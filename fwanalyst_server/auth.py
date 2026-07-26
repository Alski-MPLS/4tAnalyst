"""Static-bearer ASGI authentication for the unified server.

Interim control until Phase 4 engineer identity (AD/Entra): a single shared
token, checked on every HTTP request. Fail closed — an empty configured
token refuses to start rather than serving unauthenticated.
"""

from __future__ import annotations

import hmac
import json


class AuthConfigError(ValueError):
    """Raised when HTTP mode is requested without a usable token."""


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
