"""Per-request timeout ASGI middleware.

Cancels any request that takes longer than `timeout_seconds` and returns a
503 with a JSON error body. Prevents long-running FortiManager calls from
blocking the server indefinitely and requiring a manual kill.
"""

from __future__ import annotations

import asyncio
import json


def request_timeout(app, timeout_seconds: float):
    """Wrap an ASGI app: cancel requests that exceed timeout_seconds.

    On timeout, returns HTTP 503 with a JSON body explaining the cause.
    The underlying task is cancelled so the server remains responsive.
    """

    async def wrapped(scope, receive, send):
        if scope["type"] != "http":
            await app(scope, receive, send)
            return

        responded = False

        async def send_timeout():
            nonlocal responded
            if not responded:
                responded = True
                body = json.dumps({
                    "error": "request_timeout",
                    "detail": f"Request exceeded {timeout_seconds:.0f}s — "
                              "FortiManager query took too long. Retry in a moment; "
                              "the catalog will be cached after the first successful call.",
                }).encode()
                try:
                    await send({
                        "type": "http.response.start",
                        "status": 503,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"retry-after", b"10"),
                        ],
                    })
                    await send({"type": "http.response.body", "body": body})
                except Exception:
                    pass

        async def run():
            nonlocal responded
            try:
                await app(scope, receive, send)
                responded = True
            except asyncio.CancelledError:
                await send_timeout()

        try:
            await asyncio.wait_for(run(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            await send_timeout()

    return wrapped
