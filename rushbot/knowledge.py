"""Learned values harvested from the server's own `reveal` blocks.

The `/answer` response always carries the true value of every option in the
answered puzzle. That makes each run a labelling pass: whatever the public
datasets cannot price is recorded here and reused when the same
(family, context, entity) triple shows up again.
"""
from __future__ import annotations

import json
import os
import threading

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data",
                    "knowledge.jsonl")


def ctx_key(puzzle: dict) -> str:
    ctx = dict(puzzle.get("context") or {})
    sq = puzzle.get("soulsquares") or {}
    if sq.get("minute") is not None:
        ctx["minute"] = sq["minute"]
    mm = puzzle.get("minimap") or {}
    if mm.get("matchId") is not None:
        ctx["match"] = mm["matchId"]
    parts = [f"{k}={ctx[k]}" for k in sorted(ctx)]
    return "|".join(parts)


def _eid_xy(eid: int):
    """Invert statlocker's square entityId -> (x, y) grid coords.

    A square's id encodes its position: eid = 2048*gx + 0.5*gy + 4195328,
    where gx = x/128 and gy = y/128 (the map grid step).
    """
    v = int(eid) - 4195328
    gx = round(v / 2048)
    gy = 2 * (v - 2048 * gx)
    return gx * 128, gy * 128


class Knowledge:
    def __init__(self, path: str = PATH):
        self.path = path
        self.lock = threading.Lock()
        self.store = {}
        self._load()

    def _load(self):
        try:
            with open(self.path, encoding="utf8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    self.store[(r["family"], r.get("ctx", ""), int(r["entityId"]))] = float(r["value"])
        except OSError:
            pass

    def __len__(self):
        return len(self.store)

    # families whose value is a property of the entity itself, shared across asks
    ALIAS_GROUPS = (
        ("unit_height", "scale_unit_height", "est_unit_height"),
        ("unit_health", "est_unit_health"),
        ("unit_souls",),
    )

    def _aliases(self, family: str):
        for group in self.ALIAS_GROUPS:
            if family in group:
                return group
        return (family,)

    def get(self, puzzle: dict, entity_id):
        ctx = ctx_key(puzzle)
        fams = self._aliases(puzzle.get("family"))
        for fam in fams:
            v = self.store.get((fam, ctx, int(entity_id)))
            if v is not None:
                return v
        # soul squares: souls grow with time, so scale the nearest known minute
        sq = puzzle.get("soulsquares") or {}
        minute = sq.get("minute")
        if fams[0] == "soul_squares" and minute:
            best = None
            for (fam, c, eid), val in self.store.items():
                if fam != "soul_squares" or eid != int(entity_id) or not c.startswith("minute="):
                    continue
                try:
                    known_min = float(c.split("=", 1)[1].split("|")[0])
                except (ValueError, IndexError):
                    continue
                est = val * (float(minute) / known_min) if known_min else val
                if best is None or abs(known_min - float(minute)) < best[0]:
                    best = (abs(known_min - float(minute)), est)
            if best:
                return best[1]
        return None

    def soul_samples(self):
        """Every revealed soul square as (x, y, minute, souls)."""
        out = []
        for (fam, ctx, eid), val in self.store.items():
            if fam != "soul_squares":
                continue
            minute = None
            for part in ctx.split("|"):
                if part.startswith("minute="):
                    try:
                        minute = float(part.split("=", 1)[1])
                    except ValueError:
                        minute = None
                    break
            if minute is None:
                continue
            x, y = _eid_xy(eid)
            out.append((x, y, minute, val))
        return out

    def soul_nearest(self, x: float, y: float, minute: float):
        """Nearest learned soul sample at the same minute (~83% on pairs).

        Souls are a smooth function of map position, so the closest revealed
        square is the best predictor for an unseen one.
        """
        best = None
        for sx, sy, sm, sv in self.soul_samples():
            if sm != minute:
                continue
            d = (sx - x) ** 2 + (sy - y) ** 2
            if best is None or d < best[0]:
                best = (d, sv)
        return best[1] if best else None

    def learn(self, puzzle: dict, reveal: dict) -> int:
        """Absorb one reveal block; returns number of new values."""
        if not reveal:
            return 0
        opts = {o["id"]: o for o in (puzzle.get("options") or [])
                if o.get("entityId") is not None}
        rows = []
        for o in reveal.get("options") or []:
            oid, val = o.get("id"), o.get("value")
            if oid not in opts or not isinstance(val, (int, float)):
                continue
            key = (puzzle.get("family"), ctx_key(puzzle), int(opts[oid]["entityId"]))
            new = float(val)
            if self.store.get(key) == new:
                continue
            self.store[key] = new
            rows.append({"family": key[0], "ctx": key[1], "entityId": key[2], "value": new})
            for fam in self._aliases(key[0]):
                self.store[(fam, key[1], key[2])] = new
        if rows:
            with self.lock:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                with open(self.path, "a", encoding="utf8") as f:
                    for r in rows:
                        f.write(json.dumps(r) + "\n")
        return len(rows)
