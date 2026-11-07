"""Tests for rushbot.resolve — family rules and value extraction."""
from __future__ import annotations

from rushbot.data import Data
from rushbot.resolve import ESTIMATE_ALIASES, family_rule, value_for, values_for


def _puzzle(family, direction="higher"):
    return {"family": family, "prompt": {"direction": direction}}


def test_family_rule_unknown():
    assert family_rule("nonexistent") is None
    assert family_rule("") is None


def test_estimate_alias_resolution():
    assert family_rule("est_unit_height") is family_rule("unit_height")
    assert family_rule("est_ability_casts") is family_rule("ability_casts")
    # every alias must resolve to a registered rule
    for alias in ESTIMATE_ALIASES:
        assert family_rule(alias) is not None, alias


def test_value_for_ability_casts():
    d = Data()
    d._mem["ability"] = {100: {"abilityId": 100, "casts": {"mean": 5.0}}}
    opt = {"id": "a", "entityId": 100}
    assert value_for(d, _puzzle("ability_casts"), opt) == 5.0


def test_value_for_hero_win_rate():
    d = Data()
    d._mem["hero_stats"] = {1: {"hero_id": 1, "wins": 30, "matches": 100}}
    opt = {"id": "a", "entityId": 1}
    assert value_for(d, _puzzle("hero_win_rate"), opt) == 30.0


def test_value_for_hero_pick_rate():
    d = Data()
    d._mem["hero_stats"] = {i: {"matches": 100} for i in range(12)}
    opt = {"id": "a", "entityId": 0}
    # total games = 12*100/12 = 100 -> pick rate = 100 * 100 / 100
    assert value_for(d, _puzzle("hero_pick_rate"), opt) == 100.0


def test_value_for_hero_difficulty():
    d = Data()
    d._mem["difficulty"] = {1: 3.5}
    assert value_for(d, _puzzle("hero_difficulty"), {"entityId": 1}) == 3.5


def test_value_for_item_win_rate():
    d = Data()
    d._mem["usage"] = {10: {"itemId": 10, "winRate": 0.52}}
    assert value_for(d, _puzzle("item_win_rate"), {"entityId": 10}) == 52.0


def test_value_for_unit_health_hero():
    d = Data()
    d._mem["hero"] = {1: {"id": 1, "starting_stats": {"max_health": {"value": 700}}}}
    assert value_for(d, _puzzle("unit_health"), {"entityId": 1}) == 700.0


def test_value_for_unit_height_prior():
    d = Data()
    d._mem["hero"] = {1: {"id": 1}}
    assert value_for(d, _puzzle("unit_height"), {"entityId": 1, "name": "Wraith"}) == 2.45
    assert value_for(d, _puzzle("unit_height"),
                     {"entityId": 999, "name": "Walker 1"}) == 12.6


def test_value_for_unknown_entity_is_none():
    d = Data()
    d._mem["hero"] = {}
    d._mem["misc"] = {}
    assert value_for(d, _puzzle("unit_health"), {"entityId": 999, "name": "X"}) is None


def test_value_for_bad_entity_raises_none():
    d = Data()
    # entityId missing entirely -> int(None) raises -> caught -> None
    assert value_for(d, _puzzle("unit_health"), {"id": "a"}) is None


def test_values_for_returns_only_known():
    d = Data()
    d._mem["ability"] = {100: {"abilityId": 100, "casts": {"mean": 5.0}}}
    puzzle = {
        "family": "ability_casts",
        "options": [{"id": "a", "entityId": 100}, {"id": "b", "entityId": 200}],
    }
    assert values_for(d, puzzle) == {"a": 5.0}
