"""Accuracy report: replay harvested (puzzle, reveal) pairs through the solver.

Usage:
    python -m rushbot.calibrate [samples.jsonl]

Prints per-family hit rates and the exact mismatches, which is how new family
mappings get validated before they go into a scored run.
"""
from __future__ import annotations

import json
import sys

from .data import Data
from .knowledge import Knowledge
from .solve import solve


def grade(d: Data, kn: Knowledge, puzzle: dict, reveal: dict) -> bool:
    """Did our body match the server's revealed answer?"""
    if not reveal:
        return False
    ans = reveal.get("answer") or {}
    body, _, _ = solve(d, kn, puzzle)
    ty = puzzle.get("type")

    if ty == "overunder":
        return body.get("choice") == ans.get("choice")
    if ty == "statpick":
        idx = body.get("choice")
        opts = puzzle.get("options") or []
        got = opts[idx]["id"] if isinstance(idx, int) and 0 <= idx < len(opts) else None
        return got == (ans.get("order") or [None])[0]
    if ty == "kitcheck":
        want = ans.get("choice") or (ans.get("kitcheck") or {}).get("mix")
        return body.get("choice") == want
    if ty == "rank4":
        return body.get("order") == ans.get("order")
    if ty == "chain":
        return body.get("steps") == ans.get("steps")
    if ty == "buckets":
        want = ans.get("order") or []
        got = (body.get("bins") or {}).get("high") or []
        return set(got) == set(want)
    if ty == "shopdash":
        targets = set(int(t) for t in ((puzzle.get("shop") or {}).get("targets") or []))
        return set(body.get("found") or []) == targets
    if ty in ("itemguess", "missingitem"):
        want = ans.get("found") or ans.get("items") or ans.get("order") or []
        return set(body.get("found") or []) == set(want)
    if ty in ("estimate", "scale"):
        got = body.get("value")
        want = ans.get("value")
        if got is None or want is None:
            return False
        tol = (puzzle.get("estimate") or {}).get("tolerance") or \
              (puzzle.get("scale") or {}).get("tolerance") or {}
        kind = (tol or {}).get("kind")
        tval = float((tol or {}).get("value", 0.0))
        diff = abs(float(got) - float(want))
        if kind == "pp":                     # absolute percentage points
            return diff <= tval
        if kind in ("relative", "ratio"):    # fraction of the true value
            return diff <= tval * abs(float(want))
        return diff <= 0.2 * abs(float(want))  # unknown -> 20% band
    # pair / oddoneout / reversepick / soulsquares -> order[0] is the pick
    got = (body.get("order") or [None])[0]
    want = (ans.get("order") or [None])[0]
    return got == want


def main(path: str) -> None:
    d = Data()
    kn = Knowledge()
    rows = []
    for line in open(path, encoding="utf8"):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    stats = {}
    misses = {}
    for r in rows:
        p = r["puzzle"]
        fam = p["family"]
        ok = grade(d, kn, p, r.get("reveal") or {})
        st = stats.setdefault(fam, [0, 0])
        st[1] += 1
        st[0] += 1 if ok else 0
        if not ok:
            body, conf, note = solve(d, kn, p)
            misses.setdefault(fam, []).append((p, body, note, r.get("reveal") or {}))
    tot_ok = sum(v[0] for v in stats.values())
    tot = sum(v[1] for v in stats.values())
    print(f"accuracy {tot_ok}/{tot} = {100.0 * tot_ok / max(1, tot):.1f}%\n")
    for fam, (ok, n) in sorted(stats.items(), key=lambda kv: kv[1][0] - kv[1][1]):
        flag = "" if ok == n else "  <<<"
        print(f"  {fam:26s} {ok:3d}/{n:<3d}{flag}")
    print()
    for fam, items in sorted(misses.items()):
        for p, body, note, rv in items[:2]:
            print(f"{fam} | {p['type']} | {p['prompt'].get('label')} | "
                  f"ours={json.dumps(body)[:90]} | ok={json.dumps((rv.get('answer') or {}))[:90]} "
                  f"| {note}")
            print(f"   opts={[(o['id'], o.get('name'), o.get('entityId')) for o in p.get('options', [])][:6]}")
            print(f"   vals={[(o.get('id'), o.get('value')) for o in (rv.get('options') or [])][:6]}")


if __name__ == "__main__":
    main(sys.argv[1])
