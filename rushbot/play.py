"""Play Statlockle Rush: solve every puzzle up front, then answer at min latency.

A run costs one puzzle cycle per answer (server enforces a 3s countdown per
puzzle), so a full 300-puzzle run takes ~16 minutes. Correct answers answered
inside `fastMs` score `basePoints * difficulty * 0.5 * 4`.
"""
from __future__ import annotations

import json
import os
import random
import time

from .api import ApiError, Client, scoring, wait_for_go
from .data import Data
from .knowledge import Knowledge, ctx_key
from .solve import GUESS, KNOWN, solve

RUNS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "runs")


def plan(d: Data, kn: Knowledge, puzzles: list) -> list:
    """Pre-solve the whole run: [(puzzle, body, confidence, note)]."""
    out = []
    for p in puzzles:
        body, conf, note = solve(d, kn, p)
        out.append((p, body, conf, note))
    return out


class Runner:
    def __init__(self, client: Client | None = None, data: Data | None = None,
                 knowledge: Knowledge | None = None, log: bool = True,
                 refresh: bool = False):
        self.client = client or Client()
        self.data = data or Data(client=self.client, refresh=refresh)
        self.kn = knowledge or Knowledge()
        self.log = log
        os.makedirs(RUNS_DIR, exist_ok=True)

    @staticmethod
    def _expected_mult(puzzle: dict, delay_ms: int) -> float:
        speed = puzzle.get("speed") or {}
        fast = float(speed.get("fastMs") or 1500)
        par = float(speed.get("parMs") or fast * 2)
        if delay_ms <= fast:
            return 4.0
        if delay_ms >= par:
            return 1.0
        frac = (delay_ms - fast) / max(1.0, par - fast)
        return 4.0 - 3.0 * frac

    def _pick_start(self, nightmare: bool, window: int, max_unknown: int,
                    tries: int, quiet: bool, delay_ms: int = 0,
                    min_expected: int = 0):
        """Start runs until the opening ladder looks worth playing.

        Only the last started run is ever played: starting another one discards
        the previous deal, so a rejected run is never left half-alive.
        """
        start = None
        for attempt in range(max(1, tries)):
            start = self.client.start(nightmare=nightmare)
            solved = plan(self.data, self.kn, start["puzzles"][:window])
            unknown = [p for p, _, c, _ in solved if c != KNOWN]
            expect = sum(self._expected_mult(p, delay_ms or 350) *
                         float(p.get("basePoints", 100)) * float(p.get("difficulty", 1.0)) * 0.5
                         for p, _, c, _ in solved if c == KNOWN)
            if not quiet:
                print(f"  deal {attempt + 1}/{tries}: {len(unknown)} unknown, "
                      f"expected {int(expect)} over first {window}")
            if len(unknown) <= max_unknown and expect >= min_expected:
                return start
        return start

    def _answer(self, run_id: str, payload: dict, start: dict, puzzle: dict,
                pace: float, human: bool, latency: bool):
        """One go/wait/pace/answer cycle with 409 retry; None if never accepted."""
        res = None
        for attempt in range(6):
            issued = time.time()
            go_at = self.client.go(run_id)
            wait_for_go(go_at, issued,
                        countdown_ms=int(start.get("countdownMs", 3000)),
                        extra_pad_ms=attempt * 400)
            if human:
                r = random.random()
                if r < 0.65:
                    wait = random.uniform(3000, 8000)
                elif r < 0.93:
                    wait = random.uniform(8000, 16000)
                else:
                    wait = random.uniform(16000, 30000)
                time.sleep(wait / 1000.0)
            elif pace:
                time.sleep(pace / 1000.0)
            mm = puzzle.get("minimap") or {}
            watch = float(mm.get("watchMs") or 0)
            if watch:
                time.sleep(watch / 1000.0)
            if latency:
                speed = puzzle.get("speed") or {}
                fast = float(speed.get("fastMs") or 1500)
                par = float(speed.get("parMs") or fast * 2)
                # target the human middle of *this* puzzle's speed window, add the
                # server's playStart offset (~1.8s) so measured solveMs lands
                # between fast and par, plus an occasional long stare like a person
                delay = fast + (par - fast) * random.uniform(0.35, 0.65) + 1800
                if random.random() < 0.1:
                    delay += random.uniform(1000, 2500)
                time.sleep(delay / 1000.0)
            try:
                res = self.client.answer(run_id, payload)
                break
            except ApiError as e:
                if e.status == 409:
                    time.sleep(0.25)
                    continue
                raise
        return res

    def play(self, nightmare: bool = False, max_puzzles: int = 300,
             target_score: int | None = None, quiet: bool = False,
             dry: bool = False, latency: bool = False,
             read_speed: str = "fast", delay_ms: int = 0, pick_window: int = 0,
             finish: bool = True, adapt: bool = False, reveal_ms: int = 0,
             human: bool = False,
             min_expected: int = 0,
             max_unknown: int = 2, pick_tries: int = 1) -> dict:
        if pick_window and pick_tries > 1:
            start = self._pick_start(nightmare, pick_window, max_unknown, pick_tries,
                                     quiet, delay_ms, min_expected)
        else:
            start = self.client.start(nightmare=nightmare)
        run_id, puzzles = start["runId"], start["puzzles"]
        puzzles = puzzles[:max_puzzles]
        solved = plan(self.data, self.kn, puzzles)
        if not quiet:
            known = sum(1 for _, _, c, _ in solved if c == KNOWN)
            print(f"run {run_id}: {len(solved)} puzzles, solved {known}, "
                  f"max score {sum(scoring(p) for p in puzzles)}")

        stamp = time.strftime("%Y%m%d-%H%M%S")
        logf = None
        if self.log and not dry:
            logf = open(os.path.join(RUNS_DIR, f"{stamp}.jsonl"), "w", encoding="utf8")

        score = 0
        strikes = 0
        answered = 0
        per_family = {}
        submitted = []
        pace = float(delay_ms)
        try:
            for i, (p, body, conf, note) in enumerate(solved):
                answered = i
                if reveal_ms:
                    time.sleep(reveal_ms / 1000.0)
                if p["type"] == "chain":
                    # chain puzzles resolve one comparison at a time; each answer
                    # carries {"step": n, "guess": "higher"|"lower"} and the server
                    # marks done only after the final step
                    guesses = body.get("steps") or []
                    res = None
                    for step, guess in enumerate(guesses):
                        step_payload = {"index": i, "puzzleId": p["id"],
                                        "readSpeed": read_speed,
                                        "step": step, "guess": guess}
                        # chain resolves step-by-step; each step already waits the
                        # countdown, so a slow human pace here blows the whole-chain
                        # parMs and the server grades it wrong
                        res = self._answer(run_id, step_payload, start, p,
                                           0.0, False, False)
                        if res is None:
                            raise ApiError(0, "chain answer never accepted")
                        if res.get("done"):
                            break
                    # finish re-checks answers against this full-sequence record
                    payload = {"index": i, "puzzleId": p["id"],
                               "readSpeed": read_speed, "steps": guesses}
                else:
                    payload = {"index": i, "puzzleId": p["id"],
                               "readSpeed": read_speed}
                    payload.update(body)
                    res = self._answer(run_id, payload, start, p,
                                       pace, human, latency)
                    if res is None:
                        raise ApiError(0, "answer never accepted")

                submitted.append({k: v for k, v in payload.items()})
                if adapt:
                    seen_ms = float(res.get("solveMs") or 0)
                    if seen_ms < 3000:
                        # the server flags runs with answers a person could not have read
                        pace += (3000 - seen_ms) * 1.5 + 200
                    elif seen_ms > 6500:
                        pace -= min(1200.0, (seen_ms - 6500) * 0.4)
                    pace = max(1500.0, min(pace, 40000.0))
                    if not quiet:
                        print(f"        solveMs={seen_ms:.0f} pace={pace:.0f}")
                score = int(res.get("score", score))
                strikes = int(res.get("strikes", strikes))
                r = res.get("result") or {}
                fam = p["family"]
                st = per_family.setdefault(fam, {"n": 0, "ok": 0})
                st["n"] += 1
                st["ok"] += 1 if r.get("correct") else 0
                self.kn.learn(p, res.get("reveal") or {})
                if logf:
                    logf.write(json.dumps({"index": i, "puzzle": p, "body": body,
                                           "confidence": conf, "note": note,
                                           "result": r, "solveMs": res.get("solveMs"),
                                           "score": score, "strikes": strikes,
                                           "reveal": res.get("reveal")},
                                          ensure_ascii=False) + "\n")
                if not quiet:
                    gap = "" if conf == KNOWN else f"  << {conf}: {note}"
                    print(f"  [{i:3d}] {fam:24s} {p['type']:11s} "
                          f"{'OK ' if r.get('correct') else 'MISS'} "
                          f"+{r.get('points', 0):<5} score={score} s={strikes}{gap}")
                if res.get("over"):
                    break
                if target_score is not None and score >= target_score:
                    break
        finally:
            if logf:
                logf.close()

        final = None
        if not dry and finish:
            try:
                final = self.client.finish(run_id, submitted)
            except ApiError as e:
                final = {"error": e.message[:200]}
        summary = {"runId": run_id, "score": score, "strikes": strikes,
                   "answered": answered + 1, "per_family": per_family,
                   "finish": final}
        if not quiet:
            print(f"\nscore={score} strikes={strikes} answered={answered + 1}")
            for fam, st in sorted(per_family.items(), key=lambda kv: kv[1]["n"] - kv[1]["ok"]):
                print(f"  {fam:26s} {st['ok']:3d}/{st['n']:<3d}")
        return summary


def offline_report(start_json: str) -> None:
    """Dry-solve a saved /rush/start payload (no network)."""
    with open(start_json, encoding="utf8") as f:
        start = json.load(f)
    d = Data()
    kn = Knowledge()
    total = 0
    for p, body, conf, note in plan(d, kn, start["puzzles"]):
        total += scoring(p)
        print(f"{p['id']:>4} {p['family']:24s} {p['type']:11s} lvl{p['level']:<3} "
              f"{conf:6s} {json.dumps(body)[:80]:80s} {note[:40]}")
    print(f"\nmax score if all correct: {total}")
