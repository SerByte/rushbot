"""HTTP client for statlocker's Statlockle Rush API.

The site is behind Cloudflare: a cold session gets 401 on API calls, so every
client warms up on the HTML page first. Runs are server-side state keyed by
runId, so a client instance is cheap and stateless beyond cookies.
"""
from __future__ import annotations

import http.cookiejar
import json
import time
import urllib.error
import urllib.request

BASE = "https://statlocker.gg"
API = BASE + "/api/statlockle"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

COUNTDOWN_PAD_MS = 60  # answer this long after the countdown expires


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"{status}: {message}")
        self.status = status
        self.message = message


class Client:
    def __init__(self, cookie_header: str | None = None, timeout: float = 30.0):
        self.timeout = timeout
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar))
        self.extra_cookie = cookie_header
        self._warm = False
        self.requests = 0
        if cookie_header:
            for pair in cookie_header.split(";"):
                if "=" not in pair:
                    continue
                name, value = pair.split("=", 1)
                self.jar.set_cookie(http.cookiejar.Cookie(
                    version=0, name=name.strip(), value=value.strip(), port=None,
                    port_specified=False, domain="statlocker.gg", domain_specified=True,
                    domain_initial_dot=False, path="/", path_specified=True,
                    secure=True, expires=None, discard=False, comment=None,
                    comment_url=None, rest={}, rfc2109=False))

    # ---------------------------------------------------------------- plumbing
    def _headers(self, referer: str | None = None) -> dict:
        h = {
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": BASE,
            "Referer": referer or (BASE + "/statlockle/rush"),
        }
        return h

    def warm(self) -> None:
        if self._warm:
            return
        req = urllib.request.Request(BASE + "/statlockle/rush",
                                     headers={"User-Agent": UA})
        try:
            with self.opener.open(req, timeout=self.timeout) as r:
                r.read(2048)
        except Exception:
            pass
        self._warm = True

    def request(self, path: str, body=None, method: str | None = None,
                tries: int = 4, allow_404: bool = False):
        if path.startswith("/api/"):
            url = BASE + path
        else:
            url = API + path
        data = None if body is None else json.dumps(body).encode()
        delay = 1.0
        last = None
        for attempt in range(tries):
            self.warm()
            req = urllib.request.Request(
                url, data=data, method=method or ("POST" if body is not None else "GET"),
                headers=self._headers())
            if data is not None:
                req.add_header("Content-Type", "application/json")
            self.requests += 1
            try:
                with self.opener.open(req, timeout=self.timeout) as r:
                    raw = r.read().decode()
                    return json.loads(raw) if raw else None
            except urllib.error.HTTPError as e:
                msg = e.read().decode()[:400]
                last = ApiError(e.code, msg)
                if e.code == 404 and allow_404:
                    return None
                if e.code in (401, 403, 429, 500, 502, 503, 504) and attempt + 1 < tries:
                    self._warm = False
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise last
            except Exception as e:  # connection reset, timeout
                last = ApiError(0, str(e))
                if attempt + 1 < tries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise last
        raise last

    # ------------------------------------------------------------------- game
    def start(self, nightmare: bool = False) -> dict:
        q = "?nightmare=true" if nightmare else ""
        return self.request("/rush/start" + q, {})

    def go(self, run_id: str) -> int:
        r = self.request(f"/rush/{run_id}/go", {})
        return int(r.get("goAt", 0))

    def answer(self, run_id: str, body: dict) -> dict:
        return self.request(f"/rush/{run_id}/answer", body)

    def finish(self, run_id: str, answers: list) -> dict:
        return self.request(f"/rush/{run_id}/finish", {"answers": answers})

    def leaderboard(self, page: int = 0, size: int = 10) -> dict:
        return self.request(f"/leaderboard?page={page}&size={size}")

    def me(self):
        return self.request("/leaderboard/friends", allow_404=True)


def wait_for_go(go_at_ms: int, issued_at: float, countdown_ms: int = 3000,
                extra_pad_ms: int = 0) -> None:
    """Sleep until the server-side countdown has expired.

    The server's goAt drifts from the local clock, so the request time is used as
    the anchor and goAt only as a lower bound.
    """
    local_deadline = (issued_at * 1000.0) + countdown_ms + COUNTDOWN_PAD_MS + extra_pad_ms
    server_deadline = go_at_ms + countdown_ms + COUNTDOWN_PAD_MS + extra_pad_ms
    deadline = max(local_deadline, server_deadline)
    wait_ms = deadline - time.time() * 1000.0
    if wait_ms > 0:
        time.sleep(wait_ms / 1000.0)


def scoring(puzzle: dict, speed_mult: float = 4.0) -> int:
    """Points a correct answer is worth, mirroring the client's formula."""
    if puzzle.get("type") == "iconcost":
        return 0
    return round(puzzle.get("basePoints", 100) * puzzle.get("difficulty", 1.0)
                 * 0.5 * speed_mult)
