"""Tests for rushbot.knowledge — context keys, entityId geometry, and the store."""
from __future__ import annotations

from rushbot.knowledge import Knowledge, _eid_xy, ctx_key


def test_ctx_key_context():
    assert ctx_key({"context": {"heroId": 5, "lane": "mid"}}) == "heroId=5|lane=mid"


def test_ctx_key_soulsquares_minute():
    assert ctx_key({"context": {}, "soulsquares": {"minute": 10}}) == "minute=10"


def test_ctx_key_minimap_match():
    assert ctx_key({"context": {}, "minimap": {"matchId": "m42"}}) == "match=m42"


def test_ctx_key_empty():
    assert ctx_key({}) == ""


def test_eid_xy_origin():
    assert _eid_xy(4195328) == (0, 0)


def test_eid_xy_known_offsets():
    # eid = 2048*gx + 0.5*gy + 4195328; x = gx*128, y = gy*128
    assert _eid_xy(4195328 + 2048) == (128, 0)   # gx=1
    assert _eid_xy(4195328 + 2) == (0, 512)      # gy=4


def test_learn_and_get(kn):
    puzzle = {
        "family": "unit_health",
        "context": {"heroId": 1},
        "options": [{"id": "a", "entityId": 10}],
    }
    reveal = {"options": [{"id": "a", "value": 700.0}]}
    assert kn.learn(puzzle, reveal) == 1
    assert kn.get(puzzle, 10) == 700.0
    assert kn.get(puzzle, 11) is None


def test_learn_aliases_across_families(kn):
    # unit_height and est_unit_height are aliased in ALIAS_GROUPS
    puzzle = {
        "family": "unit_height",
        "options": [{"id": "a", "entityId": 10}],
    }
    reveal = {"options": [{"id": "a", "value": 12.6}]}
    kn.learn(puzzle, reveal)
    alias_puzzle = {"family": "est_unit_height", "options": [{"id": "a", "entityId": 10}]}
    assert kn.get(alias_puzzle, 10) == 12.6


def test_learn_ignores_non_numeric_reveal(kn):
    puzzle = {
        "family": "unit_health",
        "options": [{"id": "a", "entityId": 10}],
    }
    reveal = {"options": [{"id": "a", "value": "unknown"}]}
    assert kn.learn(puzzle, reveal) == 0
    assert len(kn) == 0


def test_soul_nearest(tmp_path):
    kn = Knowledge(path=str(tmp_path / "k.jsonl"))
    for eid, val in [(4195328, 100.0), (4195328 + 2048, 300.0)]:
        puzzle = {
            "family": "soul_squares",
            "soulsquares": {"minute": 10},
            "options": [{"id": "a", "entityId": eid}],
        }
        kn.learn(puzzle, {"options": [{"id": "a", "value": val}]})
    assert kn.soul_nearest(0, 0, 10) == 100.0
    assert kn.soul_nearest(128, 0, 10) == 300.0
    # a different minute never matches
    assert kn.soul_nearest(0, 0, 11) is None
