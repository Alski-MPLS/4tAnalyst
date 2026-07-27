"""Static-bearer ASGI authentication for the unified server.

Interim control until Phase 4 engineer identity (AD/Entra): a single shared
token, checked on every HTTP request. Fail closed — an empty configured
token refuses to start rather than serving unauthenticated.
"""

from __future__ import annotations

import hmac
import json

from fwanalyst_server.context import allowed_adoms_var


class AuthConfigError(ValueError):
    """Raised when HTTP mode is requested without a usable token."""


def _resolve_allowed_adoms(token: str, creds: dict) -> set[str] | None:
    """Return the allowed ADOM set for a token, or None if unrecognized.

    Precedence:
    1. token in server.tokens → that entry's adoms set (or {"*"} if adom_restriction: false)
    2. token == server.auth_token → {"*"} (legacy full-access, always)
    3. no match → None (caller should 401)

    Note: adom_restriction: false lifts the per-ADOM restriction for recognized
    tokens (they all get {"*"}), but unrecognized tokens still return None — auth
    is always enforced regardless of the restriction flag.
    """
    server_cfg = creds.get("server", {})
    restriction_enabled = server_cfg.get("adom_restriction", True)

    for entry in server_cfg.get("tokens", []):
        if hmac.compare_digest(
            token.encode(), entry.get("token", "").encode()
        ):
            if not restriction_enabled:
                return {"*"}
            adoms = entry.get("adoms", [])
            return {"*"} if "*" in adoms else set(adoms)

    legacy = server_cfg.get("auth_token", "")
    if legacy and hmac.compare_digest(token.encode(), legacy.encode()):
        return {"*"}

    return None


def require_bearer(app, token: str):
    """Wrap an ASGI app: reject requests lacking `Authorization: Bearer <token>`."""
    if not token or not token.strip():
        raise AuthConfigError(
            "Refusing to serve HTTP without an auth token. Set FW_ANALYST_TOKEN "
            "or server.auth_token in credentials.yaml."
        )
    expected = f"Bearer {token.strip()}".encode()

    async def wrapped(scope, receive, send):
        if scope["type"] != "http":
            await app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        supplied = headers.get(b"authorization", b"")
        if not hmac.compare_digest(supplied, expected):
            body = json.dumps({"error": "unauthorized"}).encode()
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", b"Bearer"),
                ],
            })
            await send({"type": "http.response.body", "body": body})
            return

        await app(scope, receive, send)

    return wrapped
