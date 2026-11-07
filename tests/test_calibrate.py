"""Tests for rushbot.calibrate — per-type grading of a solved answer."""
from __future__ import annotations

from rushbot.calibrate import grade


def _pair_puzzle():
    return {"type": "pair", "family": "unit_health",
            "prompt": {"direction": "higher"},
            "options": [{"id": "a", "entityId": 1}, {"id": "b", "entityId": 2}]}


def test_grade_pair(data, kn):
    assert grade(data, kn, _pair_puzzle(), {"answer": {"order": ["b"]}}) is True
    assert grade(data, kn, _pair_puzzle(), {"answer": {"order": ["a"]}}) is False


def test_grade_empty_reveal_is_false(data, kn):
    assert grade(data, kn, _pair_puzzle(), {}) is False
    assert grade(data, kn, _pair_puzzle(), None) is False


def test_grade_overunder(data, kn):
    puzzle = {"type": "overunder", "family": "unit_health",
              "overunder": {"line": 800},
              "options": [{"id": "a", "entityId": 1}]}
    assert grade(data, kn, puzzle, {"answer": {"choice": "under"}}) is True
    assert grade(data, kn, puzzle, {"answer": {"choice": "over"}}) is False


def test_grade_estimate_default_band(data, kn):
    puzzle = {"type": "estimate", "family": "unit_health",
              "estimate": {"min": 0, "max": 1000, "step": 100},
              "options": [{"id": "a", "entityId": 1}]}
    assert grade(data, kn, puzzle, {"answer": {"value": 700}}) is True
    # 800 is within the 20% band of the solved value (|700-800| <= 0.2*800)
    assert grade(data, kn, puzzle, {"answer": {"value": 800}}) is True
    assert grade(data, kn, puzzle, {"answer": {"value": 5000}}) is False


def test_grade_scale_relative_tolerance(data, kn):
    puzzle = {"type": "scale", "family": "unit_health",
              "scale": {"referenceId": "ref", "targetId": "tgt",
                        "minRatio": 0.1, "maxRatio": 10.0,
                        "tolerance": {"kind": "relative", "value": 0.05}},
              "options": [{"id": "ref", "entityId": 1}, {"id": "tgt", "entityId": 2}]}
    # solved ratio is ~1.2857
    assert grade(data, kn, puzzle, {"answer": {"value": 1.3}}) is True
    assert grade(data, kn, puzzle, {"answer": {"value": 5.0}}) is False


def test_grade_shopdash_uses_targets(data, kn):
    puzzle = {"type": "shopdash", "shop": {"targets": [10, 20]}}
    assert grade(data, kn, puzzle, {"answer": {}}) is True
