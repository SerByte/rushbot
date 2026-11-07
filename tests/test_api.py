"""Tests for rushbot.api — scoring, error type, and cookie parsing (offline)."""
from __future__ import annotations

from rushbot.api import ApiError, Client, scoring


def test_scoring_formula():
    assert scoring({"type": "pair", "basePoints": 100, "difficulty": 2.0}) == 400
    assert scoring({"type": "pair", "basePoints": 100, "difficulty": 1.5},
                   speed_mult=2.0) == 150


def test_scoring_iconcost_zero():
    # iconcost answers carry no points on their own
    assert scoring({"type": "iconcost", "basePoints": 100, "difficulty": 3.0}) == 0


def test_scoring_defaults():
    # basePoints defaults to 100, difficulty to 1.0, speed_mult to 4.0
    assert scoring({"type": "pair"}) == 200


def test_api_error_attrs():
    e = ApiError(403, "forbidden")
    assert e.status == 403
    assert e.message == "forbidden"
    assert "403" in str(e)


def test_client_parses_cookie_header():
    c = Client(cookie_header="session=abc123; theme=dark")
    names = {cookie.name for cookie in c.jar}
    assert names == {"session", "theme"}
    assert c.extra_cookie == "session=abc123; theme=dark"


def test_client_no_cookie():
    c = Client()
    assert len(list(c.jar)) == 0
    assert c.extra_cookie is None
