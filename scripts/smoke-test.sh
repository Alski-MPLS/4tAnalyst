#!/usr/bin/env bash
# Quick smoke test for the unified FW-Analyst server: unauthenticated requests
# must get 401; the configured token must get through (any non-401).
# Usage: ./scripts/smoke-test.sh   (FW_ANALYST_TOKEN defaults to dev-local-token)
set -euo pipefail

host="${SMOKE_HOST:-localhost}"
port="${SMOKE_PORT:-8000}"
token="${FW_ANALYST_TOKEN:-dev-local-token}"
url="http://${host}:${port}/mcp"
body='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}'
failed=0

echo -n "Checking ${url} without auth... "
code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 -X POST \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d "$body" "$url" 2>/dev/null || true)
if [ "$code" = "401" ]; then
  echo "OK (HTTP 401 — auth enforced)"
else
  echo "FAIL (HTTP $code — expected 401)"
  failed=1
fi

echo -n "Checking ${url} with token... "
code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 -X POST \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -H "Authorization: Bearer ${token}" -d "$body" "$url" 2>/dev/null || true)
if [ "$code" != "401" ] && [ -n "$code" ] && [ "$code" != "000" ]; then
  echo "OK (HTTP $code)"
else
  echo "FAIL (HTTP $code — token rejected or server unreachable)"
  failed=1
fi

if [ "$failed" -ne 0 ]; then
  echo "One or more smoke checks failed" >&2
  exit 2
fi

echo "All smoke checks passed"
