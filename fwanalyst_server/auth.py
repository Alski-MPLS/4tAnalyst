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


def require_bearer(app, token: str, creds: dict | None = None):
    """Wrap an ASGI app: reject requests lacking `Authorization: Bearer <token>`.

    When creds is provided, also resolves the token's allowed ADOM set and
    injects it into allowed_adoms_var for the duration of each request.
    When creds is omitted (or empty), falls back to full access for the
    token — preserving backward-compatibility with existing call sites and tests.
    """
    if not token or not token.strip():
        raise AuthConfigError(
            "Refusing to serve HTTP without an auth token. Set FW_ANALYST_TOKEN "
            "or server.auth_token in credentials.yaml."
        )
    _creds = creds or {}

    async def wrapped(scope, receive, send):
        if scope["type"] != "http":
            await app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        supplied_bytes = headers.get(b"authorization", b"")
        supplied_str = supplied_bytes.decode("latin-1")

        # Strip "Bearer " prefix for resolution
        supplied_token = supplied_str.removeprefix("Bearer ").strip()

        adom_set = _resolve_allowed_adoms(supplied_token, _creds) if supplied_token else None

        # Constant-time check against the primary token
        expected = f"Bearer {token.strip()}".encode()
        if not hmac.compare_digest(supplied_bytes, expected):
            # Also accept any token in the named tokens list (already resolved above)
            if adom_set is None:
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

        # Inject ADOM set (full access if no creds provided or legacy token)
        resolved = adom_set if adom_set is not None else {"*"}
        token_ctx = allowed_adoms_var.set(resolved)
        try:
            await app(scope, receive, send)
        finally:
            allowed_adoms_var.reset(token_ctx)

    return wrapped
