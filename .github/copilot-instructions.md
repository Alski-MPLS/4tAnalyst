# Copilot instructions for 4tAnalyst

Purpose

Short, actionable repository-specific guidance for Copilot/assistant sessions.

1) Build, test, and lint (repository-specific)

- Install packages (editable) — run from repository root:
  - uv pip install -e mcp_common/ -e standards_mcp/ -e fortimanager_mcp/ -e feedback_mcp/ \
      -e intake_mcp/ -e zone_mcp/ -e fwanalyst_server/

- The deterministic planner is exercised through the `plan_change` MCP tool
  in `fwanalyst_server` (see below) — `fwanalyst_server/server.py` registers
  the FortiManager/zone-policy client factories fgplanner needs from
  `credentials.yaml`. fgplanner also ships its own standalone CLI
  (`python -m fgplanner`), but it deliberately ships no default clients and
  reads no credentials file (see `fgplanner/clients.py` in the
  fortigate-change-planner repo) — running it directly from within 4tAnalyst
  without registering your own client factories first will fail with a
  "no FortiManager client configured" error.

- Run the unified server (development, stdio):
  - uv run python -m fwanalyst_server

- Run the unified server (production-like, streamable-HTTP + bearer auth, one port):
  - MCP_TRANSPORT=http FASTMCP_HOST=0.0.0.0 FASTMCP_PORT=8000 \
      FW_ANALYST_TOKEN=<token> uv run python -m fwanalyst_server
  - Refuses to start in HTTP mode without a token (`FW_ANALYST_TOKEN` env or
    `credentials.yaml` `server.auth_token`; env wins).

- Individual per-package servers still run over stdio for debugging:
  - uv run python -m zone_mcp.server   # etc.

- Docker:
  - docker compose up                              # local dev, mounts repo for live edits
  - docker compose -f docker-compose.ci.yml up      # CI image, no mounts

- Rebuild policy DB (one-shot):
  - uv run python standards_mcp/build_policy_db.py
  - Do not edit standards_mcp/policy_db.json by hand; regenerate from TUFIN CSVs.

- Tests & lint:
  - pytest -q tests/   # full suite, no live systems needed
  - uv run python scripts/run_smoke.py   # smoke check; server must be running,
    asserts 401 without a token, 200 with one.

2) High-level architecture (big picture)

- Core design rule: the LLM orchestrates, code computes. All correctness-critical
  analysis (rule coverage, object reuse, insertion point, CLI generation) lives in
  the deterministic planning core, published separately as
  [fortigate-change-planner](https://github.com/Alski-MPLS/fortigate-change-planner)
  (importable module `fgplanner`) and installed as a dependency of `fwanalyst_server`.
- In production, **one process** — `fwanalyst_server` (port 8000, streamable-HTTP,
  static-bearer auth, fail-closed) — aggregates every tool from every package below,
  plus `plan_change`. The per-domain packages remain individually runnable over
  stdio for development, but they are not deployed as separate services.
- Key packages:
  - fortigate-change-planner (external, `fgplanner`) — deterministic change
    planner (`plan_change()`): verdict, coverage, reuse, insertion, CLI
    generation. Also a standalone CLI (`python -m fgplanner`). Not part of this
    repo — installed as a git dependency of fwanalyst_server.
  - fwanalyst_server — the unified MCP server described above.
  - standards_mcp — zone matrix, naming.yaml, review_requirements.yaml, static
    policy evaluation (policy_engine.py). Static TUFIN-era data — do not use for
    live verdicts.
  - fortimanager_mcp — read-only FortiManager JSON-RPC queries + matching.py
    set-semantics layer.
  - zone_mcp — live 4THealth zone policy API (IP→zone + verdict). **Authoritative
    for verdicts** — always prefer this over standards_mcp for engineer workflows.
  - feedback_mcp — SQLite decision/audit store with similarity lookup.
  - intake_mcp — .xlsx parser + manual entry normaliser.
  - netbrain_mcp — planned, not yet started (blocked on NetBrain API access).
- Dataflow: intake_mcp (normalise) → zone_mcp (verdict) + fortimanager_mcp
  (existing rules/objects) → standards_mcp (naming/logging/approval) →
  feedback_mcp (record decision).

3) Key repository conventions and patterns

- Each MCP server is an independent Python package with its own pyproject.toml
  and server.py, aggregated into `fwanalyst_server` via `add_tool`. Follow the
  fortimanager_mcp pattern when adding a new MCP package (see CONTRIBUTING.md).
- Configuration vs code:
  - standards_mcp/naming.yaml and standards_mcp/review_requirements.yaml are
    team-maintained config files loaded at server startup.
  - Do not hand-edit policy_db.json — regenerate it with build_policy_db.py when
    TUFIN CSVs change.
- Policy engine is stateless and pure (policy_engine.py): callables accept DB
  dicts; avoid global I/O in evaluation logic.
- Security-sensitive files:
  - Do not commit credentials.yaml or any file containing API keys, internal IPs,
    or hostnames. credentials.yaml.example exists as a template. `__main__.py`
    refuses to start in HTTP mode (warns in stdio) when credentials.yaml is
    group/world-accessible.
  - `fwanalyst_server/auth.py` resolves bearer tokens to per-engineer ADOM
    restrictions (`server.tokens` in credentials.yaml) and to a token label for
    access logging; see context.py for the `allowed_adoms_var`/`token_label_var`
    ContextVars it injects per request. Every unified-server tool logs one INFO
    line per call (tool name + token label, never args/tokens).
  - Workstation tokens: root `.mcp.json.example` uses `${FW_ANALYST_CLIENT_TOKEN}`
    env expansion — tokens never sit in a plaintext committed file; `.mcp.json`
    itself is gitignored.
  - TLS: `FW_ANALYST_SSL_CERTFILE`/`FW_ANALYST_SSL_KEYFILE` (or the matching
    credentials.yaml `server.ssl_certfile`/`ssl_keyfile` keys) enable direct
    uvicorn TLS, both-or-neither — see docs/tls-setup.md.
- Developer run modes:
  - stdio mode (`uv run python -m <pkg>.server` or `python -m fwanalyst_server`)
    for quick debugging; `MCP_TRANSPORT=http` for production-like behaviour.
- Smoke-testing: `scripts/run_smoke.py` / `scripts/smoke-test.sh` hit the single
  unified port (8000) and assert 401 without a token, non-401 with one.

4) AI assistant / existing assistant artifacts to reuse

- CLAUDE.md and .claude/skills/ contain explicit directions and slash-command
  examples for Claude Code. Prioritize them when producing assistant prompts or
  building MCP interactions — CLAUDE.md is the canonical architecture reference;
  keep this file consistent with it.
- pytest-based tests live in tests/; prefer running/extending those over manual
  smoke testing where possible.

5) When changing repository structure or adding servers

- Follow CONTRIBUTING.md: add `<name>_mcp/` with __init__.py, server.py and
  pyproject.toml; document creds in credentials.yaml.example; register the new
  tools in `fwanalyst_server/server.py` (and update the tool count assertion in
  tests/test_fwanalyst_auth.py); add smoke test notes to docs/installation.md;
  and include a smoke test result in the PR.

6) Useful files to inspect first in a Copilot session

- README.md, CLAUDE.md, CONTRIBUTING.md, docs/installation.md,
  docs/architecture.md, fwanalyst_server/server.py, fwanalyst_server/auth.py,
  standards_mcp/policy_engine.py, standards_mcp/naming.yaml,
  standards_mcp/review_requirements.yaml, .claude/skills/*.md (planner internals
  now live in the external fortigate-change-planner repo)
