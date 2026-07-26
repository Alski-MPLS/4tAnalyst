# Installation

## Overview

4tAnalyst has two installation targets:
1. **Central MCP server** — a Linux VM on your internal network that runs the MCP servers and holds all firewall API credentials
2. **Engineer workstations** — each engineer's laptop needs only Claude Code pointed at the central server

---

## Central MCP server

### Hardware requirements

| Use case | vCPU | RAM | Disk |
|---|---|---|---|
| Development / pilot (1–2 engineers) | 4 | 8 GB | 50 GB |
| Team (5–10 engineers) | 8 | 16 GB | 100 GB |

### Network requirements

The server needs outbound access to:
- FortiManager management IP(s) on port 443
- 4THealth server IP on port 443
- NetBrain server IP on port 443 (when the integration is available)

Engineer laptops need inbound access to the MCP server on port 8000 only (the unified fwanalyst_server; put TLS in front of it — see [Configuration](configuration.md)).

No internet access is required.

### 1. Install system dependencies

```bash
# RHEL 8/9 (production target)
sudo dnf install -y python3.11 git curl

# Ubuntu 22.04
sudo apt update && sudo apt install -y python3.11 python3.11-venv git curl

# Install uv (Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc
```

### 2. Clone the repository

```bash
git clone <your-internal-repo-url> /opt/fw-analyst
cd /opt/fw-analyst
```

### 3. Create a virtual environment

```bash
uv venv .venv
source .venv/bin/activate
```

### 4. Install all MCP server packages

```bash
uv pip install -e standards_mcp/ -e fortimanager_mcp/ -e feedback_mcp/ \
    -e intake_mcp/ -e zone_mcp/ -e planner/ -e fwanalyst_server/
```

### 5. Configure credentials

```bash
cp credentials.yaml.example credentials.yaml
# Edit credentials.yaml — see Configuration for field descriptions
nano credentials.yaml
```

### 6. Start the servers

For initial testing, start each server manually in separate terminals. Host/port
are set via `FASTMCP_HOST`/`FASTMCP_PORT` env vars, not CLI flags — the
installed `mcp` version's `FastMCP.run()` only accepts `transport`:

```bash
MCP_TRANSPORT=http FASTMCP_HOST=0.0.0.0 FASTMCP_PORT=8000 \
    FW_ANALYST_TOKEN=<token> uv run python -m fwanalyst_server
```

For production, use Docker Compose — see `docker-compose.yml` in the repository root.

### 7. Smoke test

From the server, verify auth is enforced using either the pure-Python tester or the shell script:

```bash
python3 scripts/run_smoke.py   # asserts 401 without token, non-401 with
# or
./scripts/smoke-test.sh
```

Both check port 8000: an unauthenticated request must return `401`, a request with the token must not.

---

## Docker Compose

`docker-compose.yml` in the repo root runs the unified fwanalyst server for local dev (mounts the repo so edits are picked up live). `docker-compose.ci.yml` is the CI variant — built image, no mounts. `docker-compose.example.yml` is a conservative starting point if you're adapting this for a different deployment target.

```bash
docker compose up
```

Developer helper scripts (local dev)

- scripts/start-all.sh — start the unified server in the background (activates .venv if present)
  - Usage: ./scripts/start-all.sh
- scripts/smoke-test.sh — quick curl-based auth check against port 8000
  - Usage: ./scripts/smoke-test.sh
- scripts/run_smoke.py — pure-Python smoke tester (no extra packages)
  - Usage: python3 scripts/run_smoke.py

Systemd template (VM deployment, e.g. RHEL)

- A systemd unit template for the unified server is provided at `systemd/fw-analyst.service` (one unit — `MCP_TRANSPORT=http` plus `FW_ANALYST_TOKEN` via EnvironmentFile). Adjust ExecStart and paths for your host environment.

If you prefer to maintain your own start script, the commands below show what scripts/start-all.sh runs:

```bash
MCP_TRANSPORT=http FASTMCP_HOST=0.0.0.0 FASTMCP_PORT=8000 \
    FW_ANALYST_TOKEN=<token> uv run python -m fwanalyst_server &

wait
```

---

## Engineer workstations

Engineers need only Claude Code — no Python, no API credentials, no local server.

### 1. Install Claude Code

Download from [claude.ai/code](https://claude.ai/code). Available for macOS, Windows (native and WSL2), and Linux.

### 2. Clone the repo (for skills and config)

```bash
git clone <your-internal-repo-url> ~/fw-analyst
```

Or just copy the `.claude/` folder from the repo root to any working directory where you'll run Claude Code.

### 3. Configure MCP server connections

See [Configuration — Engineer workstations](configuration.md#engineer-workstations) for how to point Claude Code at the central server.

### 4. Verify the connection

Open the `fw-analyst` directory in Claude Code and type:

```
/check-policy 10.1.0.1 10.2.0.1
```

If the zone policy server is reachable you'll get a verdict back. If you get an error, see [Troubleshooting](troubleshooting.md).
