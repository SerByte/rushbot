"""CLI.

    python -m rushbot plan  start.json          # dry-solve a saved run payload
    python -m rushbot play  [--nightmare] [--cookie FILE] [--max N]
    python -m rushbot calib samples.jsonl       # per-family accuracy report
    python -m rushbot board                     # current season leaderboard
    python -m rushbot fetch                     # refresh cached datasets
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from .api import Client
from .data import Data
from .knowledge import Knowledge


def _cookie(path):
    if not path:
        return None
    with open(path, encoding="utf8") as f:
        raw = f.read().strip()
    if raw.lower().startswith("cookie:"):
        raw = raw[7:].strip()
    return raw


def main(argv=None):
    ap = argparse.ArgumentParser(prog="rushbot")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_brave = sub.add_parser("brave", help="pull the Steam session out of a local browser profile")
    p_brave.add_argument("--browser", default="brave", choices=["brave", "chrome", "edge"])
    p_brave.add_argument("--profile", default="Default")
    p_brave.add_argument("--out", default=None)

    p_plan = sub.add_parser("plan", help="dry-solve a saved /rush/start payload")
    p_plan.add_argument("path")

    p_play = sub.add_parser("play", help="play a live run")
    p_play.add_argument("--nightmare", action="store_true")
    p_play.add_argument("--cookie", help="file containing the browser Cookie header")
    p_play.add_argument("--max", type=int, default=300)
    p_play.add_argument("--target", type=int, default=None,
                        help="stop once score reaches this (default: beat leaderboard #1)")
    p_play.add_argument("--dry", action="store_true", help="solve without submitting")
    p_play.add_argument("--read-speed", default="fast", choices=["fast", "normal", "slow"])
    p_play.add_argument("--reveal", type=int, default=0,
                        help="ms to wait for the reveal before calling /go (client does ~1800)")
    p_play.add_argument("--human", action="store_true",
                        help="human-like, heavy-tailed answer pacing")
    p_play.add_argument("--adapt", action="store_true",
                        help="tune answer pacing from the server-reported solveMs")
    p_play.add_argument("--no-finish", action="store_true",
                        help="let the server finalize the run itself")
    p_play.add_argument("--delay", type=int, default=0,
                        help="fixed extra ms after the countdown before answering")
    p_play.add_argument("--pick-window", type=int, default=0,
                        help="judge the opening N puzzles before committing")
    p_play.add_argument("--pick-tries", type=int, default=1,
                        help="number of runs to inspect when picking")
    p_play.add_argument("--max-unknown", type=int, default=2)
    p_play.add_argument("--min-expected", type=int, default=0)
    p_play.add_argument("--refresh", action="store_true",
                        help="re-download public datasets first (they drift)")
    p_play.add_argument("--latency", action="store_true",
                        help="answer after a human-like delay instead of the 350ms floor")

    p_calib = sub.add_parser("calib", help="accuracy report over harvested samples")
    p_calib.add_argument("path")

    p_seed = sub.add_parser("seed", help="ingest harvested samples into the knowledge store")
    p_seed.add_argument("path")

    p_auth = sub.add_parser("auth", help="verify the Steam session cookie")
    p_auth.add_argument("--cookie", required=True)

    p_runs = sub.add_parser("runs", help="play several runs back to back (learning loop)")
    p_runs.add_argument("--runs", type=int, default=3)
    p_runs.add_argument("--cookie")
    p_runs.add_argument("--max", type=int, default=150)
    p_runs.add_argument("--latency", action="store_true")
    p_runs.add_argument("--delay", type=int, default=0)
    p_runs.add_argument("--adapt", action="store_true")
    p_runs.add_argument("--refresh", action="store_true")

    p_vig = sub.add_parser("vigil", help="keep playing until a run is finally ranked")
    p_vig.add_argument("--cookie")
    p_vig.add_argument("--every", type=int, default=10, help="minutes between runs")
    p_vig.add_argument("--rounds", type=int, default=24)
    p_vig.add_argument("--max", type=int, default=300)
    p_vig.add_argument("--delay", type=int, default=6000)
    p_vig.add_argument("--human", action="store_true")
    p_vig.add_argument("--tries", type=int, default=3)
    p_vig.add_argument("--min-expected", type=int, default=0)

    sub.add_parser("board", help="print the season leaderboard top")
    sub.add_parser("fetch", help="refresh cached public datasets")

    args = ap.parse_args(argv)

    if args.cmd == "brave":
        from .brave import cookie_file
        path = cookie_file(args.browser, args.profile, out=args.out)
        print(f"cookie header written to {path}")
        st = Client(cookie_header=_cookie(path)).request("/api/auth/status")
        print("auth:", json.dumps(st)[:200])
        return 0

    if args.cmd == "plan":
        from .play import offline_report
        offline_report(args.path)
        return 0

    if args.cmd == "calib":
        from .calibrate import main as calib_main
        calib_main(args.path)
        return 0

    if args.cmd == "seed":
        import json as _json
        kn = Knowledge()
        added = 0
        for line in open(args.path, encoding="utf8"):
            try:
                r = _json.loads(line)
            except ValueError:
                continue
            added += kn.learn(r.get("puzzle") or {}, r.get("reveal") or {})
        print(f"knowledge rows: {len(kn)} (+{added})")
        return 0

    if args.cmd == "auth":
        c = Client(cookie_header=_cookie(args.cookie))
        st = c.request("/api/auth/status")
        print("auth/status:", json.dumps(st)[:300])
        me = c.request("/api/auth/profile", allow_404=True)
        print("profile:", json.dumps(me)[:300] if me else "not signed in")
        return 0

    if args.cmd == "runs":
        from .play import Runner
        client = Client(cookie_header=_cookie(args.cookie))
        best = 0
        target = None
        try:
            lb = client.leaderboard(size=1)
            top = (lb.get("entries") or [{}])[0].get("score", 0)
            if top:
                target = int(top) + 1
                print(f"leaderboard #1 = {top}; target = {target}")
        except Exception as e:  # noqa: BLE001
            print(f"leaderboard unavailable: {e}")
        for n in range(args.runs):
            print(f"--- run {n + 1}/{args.runs}")
            try:
                summary = Runner(client=client, refresh=args.refresh).play(
                    max_puzzles=args.max, quiet=False, target_score=target,
                    latency=args.latency, delay_ms=args.delay, adapt=args.adapt)
            except Exception as e:  # noqa: BLE001
                print("run failed:", e)
                time.sleep(20)
                continue
            best = max(best, summary["score"])
            print(f"    best so far: {best}")
            if target and best >= target:
                print("target beaten")
                break
            time.sleep(5)
        print("best:", best)
        return 0

    if args.cmd == "vigil":
        from .play import Runner
        client = Client(cookie_header=_cookie(args.cookie))
        for n in range(args.rounds):
            print(f"--- round {n + 1}/{args.rounds} {time.strftime('%H:%M:%S')}")
            try:
                summary = Runner(client=client, refresh=True).play(
                    max_puzzles=args.max, quiet=True, delay_ms=args.delay, human=args.human,
                    pick_window=60, pick_tries=args.tries,
                    min_expected=args.min_expected)
            except Exception as e:  # noqa: BLE001
                print("run failed:", e)
                time.sleep(60)
                continue
            fin = summary.get("finish") or {}
            print(f"    score={summary['score']} answered={summary['answered']} "
                  f"valid={fin.get('valid')} ranked={fin.get('ranked')} rank={fin.get('rank')}")
            if fin.get("ranked") and summary["score"] > 1746:
                me = client.request("/leaderboard?page=0&size=1").get("me")
                print("RANKED! board entry:", me)
                if me and me.get("score") and me["rank"] == 1:
                    return 0
            time.sleep(max(30, args.every * 60))
        return 1

    if args.cmd == "board":
        c = Client()
        lb = c.leaderboard(size=5)
        season = lb.get("season") or {}
        print(f"season {season.get('name')} total={lb.get('total')}")
        for e in lb.get("entries") or []:
            print(f"  #{e['rank']} {e['name']:20s} {e['score']:6d} (attempts {e['attempts']})")
        return 0

    if args.cmd == "fetch":
        Data(refresh=True)
        print("datasets refreshed")
        return 0

    if args.cmd == "play":
        from .play import Runner
        client = Client(cookie_header=_cookie(args.cookie))
        target = args.target
        if target is None:
            try:
                lb = client.leaderboard(size=1)
                top = (lb.get("entries") or [{}])[0].get("score", 0)
                target = int(top) + 1 if top else None
                print(f"leaderboard #1 = {top}; target = {target}")
            except Exception as e:  # noqa: BLE001
                print(f"leaderboard unavailable: {e}")
        runner = Runner(client=client, refresh=args.refresh)
        summary = runner.play(nightmare=args.nightmare, max_puzzles=args.max,
                              target_score=target, dry=args.dry, latency=args.latency,
                              read_speed=args.read_speed, delay_ms=args.delay,
                              finish=not args.no_finish, adapt=args.adapt, human=args.human,
                              reveal_ms=args.reveal,
                              pick_window=args.pick_window,
                              pick_tries=args.pick_tries, max_unknown=args.max_unknown,
                              min_expected=args.min_expected)
        print(json.dumps({k: v for k, v in summary.items() if k != "per_family"}))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
