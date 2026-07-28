#!/bin/bash
# Start the unified 4tAnalyst MCP server for local development.
# Usage: ./scripts/start-all.sh
# Set FW_ANALYST_TOKEN to override the dev token.
set -euo pipefail
# If a venv exists, activate it
if [ -f ".venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi
cd "$(dirname "${BASH_SOURCE[0]}")/.."

export MCP_TRANSPORT=http
export FASTMCP_HOST=0.0.0.0
export FASTMCP_PORT=8000
export FW_ANALYST_TOKEN="${FW_ANALYST_TOKEN:-dev-local-token}"

echo "Starting fwanalyst_server on port ${FASTMCP_PORT} (streamable-HTTP + bearer auth)"
exec uv run python -m fwanalyst_server
