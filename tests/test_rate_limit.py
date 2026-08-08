"""
Tests for fwanalyst_server: per-session rate-limiting middleware.
Middleware is driven directly as an ASGI callable — no server needed.
"""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from fwanalyst_server.rate_limit import RateLimitConfigError, rate_limit


async def _echo_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


def _call(app, headers=()):
    sent = []

    async def send(msg):
        sent.append(msg)

    async def receive():
        return {"type": "http.request", "body": b""}

    scope = {"type": "http", "method": "POST", "path": "/mcp",
             "headers": list(headers)}
    asyncio.run(app(scope, receive, send))
    return sent


def test_requests_under_budget_pass_through():
    app = rate_limit(_echo_app, max_requests=2, window_seconds=60)
    for _ in range(2):
        sent = _call(app)
        assert sent[0]["status"] == 200


def test_requests_over_budget_get_429():
    app = rate_limit(_echo_app, max_requests=1, window_seconds=60)
    _call(app)
    sent = _call(app)
    assert sent[0]["status"] == 429
    retry_after = dict(sent[0]["headers"])[b"retry-after"]
    assert retry_after == b"60"


def test_separate_sessions_have_separate_budgets():
    app = rate_limit(_echo_app, max_requests=1, window_seconds=60)
    sent_a = _call(app, [(b"mcp-session-id", b"session-a")])
    sent_b = _call(app, [(b"mcp-session-id", b"session-b")])
    assert sent_a[0]["status"] == 200
    assert sent_b[0]["status"] == 200
    # session-a is now over budget, session-b still has room used up too
    sent_a_again = _call(app, [(b"mcp-session-id", b"session-a")])
    assert sent_a_again[0]["status"] == 429


def test_window_expiry_resets_budget():
    app = rate_limit(_echo_app, max_requests=1, window_seconds=0.05)
    _call(app)
    blocked = _call(app)
    assert blocked[0]["status"] == 429
    import time
    time.sleep(0.06)
    sent = _call(app)
    assert sent[0]["status"] == 200


def test_non_http_scope_passes_through_unmetered():
    app = rate_limit(_echo_app, max_requests=1, window_seconds=60)

    async def _run():
        sent = []

        async def send(msg):
            sent.append(msg)

        async def receive():
            return {"type": "lifespan.startup"}

        await app({"type": "lifespan"}, receive, send)
        return sent

    # lifespan scope has no http status to assert on; just confirm no crash
    # and that it doesn't consume the http rate-limit budget
    asyncio.run(_run())
    sent = _call(app)
    assert sent[0]["status"] == 200


def _windows(app):
    """Reach into the middleware closure for the live session-bucket dict."""
    return app.__closure__[
        app.__code__.co_freevars.index("windows")
    ].cell_contents


def test_empty_bucket_is_removed_after_window_expires():
    import time

    app = rate_limit(_echo_app, max_requests=5, window_seconds=0.05)
    _call(app, [(b"mcp-session-id", b"session-a")])
    windows = _windows(app)
    assert b"session-a" in windows

    time.sleep(0.06)
    # A request from a *different* session must not resurrect session-a, and
    # session-a's own next request must find its stale bucket pruned, not empty.
    _call(app, [(b"mcp-session-id", b"session-b")])
    assert b"session-a" in windows  # untouched until session-a is seen again

    _call(app, [(b"mcp-session-id", b"session-a")])
    assert len(windows[b"session-a"]) == 1  # stale entry dropped, new one added
    assert all(bucket for bucket in windows.values())  # no empty deques kept


def test_bucket_count_is_capped_and_evicts_stalest(monkeypatch):
    monkeypatch.setattr("fwanalyst_server.rate_limit._MAX_TRACKED_SESSIONS", 3)
    app = rate_limit(_echo_app, max_requests=5, window_seconds=60)
    for name in (b"s1", b"s2", b"s3"):
        _call(app, [(b"mcp-session-id", name)])
    windows = _windows(app)
    assert len(windows) == 3

    _call(app, [(b"mcp-session-id", b"s4")])
    assert len(windows) == 3
    assert b"s1" not in windows          # stalest newest-timestamp evicted
    assert set(windows) == {b"s2", b"s3", b"s4"}


def test_eviction_never_breaks_an_active_sessions_accounting(monkeypatch):
    monkeypatch.setattr("fwanalyst_server.rate_limit._MAX_TRACKED_SESSIONS", 2)
    app = rate_limit(_echo_app, max_requests=4, window_seconds=60)

    # An active session keeps touching the limiter while other sessions churn.
    _call(app, [(b"mcp-session-id", b"active")])
    _call(app, [(b"mcp-session-id", b"idle")])
    for name in (b"churn-1", b"churn-2", b"churn-3"):
        _call(app, [(b"mcp-session-id", b"active")])  # keeps `active` freshest
        _call(app, [(b"mcp-session-id", name)])

    windows = _windows(app)
    assert b"active" in windows, "the freshest session must never be evicted"
    assert len(windows) <= 2
    # Its 4 requests were all counted despite the churn: the 5th is refused.
    assert len(windows[b"active"]) == 4
    assert _call(app, [(b"mcp-session-id", b"active")])[0]["status"] == 429


def test_invalid_config_raises():
    with pytest.raises(RateLimitConfigError):
        rate_limit(_echo_app, max_requests=0, window_seconds=60)
    with pytest.raises(RateLimitConfigError):
        rate_limit(_echo_app, max_requests=10, window_seconds=0)
