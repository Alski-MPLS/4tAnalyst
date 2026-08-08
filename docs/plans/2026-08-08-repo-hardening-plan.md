# 4tAnalyst Review — Approved-Pending Plans (2026-08-08)

Findings from a four-question review (MCP config, workstation connection, public-GitHub
readiness, security), stress-tested by a devil's-advocate pass. Items marked **[DA]**
were changed or added by that pass. Execution target: `development` branch.

Hard gate for ALL work: full `pytest -q tests/` must pass, and any diff touching
`fwanalyst_server/auth.py`, `fwanalyst_server/__main__.py` middleware ordering,
`rate_limit.py`, or `planner/engine.py` gets a second review pass before commit.

---

## Plan 1 — MCP configuration hygiene

Verdict: architecture is already close to best practice (fail-closed bearer,
constant-time compare, per-token ADOM scoping, DNS-rebinding protection, rate
limit + request timeout, deterministic core). Remaining items are small.

1. **Rate limiter hygiene** (`fwanalyst_server/rate_limit.py`): delete empty deques
   after pruning; cap the `windows` dict (e.g. 1000 buckets, evict oldest).
   **[DA] Keep session-ID keying** — the limiter runs behind auth, so the key is only
   "spoofable" by an authenticated engineer; keying by token would collapse engineers
   sharing `auth_token` into one bucket (self-DoS). Classify as hygiene, not a vuln.
2. **Tool annotations**: add `readOnlyHint` (and `destructiveHint: false`) annotations
   to the 31 read-only tools. Advisory client UX only — not security. Update the
   tool-count/shape assertions in `tests/test_fwanalyst_auth.py` as needed.
3. **[DA] Dropped: unauthenticated `/healthz`.** The existing convention (401 on
   `/mcp` = alive with auth enforced, per `scripts/run_smoke.py`) is a better liveness
   signal. Document "401 = healthy" in docs/troubleshooting.md instead.
4. **OAuth 2.1 / Entra**: stays deferred to Phase 4 as roadmapped. No code now.

## Plan 2 — Workstation connection

Verdict: sparse-checkout + central server model is sound; the config examples and
gitignore have real gaps.

1. **Add `.mcp.json` to `.gitignore`** — onboarding doc claims it's ignored; it isn't.
2. **Ship `.mcp.json.example` at repo root**, replacing
   `.claude/mcp_servers.json.example` (which matches no path Claude Code reads);
   update `docs/workstation-onboarding.md` accordingly.
3. **Env-var token in the example**: `"Authorization": "Bearer ${FW_ANALYST_CLIENT_TOKEN}"`
   via Claude Code env expansion, so tokens live in env/keychain, not plaintext files.
   **[DA] Use a NEW variable name** (`FW_ANALYST_CLIENT_TOKEN`) — `FW_ANALYST_TOKEN` is
   already the server-side admin token and reuse would conflate the two.
4. **TLS before pilot** — **[DA] simplest path first**: uvicorn's native
   `ssl_certfile`/`ssl_keyfile` with an internal-CA cert (one config change, no nginx
   SSE buffering/timeout pitfalls); graduate to nginx when rotation/mTLS/HA is needed.
   Must add the TLS hostname to `allowed_hosts` or DNS-rebinding protection will
   reject every engineer. Update docs/tls-setup.md with this option.
5. **[DA] Deferred: separate workstation repo / Claude Code plugin.** Skills are
   tightly coupled to server tool names and report schema; a second repo invites
   silent version skew during the pilot. Revisit after Phase 3 stabilizes the tool
   surface — then publish a plugin *from* this monorepo via CI.

## Plan 3 — Public GitHub readiness

Verdict: **not ready**, and **[DA] the better question is what to publish.**
Tracked files encode the utility's zone taxonomy ("NSS ..." names in
`device_zone_map.example.yaml`, `docs/device-zone-map.md`), a real policy name in
`Changelog.md`, device-naming convention (MNHQ-FW01), the 4THealth product name
throughout, and live-test narratives in `todo.md` — recon-relevant for an energy
utility and a scrub that must be perfect forever.

**Recommended path (Option A, [DA]):** don't publish this repo. Extract the
org-neutral, genuinely reusable core — `planner/` (insertion/shadowing analysis) and
`fortimanager_mcp/matching.py` (set-semantics matching) — into a NEW public repo with
fresh history and synthetic fixtures. ~90% smaller scrub surface, no tail risk.

**Alternative (Option B):** sanitized full publish — new repo, fresh history
(never rewrite this one), after: genericizing all NSS zone names / MNHQ convention /
4THealth references (large rename touching most of the tree), rewriting Changelog.md
and dropping todo.md/highlevel-4tanalyst.md, plus manual review. gitleaks over the
new tree is a gate but will NOT catch identifier leakage — manual scrub review required.

**Either way, OSS baseline for whatever goes public:** LICENSE (Apache-2.0),
vulnerability-reporting section in SECURITY.md, CI with gitleaks + pip-audit
(+ CodeQL), dependabot, dependency pinning per Plan 4.5.

**Regardless of publishing:** run gitleaks over this repo's full history once as
hygiene (confirms nothing needs rotation). `docs/zone-name-mapping.md` is untracked —
keep it that way (it's already in the "never commit" spirit; consider adding to
.gitignore explicitly).

## Plan 4 — Security hardening

Verdict: strong baseline for a pilot. Gaps, in priority order:

1. **TLS** — top blocker (repo's own todo #2). Path per Plan 2.4.
2. **Rate limiter memory** — per Plan 1.1 (hygiene).
3. **Access logging** — log token label + tool name per request. **[DA] Implement at
   the FastMCP layer** (wrap tools at `add_tool` time; read the label from a new
   ContextVar set in `require_bearer` beside `allowed_adoms_var`), NOT by parsing
   JSON-RPC bodies in ASGI middleware. Log to stdout/journald; do not mix with
   feedback_mcp's SQLite audit log.
4. **zone_policy TLS**: support `verify: /path/to/internal-ca.pem` instead of
   `verify_ssl: false`; config-schema tweak + docs.
5. **Dependency pinning** — **[DA] committing uv.lock alone is decorative** (the
   documented `uv pip install -e` flow ignores it). Cheaper interim: generate a
   constraints file (`uv pip compile`) and add `-c constraints.txt` to Dockerfile/CI
   install lines; full uv-workspace migration later. Add pip-audit to CI now.
6. **Runtime hardening**: non-root `USER` in Dockerfile.dev (UID must be able to
   write the `output/` host mount in dev compose); systemd unit gains
   `NoNewPrivileges=yes`, `PrivateTmp=yes`, `ProtectSystem=strict` **with
   `ReadWritePaths=` covering feedback.db (+ -wal/-shm), output/, and cache dirs** —
   without those paths the unit fails in the field.
7. **Credential file perms** — **[DA] code beats prose**: in `_load_creds()`, warn
   (or refuse in HTTP mode) when `credentials.yaml` is group/world-readable. Also
   document token rotation procedure in SECURITY.md.

---

## Execution model recommendation

Split by risk, not one model for everything **[DA]**:
- **Sonnet 5** for the mechanical majority: .gitignore, example files, docs, CI YAML,
  Dockerfile/systemd, constraints file, tool annotations.
- **Opus 5 (or Fable) + mandatory second review pass** for security-boundary files:
  `auth.py`, `__main__.py` middleware ordering, `rate_limit.py`, access-logging
  ContextVar plumbing.
- Gate every change on `pytest -q tests/` regardless of model.
