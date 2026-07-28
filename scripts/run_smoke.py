#!/usr/bin/env python3
"""Pure-Python smoke test for the unified 4tAnalyst server.

Checks that http://localhost:8000/mcp
  1. rejects unauthenticated requests with 401, and
  2. accepts the configured bearer token (any non-401 response).

Token comes from FW_ANALYST_TOKEN (default: dev-local-token, matching
docker-compose.yml). No external packages required.
Usage: python3 scripts/run_smoke.py
"""
import http.client
import json
import os
import socket
import sys

HOST = os.getenv("SMOKE_HOST", "localhost")
PORT = int(os.getenv("SMOKE_PORT", "8000"))
TOKEN = os.getenv("FW_ANALYST_TOKEN", "dev-local-token")
PATH = "/mcp"

_INIT_BODY = json.dumps({
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "smoke", "version": "0"},
    },
}).encode()


def _post(headers: dict) -> int:
    conn = http.client.HTTPConnection(HOST, PORT, timeout=10)
    try:
        base = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        base.update(headers)
        conn.request("POST", PATH, body=_INIT_BODY, headers=base)
        return conn.getresponse().status
    finally:
        conn.close()


def main() -> None:
    ok = True

    try:
        status = _post({})
        if status == 401:
            print(f"http://{HOST}:{PORT}{PATH} unauthenticated -> 401 OK")
        else:
            print(f"http://{HOST}:{PORT}{PATH} unauthenticated -> {status} "
                  "FAILED (expected 401 — auth is not enforced!)")
            ok = False
    except (ConnectionRefusedError, socket.timeout, OSError) as e:
        print(f"http://{HOST}:{PORT}{PATH} ERROR: {e}")
        sys.exit(2)

    status = _post({"Authorization": f"Bearer {TOKEN}"})
    if status != 401:
        print(f"http://{HOST}:{PORT}{PATH} with token -> {status} OK")
    else:
        print(f"http://{HOST}:{PORT}{PATH} with token -> 401 FAILED "
              "(token rejected — check FW_ANALYST_TOKEN)")
        ok = False

    if not ok:
        sys.exit(2)
    print("All checks passed")


if __name__ == "__main__":
    main()
