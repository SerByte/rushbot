"""Tests for rushbot.data — value parsing and the seeded cache view."""
from __future__ import annotations

from rushbot.data import Data, parse_num


def test_parse_num_scalars():
    assert parse_num(4) == 4.0
    assert parse_num(4.5) == 4.5
    assert parse_num(-3) == -3.0


def test_parse_num_strings():
    assert parse_num("25 %") == 25.0
    assert parse_num("4") == 4.0
    assert parse_num("cost: -12.5g") == -12.5


def test_parse_num_empty():
    assert parse_num(None) is None
    assert parse_num(True) is None      # bool is deliberately excluded
    assert parse_num("") is None
    assert parse_num("abc") is None


def test_item_prop_by_label_and_key():
    d = Data()
    d._mem["item"] = {
        10: {
            "id": 10,
            "properties": {
                "a": {"label": "Weapon Power", "value": "42"},
                "b": {"label": "Cost", "value": "500"},
            },
        }
    }
    assert d.item_prop(10, label="Weapon Power") == 42.0
    assert d.item_prop(10, key="b") == 500.0
    assert d.item_prop(10, label="Missing") is None
    assert d.item_prop(99, label="Weapon Power") is None


def test_item_by_slot_cost_excludes_unshoppable():
    d = Data()
    d._mem["item"] = {
        10: {"id": 10, "item_slot_type": "weapon", "item_tier": 3,
             "cost": 500, "shopable": True, "name": "A"},
        11: {"id": 11, "item_slot_type": "weapon", "item_tier": 3,
             "cost": 500, "shopable": False, "name": "B"},
        12: {"id": 12, "item_slot_type": "armor", "item_tier": 3,
             "cost": 500, "shopable": True, "name": "C"},
    }
    hits = d.item_by_slot_cost("weapon", 3, 500)
    assert [i["id"] for i in hits] == [10]


def test_total_hero_games_pools_matches():
    d = Data()
    d._mem["hero_stats"] = {1: {"matches": 120}, 2: {"matches": 240}}
    # two heroes -> 360 pooled team-games -> /12
    assert d.total_hero_games() == 30.0
