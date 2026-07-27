"""
Tests for fwanalyst_server: bearer-auth middleware and tool aggregation.
Middleware is driven directly as an ASGI callable — no server needed.
"""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from fwanalyst_server.auth import AuthConfigError, require_bearer


async def _echo_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


def _call(app, headers):
    sent = []

    async def send(msg):
        sent.append(msg)

    async def receive():
        return {"type": "http.request", "body": b""}

    scope = {"type": "http", "method": "POST", "path": "/mcp",
             "headers": headers}
    asyncio.run(app(scope, receive, send))
    return sent


def test_missing_token_401():
    app = require_bearer(_echo_app, "secret")
    sent = _call(app, [])
    assert sent[0]["status"] == 401


def test_wrong_token_401():
    app = require_bearer(_echo_app, "secret")
    sent = _call(app, [(b"authorization", b"Bearer wrong")])
    assert sent[0]["status"] == 401


def test_good_token_passes_through():
    app = require_bearer(_echo_app, "secret")
    sent = _call(app, [(b"authorization", b"Bearer secret")])
    assert sent[0]["status"] == 200
    assert sent[1]["body"] == b"ok"


def test_empty_configured_token_raises():
    with pytest.raises(AuthConfigError):
        require_bearer(_echo_app, "")
    with pytest.raises(AuthConfigError):
        require_bearer(_echo_app, "   ")


def test_allowed_hosts_env_var_parses_comma_separated(monkeypatch):
    from fwanalyst_server.__main__ import _allowed_hosts

    monkeypatch.setenv("FW_ANALYST_ALLOWED_HOSTS", "central-server:8000, 10.1.5.62:*")
    assert _allowed_hosts() == ["central-server:8000", "10.1.5.62:*"]


def test_allowed_hosts_defaults_empty_without_env_or_file(monkeypatch, tmp_path):
    from fwanalyst_server.__main__ import _allowed_hosts

    monkeypatch.delenv("FW_ANALYST_ALLOWED_HOSTS", raising=False)
    monkeypatch.setenv("CREDENTIALS_FILE", str(tmp_path / "missing.yaml"))
    assert _allowed_hosts() == []


def test_unified_server_aggregates_all_tools():
    from fwanalyst_server.server import mcp
    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    assert "plan_change" in names
    # one representative per package
    for expected in ("check_ip_traffic", "search_policies", "record_feedback",
                     "parse_spreadsheet_file", "get_naming_convention"):
        assert expected in names, f"missing {expected}"
    assert len(names) == 32  # 31 aggregated + plan_change


def test_context_module_exports_allowed_adoms_var():
    from fwanalyst_server.context import allowed_adoms_var
    from contextvars import ContextVar
    assert isinstance(allowed_adoms_var, ContextVar)


def test_resolve_adoms_restriction_disabled():
    from fwanalyst_server.auth import _resolve_allowed_adoms
    creds = {
        "server": {
            "adom_restriction": False,
            "auth_token": "admin-tok",
            "tokens": [
                {"token": "eng-tok", "label": "alice", "adoms": ["OT-ADOM"]},
            ],
        }
    }
    # Recognized tokens get {"*"} when restriction is off (ADOM filter lifted)
    assert _resolve_allowed_adoms("eng-tok", creds) == {"*"}
    assert _resolve_allowed_adoms("admin-tok", creds) == {"*"}
    # Unrecognized tokens still return None — auth is always enforced
    assert _resolve_allowed_adoms("garbage", creds) is None


def test_resolve_adoms_named_token_restricted():
    from fwanalyst_server.auth import _resolve_allowed_adoms
    creds = {
        "server": {
            "adom_restriction": True,
            "auth_token": "admin-tok",
            "tokens": [
                {"token": "eng-tok", "label": "alice", "adoms": ["OT-ADOM", "GAS-ADOM"]},
            ],
        }
    }
    result = _resolve_allowed_adoms("eng-tok", creds)
    assert result == {"OT-ADOM", "GAS-ADOM"}


def test_resolve_adoms_named_token_wildcard():
    from fwanalyst_server.auth import _resolve_allowed_adoms
    creds = {
        "server": {
            "adom_restriction": True,
            "auth_token": "admin-tok",
            "tokens": [
                {"token": "power-tok", "label": "bob", "adoms": ["*"]},
            ],
        }
    }
    assert _resolve_allowed_adoms("power-tok", creds) == {"*"}


def test_resolve_adoms_legacy_auth_token():
    from fwanalyst_server.auth import _resolve_allowed_adoms
    creds = {"server": {"adom_restriction": True, "auth_token": "legacy", "tokens": []}}
    assert _resolve_allowed_adoms("legacy", creds) == {"*"}


def test_resolve_adoms_unknown_token_returns_none():
    from fwanalyst_server.auth import _resolve_allowed_adoms
    creds = {"server": {"adom_restriction": True, "auth_token": "real", "tokens": []}}
    assert _resolve_allowed_adoms("garbage", creds) is None


def test_require_bearer_injects_allowed_adoms_into_contextvar():
    from fwanalyst_server.auth import require_bearer
    from fwanalyst_server.context import allowed_adoms_var

    captured = {}

    async def capturing_app(scope, receive, send):
        captured["adoms"] = allowed_adoms_var.get(None)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    creds = {
        "server": {
            "adom_restriction": True,
            "auth_token": "admin",
            "tokens": [
                {"token": "eng-tok", "label": "alice", "adoms": ["OT-ADOM"]},
            ],
        }
    }
    app = require_bearer(capturing_app, "eng-tok", creds)
    _call(app, [(b"authorization", b"Bearer eng-tok")])
    assert captured["adoms"] == {"OT-ADOM"}


def test_require_bearer_unknown_token_still_401():
    from fwanalyst_server.auth import require_bearer

    creds = {
        "server": {
            "adom_restriction": True,
            "auth_token": "admin",
            "tokens": [],
        }
    }
    app = require_bearer(_echo_app, "admin", creds)
    sent = _call(app, [(b"authorization", b"Bearer garbage")])
    assert sent[0]["status"] == 401


def test_require_bearer_named_token_differs_from_primary():
    """A named token from server.tokens is accepted even when it differs from the primary admin token."""
    from fwanalyst_server.auth import require_bearer
    from fwanalyst_server.context import allowed_adoms_var

    captured = {}

    async def capturing_app(scope, receive, send):
        captured["adoms"] = allowed_adoms_var.get(None)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    creds = {
        "server": {
            "adom_restriction": True,
            "auth_token": "admin-token",          # primary token
            "tokens": [
                {"token": "eng-tok", "label": "alice", "adoms": ["OT-ADOM"]},
            ],
        }
    }
    # require_bearer is initialized with the admin token, but eng-tok is submitted
    app = require_bearer(capturing_app, "admin-token", creds)
    sent = _call(app, [(b"authorization", b"Bearer eng-tok")])
    assert sent[0]["status"] == 200
    assert captured["adoms"] == {"OT-ADOM"}
