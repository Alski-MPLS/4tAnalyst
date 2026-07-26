# Contributing

## Who maintains what

| Component | How to update | Who owns it |
|---|---|---|
| Zone definitions and subnets | 4THealth admin UI | Network / OT team |
| Zone policy rules | 4THealth admin UI | Security team |
| `standards_mcp/naming.yaml` | Edit the file, commit, restart standards_mcp | FW engineering team |
| `standards_mcp/review_requirements.yaml` | Edit the file, commit, restart standards_mcp | FW engineering team |
| MCP server code | Pull request, see below | 4tAnalyst maintainers |
| `planner/` (deterministic engine) | Pull request — changes here alter what engineers implement; tests required | 4tAnalyst maintainers |
| `.claude/skills/<name>/SKILL.md` | Pull request or direct edit | FW engineering team |

## Updating naming conventions or review requirements

Edit `standards_mcp/naming.yaml` or `standards_mcp/review_requirements.yaml` directly. Changes take effect on the next MCP server restart — no code changes needed.

After editing:
1. Commit the change to the repo
2. Pull the change on the central server (`git pull`)
3. Restart the `standards_mcp` server process

## Adding a new MCP server

Each MCP server is an independent Python package under its own directory. To add a new one:

1. Create a new directory: `<name>_mcp/`
2. Add `__init__.py`, `server.py`, `pyproject.toml` following the pattern in `fortimanager_mcp/`
3. If the server needs credentials, add a section to `credentials.yaml.example` and document it in `docs/configuration.md`
4. Install it: `uv pip install -e <name>_mcp/`
5. Add it to the server start script and eventually `docker-compose.yml`
6. Add a smoke test entry to `docs/installation.md`

## Pull request guidelines

- Keep pull requests focused — one logical change per PR
- MCP server changes should include a manual smoke test result in the PR description
- Do not commit `credentials.yaml`, `policy_db.json`, or any file containing internal IPs, hostnames, or API keys
- Update `docs/` if the change affects installation, configuration, or usage

## Running servers locally for development

```bash
# per-package stdio mode — easiest for debugging; server logs appear in the terminal
uv run python -m zone_mcp.server

# unified server, http mode — matches production behaviour
MCP_TRANSPORT=http FASTMCP_PORT=8000 FW_ANALYST_TOKEN=<token> \
    uv run python -m fwanalyst_server

# deterministic planner, no server needed at all
uv run python -m planner --src 10.1.2.3 --dst 10.9.8.7 --service tcp/8443 \
    --firewall FW1:root --json-only
```

Each per-package MCP server still runs independently over stdio for development. Production serves a single aggregated endpoint (fwanalyst_server, port 8000) — when you add a tool, register it in fwanalyst_server/server.py and bump the expected count in tests/test_fwanalyst_auth.py.

Local helper scripts are available in `scripts/`:

- `scripts/start-all.sh` — start the unified server in the background (activates .venv if present)
- `scripts/smoke-test.sh` — quick curl-based auth check against port 8000
- `scripts/run_smoke.py` — pure-Python smoke tester (no extra packages)

See `docs/installation.md` for usage and the `docker-compose.example.yml` and `systemd/` templates for example deployment approaches.
