"""Build the `/answer` request body for each puzzle type.

Payload shapes mirror the client's own answer builder:
  overunder   -> {"choice": "over"|"under"}
  pair        -> {"order": [winnerId]}
  rank4       -> {"order": [id, id, id, id]}      (descending when direction=higher)
  oddoneout   -> {"order": [outlierId]}
  buckets     -> {"bins": {"high": [...], "low": [...]}}
  chain       -> {"steps": ["higher"|"lower", ...]}  (guess per adjacent pair; play answers these step-by-step as {"step": n, "guess": ...})
  estimate    -> {"value": <number>}
  scale       -> {"value": <ratio>}
  statpick    -> {"choice": <index 0..2>}
  reversepick -> {"order": [itemId]}
  soulsquares -> {"order": [optionId]}
  shopdash    -> {"found": [itemIds], "pickMs": [...]}
  itemguess   -> {"found": [itemId]}
  missingitem -> {"found": [itemId]}
  kitcheck    -> {"choice": "right"|"wrong"}
"""
from __future__ import annotations

from .data import Data, parse_num
from .knowledge import Knowledge
from .resolve import value_for

KNOWN = "known"
GUESS = "guess"


def _values(d: Data, kn: Knowledge, puzzle: dict) -> dict:
    out = {}
    for opt in puzzle.get("options") or []:
        # learned reveals are fresher than the cached datasets; prefer them
        v = kn.get(puzzle, opt["entityId"]) if opt.get("entityId") is not None else None
        if v is None:
            v = value_for(d, puzzle, opt)
        if v is not None:
            out[opt["id"]] = float(v)
    return out


def _snap_range(puzzle: dict, value: float) -> float:
    """Clamp/snap an estimate answer into the slider's grid."""
    est = puzzle.get("estimate") or {}
    lo = float(est.get("min", 0.0))
    hi = float(est.get("max", 100.0))
    step = est.get("step") or ((hi - lo) / 100.0 if hi > lo else 0.01)
    if step <= 0:
        step = 0.01
    v = min(hi, max(lo, value))
    snapped = lo + round((v - lo) / step) * step
    decimals = max(0, min(4, len(str(step).split(".")[1]) if "." in str(step) else 0))
    return round(min(hi, max(lo, snapped)), decimals)


def _item_matching_lines(d: Data, slot: str | None, lines: list) -> list:
    """Items whose properties satisfy every {key,label,value} line."""
    hits = []
    seen = set()
    for it in d.item.values():
        if slot and it.get("item_slot_type") != slot:
            continue
        if not it.get("shopable") or it.get("disabled"):
            continue
        if it.get("name") in seen:
            continue
        ok = True
        for ln in lines:
            v = d.item_prop(it["id"], label=ln.get("label"), key=ln.get("key"))
            want = parse_num(ln.get("value"))
            if v is None or want is None or abs(v - want) > 1e-6:
                ok = False
                break
        if ok:
            hits.append(it)
            seen.add(it.get("name"))
    return hits


def solve(d: Data, kn: Knowledge, puzzle: dict):
    """Return (body, confidence, note)."""
    ty = puzzle.get("type")
    opts = puzzle.get("options") or []
    ids = [o["id"] for o in opts]
    vals = _values(d, kn, puzzle)
    direction = (puzzle.get("prompt") or {}).get("direction", "higher")
    full = bool(opts) and len(vals) == len(opts)
    conf = KNOWN if full else GUESS

    if ty == "overunder":
        line = float((puzzle.get("overunder") or {}).get("line", 0))
        if vals:
            v = next(iter(vals.values()))
            choice = "over" if v >= line else "under"
            return {"choice": choice}, conf, f"value={v:.4g} line={line:g}"
        return {"choice": "over"}, GUESS, "no value"

    if ty in ("pair", "kitcheck", "reversepick", "soulsquares", "minimap", "oddoneout", "statpick"):
        if ty == "kitcheck":
            return _solve_kitcheck(d, puzzle)
        if ty == "statpick":
            return _solve_statpick(d, puzzle)
        if ty == "reversepick":
            return _solve_reversepick(d, puzzle)
        if ty == "minimap":
            return _solve_minimap(puzzle, ids)
        if ty == "oddoneout" and len(vals) == len(ids) and len(ids) >= 3:
            # the odd one out is whichever value sits furthest from the rest
            best, best_dev = None, -1.0
            for i in ids:
                rest = [vals[j] for j in ids if j != i]
                m = sum(rest) / len(rest)
                dev = abs(vals[i] - m)
                if dev > best_dev:
                    best, best_dev = i, dev
            return {"order": [best]}, KNOWN, f"outlier={vals[best]:.4g}"
        if vals and len(vals) == len(ids):
            best = max(vals, key=vals.get) if direction != "lower" else min(vals, key=vals.get)
            return {"order": [best]}, KNOWN, f"best={vals[best]:.4g}"
        if ty == "soulsquares":
            sq = puzzle.get("soulsquares") or {}
            minute = sq.get("minute")
            xy = {s.get("optionId"): (s.get("x"), s.get("y"))
                  for s in sq.get("squares") or []}

            # spatial kNN over learned soul samples (~83% on harvested pairs):
            # souls are a smooth function of map position, so the nearest
            # revealed square predicts an unseen one better than any heuristic
            pred = {}
            if minute is not None:
                for oid in ids:
                    x, y = xy.get(oid, (None, None))
                    if x is None or y is None:
                        continue
                    v = kn.soul_nearest(x, y, minute)
                    if v is not None:
                        pred[oid] = v
            if len(pred) == len(ids):
                best = max(pred, key=pred.get) if direction != "lower" else min(pred, key=pred.get)
                return {"order": [best]}, GUESS, "soul-knn"

            # cold start: |y| outranks centre alone (~61% vs 53% on pairs)
            def abs_y(oid):
                return abs((xy.get(oid) or (0.0, 0.0))[1] or 0.0)
            pick = min(ids, key=abs_y) if direction != "lower" else max(ids, key=abs_y)
            return {"order": [pick]}, GUESS, "soul-|y|"
        return {"order": [ids[0]]}, GUESS, "no value"

    if ty == "abilityorder":
        vals2 = {o["id"]: o.get("value") for o in opts}
        if all(isinstance(v, (int, float)) for v in vals2.values()):
            first = str(direction).lower() in ("first", "higher")
            order = sorted(vals2, key=vals2.get, reverse=not first)
            return {"order": order}, KNOWN, "ap order"
        return {"order": ids}, GUESS, "no ap values"

    if ty == "rank4":
        if full:
            order = sorted(ids, key=lambda i: vals[i], reverse=direction != "lower")
            return {"order": order}, KNOWN, "ranked"
        priced = [i for i in ids if i in vals]
        unpriced = [i for i in ids if i not in vals]
        rev = direction != "lower"
        order = (sorted(priced, key=lambda i: vals[i], reverse=rev)[:len(priced) // 2 + 1]
                 + unpriced
                 + sorted(priced, key=lambda i: vals[i], reverse=rev)[len(priced) // 2 + 1:])
        return {"order": order}, GUESS, f"partial {len(priced)}/{len(ids)}"

    if ty == "buckets":
        line = float((puzzle.get("buckets") or {}).get("line", 0))
        high = [i for i in ids if i in vals and vals[i] >= line]
        low = [i for i in ids if i in vals and vals[i] < line]
        unk = [i for i in ids if i not in vals]
        # unknown options still score a coin flip; split them instead of leaving blanks
        for k, i in enumerate(unk):
            (high if k % 2 == 0 else low).append(i)
        conf = KNOWN if not unk else GUESS
        return {"bins": {"high": high, "low": low}}, conf, f"line={line:g} unk={len(unk)}"

    if ty == "chain":
        if full and len(ids) > 1:
            steps = ["higher" if vals[ids[i]] >= vals[ids[i - 1]] else "lower"
                     for i in range(1, len(ids))]
            return {"steps": steps}, KNOWN, "chain"
        return {"steps": ["higher"] * max(0, len(ids) - 1)}, GUESS, "no value"

    if ty == "estimate":
        if vals:
            v = next(iter(vals.values()))
            return {"value": _snap_range(puzzle, v)}, KNOWN, f"value={v:.4g}"
        return {"value": float((puzzle.get("estimate") or {}).get("min", 0))}, GUESS, "no value"

    if ty == "scale":
        sc = puzzle.get("scale") or {}
        ref = next((o for o in opts if o["id"] == sc.get("referenceId")), None)
        tgt = next((o for o in opts if o["id"] == sc.get("targetId")), None)
        if ref and tgt and full:
            ratio = vals[tgt["id"]] / vals[ref["id"]] if vals.get(ref["id"]) else None
            if ratio:
                lo = float(sc.get("minRatio", 0.1))
                hi = float(sc.get("maxRatio", 10.0))
                return {"value": round(min(hi, max(lo, ratio)), 4)}, KNOWN, f"ratio={ratio:.4g}"
        return {"value": float(sc.get("startRatio", 1.0))}, GUESS, "no ratio"

    if ty == "shopdash":
        targets = list((puzzle.get("shop") or {}).get("targets") or [])
        # human pick cadence: ~700ms first, ~250ms apart (0ms reads as a bot)
        ms = [700 + k * 250 for k in range(len(targets))]
        return ({"found": [int(t) for t in targets], "pickMs": ms},
                KNOWN, "targets given")

    if ty == "itemguess":
        lines = ((puzzle.get("reversepick") or {}).get("lines") or [])
        slot = (puzzle.get("reversepick") or {}).get("slot")
        hits = _item_matching_lines(d, slot, lines)
        if hits:
            return {"found": [int(hits[0]["id"])]}, KNOWN, f"item={hits[0]['name']}"
        return {"found": []}, GUESS, "no item"

    if ty == "missingitem":
        mi = puzzle.get("missingitem") or {}
        given = {int(i["itemId"]) for i in (mi.get("items") or [])}
        cand = d.item_by_slot_cost(mi.get("slot"), mi.get("tier"),
                                   parse_num(mi.get("cost")), exclude=given)
        cand = [c for c in cand if c.get("shopable") and not c.get("disabled")]
        if len(cand) == 1:
            return {"found": [int(cand[0]["id"])]}, KNOWN, f"missing={cand[0]['name']}"
        return {"found": []}, GUESS, f"candidates={len(cand)}"

    if ty == "iconcost":
        return _solve_iconcost(puzzle)

    # fall back to the first option
    return {"order": ids[:1]}, GUESS, f"unhandled type {ty}"


def _solve_statpick(d: Data, puzzle: dict):
    """Pick the stat line matching the real item; options all share one itemId."""
    sp = puzzle.get("statpick") or {}
    choices = sp.get("choices") or []
    opts = puzzle.get("options") or []
    item_id = next((o.get("entityId") for o in opts if o.get("entityId")), None)
    if item_id is not None:
        for idx, lines in enumerate(choices):
            ok = True
            for ln in lines:
                v = d.item_prop(int(item_id), label=ln.get("label"), key=ln.get("key"))
                want = parse_num(ln.get("value"))
                if v is None or want is None or abs(v - want) > 1e-6:
                    ok = False
                    break
            if ok:
                return {"choice": idx}, KNOWN, f"index={idx}"
    return {"choice": 0}, GUESS, "no stat match"


def _solve_reversepick(d: Data, puzzle: dict):
    rp = puzzle.get("reversepick") or {}
    lines = rp.get("lines") or []
    for o in puzzle.get("options") or []:
        ok = True
        for ln in lines:
            v = d.item_prop(int(o["entityId"]), label=ln.get("label"), key=ln.get("key"))
            want = parse_num(ln.get("value"))
            if v is None or want is None or abs(v - want) > 1e-6:
                ok = False
                break
        if ok:
            return {"order": [o["id"]]}, KNOWN, "item matched"
    return {"order": [(puzzle.get("options") or [{}])[0].get("id", "a1")]}, GUESS, "no match"


def _solve_kitcheck(d: Data, puzzle: dict):
    """A kit is correct only when the four icons sit in ability-slot order 1..4.

    Icons resolve to abilities through items_full asset urls, so both a swapped
    icon and a shuffled order are detectable from the payload.
    """
    import re
    m = re.match(r"This is (.+?)'s kit\.", (puzzle.get("prompt") or {}).get("question", ""))
    hero_id = d.hero_id_by_name(m.group(1)) if m else None
    opts = puzzle.get("options") or []
    slots = [d.ability_slot_for_image(o.get("image")) for o in opts]
    keys = [k for k, _ in slots] if all(slots) else None
    if keys and all(k is not None for k in keys):
        want = list(range(1, len(keys) + 1))
        ok = keys == want and (hero_id is None or all(h == hero_id for _, h in slots))
        return ({"choice": "right"} if ok else {"choice": "wrong"}), KNOWN, f"slots={keys}"
    known = [sl[0] for sl in slots if sl and sl[0] is not None]
    if len(known) >= 2 and any(known[i] > known[j] for i in range(len(known)) for j in range(i + 1, len(known))):
        return {"choice": "wrong"}, GUESS, "slot inversion"
    return {"choice": "right"}, GUESS, "kit unverifiable"


OBJECTIVE_KINDS = {
    "base guardian": "barracks", "base guardians": "barracks",
    "guardian": "guardian", "guardians": "guardian",
    "walker": "walker", "walkers": "walker",
    "shrine": "shrine", "shrines": "shrine",
    "barrack": "barracks", "barracks": "barracks",
    "patron": "patron", "patrons": "patron",
}


def _solve_iconcost(puzzle: dict):
    ic = puzzle.get("iconcost") or {}
    items = ic.get("items") or []
    pairs = ic.get("pairs") or []
    if not items or not pairs:
        return {"picks": [], "pickMs": []}, GUESS, "no pairs"
    picks, ms = [], []
    step = max(int(ic.get("minPickMs") or 150), 600)
    for k, pair in enumerate(pairs):
        try:
            a, b = int(pair[0]), int(pair[1])
        except (TypeError, ValueError, IndexError):
            return {"picks": [], "pickMs": []}, GUESS, "bad pair"
        ca = parse_num((items[a] or {}).get("cost"))
        cb = parse_num((items[b] or {}).get("cost"))
        if ca is None or cb is None:
            return {"picks": [], "pickMs": []}, GUESS, "no cost"
        picks.append(0 if ca > cb else 1)
        ms.append(step + k * 200)
    return {"picks": picks, "pickMs": ms}, KNOWN, f"{len(picks)} pairs"


def _solve_last_seen(mm: dict):
    """Last substep at which the target hero was inside a teammate's vision range.

    Positions arrive at `hz` per second; the server samples `substeps` per
    interval and answers with the interpolated position where vision was lost.
    """
    import math
    frames = mm.get("frames") or []
    teams = mm.get("teams") or []
    tgt = mm.get("target")
    rng = float(mm.get("visionRange") or 0)
    pt = mm.get("perspTeam")
    substeps = max(1, int(mm.get("substeps") or 1))
    if not frames or tgt is None or not rng or len(frames) < 2:
        return None
    observers = [i for i, t in enumerate(teams) if t == pt and i != tgt]
    if not observers:
        return None

    def at(f0, f1, i, t):
        return (f0[2 * i] + (f1[2 * i] - f0[2 * i]) * t,
                f0[2 * i + 1] + (f1[2 * i + 1] - f0[2 * i + 1]) * t)

    last = None
    for k in range(len(frames) - 1):
        for step in range(substeps + 1):
            t = step / float(substeps)
            tx, ty = at(frames[k], frames[k + 1], tgt, t)
            for i in observers:
                ox, oy = at(frames[k], frames[k + 1], i, t)
                if math.hypot(ox - tx, oy - ty) <= rng:
                    last = (round(tx), round(ty))
                    break
    return last


def _solve_minimap(puzzle: dict, ids: list):
    """'objective' asks are countable; 'last seen' asks are geometric."""
    mm = puzzle.get("minimap") or {}
    if mm.get("ask") != "objective":
        pt = _solve_last_seen(mm)
        if pt:
            return {"x": pt[0], "y": pt[1]}, KNOWN, "last visible substep"
        return {"x": 0, "y": 0}, GUESS, "last-seen unsolved"
    label = ((puzzle.get("prompt") or {}).get("label") or "").lower().strip()
    kind = OBJECTIVE_KINDS.get(label)
    if kind is None:
        for word in label.split():
            kind = OBJECTIVE_KINDS.get(word)
            if kind:
                break
    opts = puzzle.get("options") or []
    if opts and all(o.get("kind") == "objective" for o in opts):
        return _solve_objective_unit(puzzle, opts, kind)
    counts = {int(o.get("entityId", 0)): 0 for o in opts}
    for o in mm.get("objectives") or []:
        if kind and o.get("kind") != kind:
            continue
        t = int(o.get("team", 0))
        counts[t] = counts.get(t, 0) + 1
    if not counts or not opts:
        return {"order": [ids[0]]}, GUESS, "no objective data"
    if max(counts.values()) == 0:
        return {"order": [ids[0]]}, GUESS, "objective kind absent"
    direction = ((puzzle.get("prompt") or {}).get("direction") or "more").lower()
    by_team = {o.get("entityId"): o["id"] for o in opts}
    team = max(counts, key=counts.get) if direction == "more" else min(counts, key=counts.get)
    if team not in by_team:
        return {"order": [ids[0]]}, GUESS, f"team {team} not an option"
    return {"order": [by_team[team]]}, KNOWN, f"{label} {counts}"


OBJECTIVE_TEAMS = {"hidden king": 0, "archmother": 1}
LANE_NAMES = {"yellow": 1, "blue": 4, "green": 6}


def _solve_objective_unit(puzzle: dict, opts: list, kind):
    """Pick the objective with the highest/lowest hp ('Which walker had least HP?')."""
    mm = puzzle.get("minimap") or {}
    objs = mm.get("objectives") or []
    values = {}
    for o in opts:
        name = (o.get("name") or "").lower()
        team = next((t for word, t in OBJECTIVE_TEAMS.items() if word in name), None)
        lane = next((n for word, n in LANE_NAMES.items() if word in name), None)
        if team is None or lane is None:
            continue
        hit = next((x for x in objs
                    if x.get("kind") == kind and int(x.get("team", -1)) == team
                    and int(x.get("lane", -1)) == lane), None)
        if hit is not None:
            values[o["id"]] = float(hit.get("hp", 0))
    direction = ((puzzle.get("prompt") or {}).get("direction") or "more").lower()
    low = direction in ("least", "fewer", "lowest", "less")
    if len(values) == len(opts):
        best = min(values, key=values.get) if low else max(values, key=values.get)
        return {"order": [best]}, KNOWN, f"{kind} hp {values}"
    return {"order": [opts[0]["id"]]}, GUESS, f"hp partial {len(values)}/{len(opts)}"
