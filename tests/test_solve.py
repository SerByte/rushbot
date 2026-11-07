"""Tests for rushbot.solve — answer-body construction per puzzle type."""
from __future__ import annotations

from rushbot.data import Data
from rushbot.solve import GUESS, KNOWN, solve


def test_pair_higher(data, kn):
    p = {"type": "pair", "family": "unit_health",
         "prompt": {"direction": "higher"},
         "options": [{"id": "a", "entityId": 1}, {"id": "b", "entityId": 2}]}
    body, conf, _ = solve(data, kn, p)
    assert body == {"order": ["b"]}
    assert conf == KNOWN


def test_pair_lower(data, kn):
    p = {"type": "pair", "family": "unit_health",
         "prompt": {"direction": "lower"},
         "options": [{"id": "a", "entityId": 1}, {"id": "b", "entityId": 2}]}
    body, conf, _ = solve(data, kn, p)
    assert body == {"order": ["a"]}
    assert conf == KNOWN


def test_rank4_descending(data, kn):
    p = {"type": "rank4", "family": "unit_health",
         "prompt": {"direction": "higher"},
         "options": [{"id": "a", "entityId": 1}, {"id": "b", "entityId": 2},
                     {"id": "c", "entityId": 3}]}
    body, conf, _ = solve(data, kn, p)
    # 700, 900, 800 -> descending
    assert body == {"order": ["b", "c", "a"]}
    assert conf == KNOWN


def test_overunder(data, kn):
    p = {"type": "overunder", "family": "unit_health",
         "overunder": {"line": 800},
         "options": [{"id": "a", "entityId": 1}]}
    body, conf, _ = solve(data, kn, p)
    assert body == {"choice": "under"}
    assert conf == KNOWN


def test_buckets(data, kn):
    p = {"type": "buckets", "family": "unit_health",
         "buckets": {"line": 800},
         "options": [{"id": "a", "entityId": 1}, {"id": "b", "entityId": 2}]}
    body, conf, _ = solve(data, kn, p)
    assert body == {"bins": {"high": ["b"], "low": ["a"]}}
    assert conf == KNOWN


def test_chain_steps(data, kn):
    p = {"type": "chain", "family": "unit_health",
         "options": [{"id": "a", "entityId": 1}, {"id": "b", "entityId": 2},
                     {"id": "c", "entityId": 3}]}
    body, conf, _ = solve(data, kn, p)
    # 900>=700 higher; 800>=900 lower
    assert body == {"steps": ["higher", "lower"]}
    assert conf == KNOWN


def test_estimate_snaps_to_grid(data, kn):
    data._mem["hero"] = {1: {"id": 1, "starting_stats": {"max_health": {"value": 723}}}}
    p = {"type": "estimate", "family": "unit_health",
         "estimate": {"min": 0, "max": 1000, "step": 100},
         "options": [{"id": "a", "entityId": 1}]}
    body, conf, _ = solve(data, kn, p)
    assert body == {"value": 700.0}
    assert conf == KNOWN


def test_scale_ratio(data, kn):
    p = {"type": "scale", "family": "unit_health",
         "scale": {"referenceId": "ref", "targetId": "tgt",
                   "minRatio": 0.1, "maxRatio": 10.0},
         "options": [{"id": "ref", "entityId": 1}, {"id": "tgt", "entityId": 2}]}
    body, conf, _ = solve(data, kn, p)
    assert body["value"] == 1.2857
    assert conf == KNOWN


def test_shopdash_pick_cadence(data, kn):
    p = {"type": "shopdash", "shop": {"targets": [10, 20, 30]}}
    body, conf, _ = solve(data, kn, p)
    assert body == {"found": [10, 20, 30], "pickMs": [700, 950, 1200]}
    assert conf == KNOWN


def test_oddoneout_outlier(kn):
    d = Data()
    d._mem["hero"] = {
        1: {"id": 1, "starting_stats": {"max_health": {"value": 700}}},
        2: {"id": 2, "starting_stats": {"max_health": {"value": 720}}},
        3: {"id": 3, "starting_stats": {"max_health": {"value": 2000}}},
    }
    p = {"type": "oddoneout", "family": "unit_health",
         "options": [{"id": "a", "entityId": 1}, {"id": "b", "entityId": 2},
                     {"id": "c", "entityId": 3}]}
    body, conf, _ = solve(d, kn, p)
    assert body == {"order": ["c"]}
    assert conf == KNOWN


def test_soulsquares_cold_start(kn):
    p = {"type": "soulsquares",
         "soulsquares": {"minute": 10, "squares": [
             {"optionId": "a", "x": 0, "y": 100},
             {"optionId": "b", "x": 0, "y": -500},
         ]},
         "options": [{"id": "a"}, {"id": "b"}]}
    body, conf, _ = solve(Data(), kn, p)
    # no learned samples -> |y| heuristic picks the smallest |y|
    assert body == {"order": ["a"]}
    assert conf == GUESS


def test_abilityorder(data, kn):
    p = {"type": "abilityorder", "prompt": {"direction": "first"},
         "options": [{"id": "a", "value": 3}, {"id": "b", "value": 1},
                     {"id": "c", "value": 2}]}
    body, conf, _ = solve(data, kn, p)
    assert body == {"order": ["b", "c", "a"]}
    assert conf == KNOWN


def test_kitcheck_right():
    d = Data()
    d._mem["hero"] = {1: {"id": 1, "name": "Wraith"}}
    d._mem["icon_ability"] = {"icon1": 100, "icon2": 101}
    d._mem["ability"] = {
        100: {"abilityKey": 1, "heroId": 1},
        101: {"abilityKey": 2, "heroId": 1},
    }
    p = {"type": "kitcheck",
         "prompt": {"question": "This is Wraith's kit."},
         "options": [{"id": "a", "image": "icon1.png"},
                     {"id": "b", "image": "icon2.png"}]}
    body, conf, _ = solve(d, None, p)
    assert body == {"choice": "right"}
    assert conf == KNOWN


def test_iconcost_pairs(data, kn):
    p = {"type": "iconcost", "iconcost": {
        "items": [{"cost": 100}, {"cost": 200}, {"cost": 300}, {"cost": 400}],
        "pairs": [[0, 1], [2, 3]], "minPickMs": 150,
    }}
    body, conf, _ = solve(data, kn, p)
    assert body == {"picks": [1, 1], "pickMs": [600, 800]}
    assert conf == KNOWN


def test_reversepick_item_match(data, kn):
    data._mem["item"] = {
        10: {"id": 10, "properties": {"x": {"label": "Cost", "value": "500"}}}
    }
    p = {"type": "reversepick",
         "reversepick": {"lines": [{"label": "Cost", "value": "500"}]},
         "options": [{"id": "a", "entityId": 10}]}
    body, conf, _ = solve(data, kn, p)
    assert body == {"order": ["a"]}
    assert conf == KNOWN


def test_statpick_index(data, kn):
    data._mem["item"] = {
        10: {"id": 10, "properties": {"x": {"label": "Weapon Power", "value": "42"}}}
    }
    p = {"type": "statpick",
         "statpick": {"choices": [
             [{"label": "Weapon Power", "value": "42"}],
             [{"label": "Weapon Power", "value": "99"}],
         ]},
         "options": [{"id": "a", "entityId": 10}]}
    body, conf, _ = solve(data, kn, p)
    assert body == {"choice": 0}
    assert conf == KNOWN


def test_minimap_objective_count(data, kn):
    p = {"type": "minimap",
         "minimap": {"ask": "objective", "objectives": [
             {"kind": "guardian", "team": 0}, {"kind": "guardian", "team": 0}]},
         "prompt": {"label": "guardians", "direction": "more"},
         "options": [{"id": "a", "entityId": 0}, {"id": "b", "entityId": 1}]}
    body, conf, _ = solve(data, kn, p)
    assert body == {"order": ["a"]}
    assert conf == KNOWN


def test_minimap_last_seen_unsolved(data, kn):
    p = {"type": "minimap", "minimap": {"ask": "last_seen", "frames": []},
         "options": [{"id": "a"}]}
    body, conf, _ = solve(data, kn, p)
    assert body == {"x": 0, "y": 0}
    assert conf == GUESS


def test_missingitem_single_candidate(data, kn):
    data._mem["item"] = {
        10: {"id": 10, "item_slot_type": "weapon", "item_tier": 3,
             "cost": 500, "shopable": True, "name": "A"},
    }
    p = {"type": "missingitem",
         "missingitem": {"slot": "weapon", "tier": 3, "cost": 500, "items": []}}
    body, conf, _ = solve(data, kn, p)
    assert body == {"found": [10]}
    assert conf == KNOWN


def test_unhandled_type_guesses(data, kn):
    p = {"type": "totally_unknown", "options": [{"id": "a"}]}
    body, conf, note = solve(data, kn, p)
    assert body == {"order": ["a"]}
    assert conf == GUESS
    assert "unhandled" in note
