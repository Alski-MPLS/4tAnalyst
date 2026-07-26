# Copilot instructions for 4tAnalyst

Purpose

Short, actionable repository-specific guidance for Copilot/assistant sessions.

1) Build, test, and lint (repository-specific)

- Install packages (editable) — run from repository root:
  - uv pip install -e standards_mcp/
  - uv pip install -e fortimanager_mcp/
  - uv pip install -e feedback_mcp/
  - uv pip install -e intake_mcp/
  - uv pip install -e zone_mcp/

- Run a single MCP server (development / debug, stdio):
  - uv run python -m standards_mcp.server
  - uv run python -m fortimanager_mcp.server

- Run a single MCP server (production-like SSE):
  - uv run mcp run standards_mcp/server.py --transport sse --port 8000

- Rebuild policy DB (one-shot):
  - uv run python standards_mcp/build_policy_db.py
  - Do not edit standards_mcp/policy_db.json by hand; regenerate from TUFIN CSVs.

- Smoke tests (quick checks):
  - curl -s http://localhost:8000/sse | head -2   # standards_mcp
  - curl -s http://localhost:8001/sse | head -2   # fortimanager_mcp

- Tests & lint: No test framework or linter is configured in this repo as of now. Use manual smoke tests above. If adding tests, update this file.

2) High-level architecture (big picture)

- The project is a set of independent Python MCP servers (packages suffixed with `_mcp`) that expose read-only tools via the Model Context Protocol to Claude Code running on engineer workstations.
- Key packages:
  - standards_mcp (port 8000) — zone matrix, naming.yaml, review_requirements.yaml, and policy evaluation (policy_engine.py).
  - fortimanager_mcp (port 8001) — read-only FortiManager queries (devices, policies, search).
  - feedback_mcp (port 8002) — decision/audit store (SQLite in Phase 1).
  - intake_mcp (port 8003) — spreadsheet (.xlsx) parser and manual entry normalization.
  - zone_mcp (port 8004) — IP→zone resolution and policy queries to 4THealth (Phase 2 mapper).
  - netbrain_mcp — planned for automated path discovery (future).
- Dataflow: intake → zone_mcp (resolve zones) + fortimanager_mcp (search device rules) → standards_mcp (naming/logging/review rules) → feedback_mcp (store decisions).

3) Key repository conventions and patterns

- Each MCP server is an independent Python package with its own pyproject.toml and server.py. Follow the fortimanager_mcp pattern when adding a new MCP package.
- Configuration vs code:
  - standards_mcp/naming.yaml and standards_mcp/review_requirements.yaml are team-maintained config files and are loaded at server startup. Editing them requires only a restart of the standards_mcp server.
  - Do not hand-edit policy_db.json — regenerate it with build_policy_db.py when TUFIN CSVs change.
- Policy engine is stateless and pure (policy_engine.py): callables accept DB dicts; avoid global I/O in evaluation logic.
- Security-sensitive files:
  - Do not commit credentials.yaml or any file containing API keys, internal IPs, or hostnames. credentials.yaml.example exists as a template.
- Developer run modes:
  - stdio mode (uv run python -m <pkg>.server) for quick debugging; SSE mode (uv run mcp run ...) for production-like behaviour.
- Smoke-testing endpoints:
  - Each MCP exposes an SSE endpoint (/<sse>) that can be sanity-checked with curl as above.

4) AI assistant / existing assistant artifacts to reuse

- CLAUDE.md and .claude/skills/ contain explicit directions and slash-command examples for Claude Code. Prioritize them when producing assistant prompts or building MCP interactions.
- This repo uses manual smoke-testing; search for documentation in docs/ and the .claude directory before suggesting automated test approaches.

5) When changing repository structure or adding servers

- Follow CONTRIBUTING.md: add `<name>_mcp/` with __init__.py, server.py and pyproject.toml; document creds in credentials.yaml.example; add smoke test notes to docs/installation.md; and include a smoke test result in the PR.

6) Useful files to inspect first in a Copilot session

- README.md, CLAUDE.md, CONTRIBUTING.md, docs/installation.md, docs/architecture.md, standards_mcp/server.py, standards_mcp/policy_engine.py, standards_mcp/naming.yaml, standards_mcp/review_requirements.yaml, .claude/skills/*.md

---

If you'd like, configure MCP server helpers (e.g., a Playwright or other test MCP) for this project now. Otherwise, the file is ready.
