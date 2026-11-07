"""Shared fixtures for the rushbot test suite.

Tests are fully offline: ``Data`` is seeded through its ``_mem`` cache and
``Knowledge`` is pointed at a temp file, so no network or browser access is
ever required.
"""
from __future__ import annotations

import pytest

from rushbot.data import Data
from rushbot.knowledge import Knowledge


def hero(eid: int, max_health: float, name: str | None = None) -> dict:
    return {
        "id": eid,
        "name": name or f"Hero{eid}",
        "starting_stats": {"max_health": {"value": max_health}},
    }


def make_data() -> Data:
    d = Data()
    d._mem["hero"] = {
        1: hero(1, 700, "Wraith"),
        2: hero(2, 900, "Seven"),
        3: hero(3, 800, "Infernus"),
    }
    return d


@pytest.fixture
def data() -> Data:
    return make_data()


@pytest.fixture
def kn(tmp_path) -> Knowledge:
    return Knowledge(path=str(tmp_path / "knowledge.jsonl"))
