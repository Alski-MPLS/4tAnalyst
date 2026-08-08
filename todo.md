# 4tAnalyst — To-Do / Gap Tracker

## Session summary — 2026-07-05 (planner hardening + consolidated multi-value)

All four items found/built during live testing against the lab FortiWiFi-71G; test suite grew 147 → 181.

- **Interface-scoped coverage (bug fix, found live)** — a broad `internal→wan1` accept rule was reported as "already covered" for an east-west flow it would never apply to. Interfaces are now resolved before coverage analysis and rules must be scoped to the flow's interface pair to count.
- **"allow only" access type (bug fix, found live)** — `standards_mcp.policy_engine.evaluate()` didn't handle `allow only` policies: a non-listed service was wrongly ALLOWED. Full precedence rules added (allow-only + non-matching service → BLOCKED).
- **Internet catch-all defaulting** — IPs 4THealth can't resolve now default to the catch-all `Internet` zone (with an explanatory note in the report) and the verdict is re-derived from the live policy table; any flow touching the Internet zone is critical risk with a new `allow_internet_inbound` logging profile (log start+end, SIEM forward, 180-day retention). Deliberate design: the internet is *not* enumerated as subnets; unmatched = Internet. RFC1918 IPs that hit this path are a 4THealth registration gap the engineer must fix, not implement around.
- **Group-append alternative (Option B)** — when a near-miss enabled rule would cover the request except for one address side that references a group, the plan carries the smaller change (append the missing endpoint(s) to the group) alongside the new-policy plan. Always includes the ADOM-wide blast radius (every other rule referencing the group, directly or via nesting); never offered for negated sides. Engineer chooses ONE option.
- **Consolidated multi-value planning** — `plan_change` src/dst/service accept lists or comma-separated strings; ONE call → ONE policy per firewall covering every combination. Per-combination zone verdicts (any UNKNOWN → no action; mixed ALLOWED+BLOCKED → "split the request" error). "Already covered" requires every pair covered. Sides with >3 members auto-group (`GRP_<ticket>_SRC/DST`); `--src-group`/`--dst-group` (CLI) and `src_group`/`dst_group` (tool) force named groups. `/analyze-request` now calls `plan_change` once per request instead of once per flow.
- Docs swept 2026-07-05: README, architecture, usage, engineer-workflow, troubleshooting, installation, CONTRIBUTING updated for all of the above plus stale pre-consolidation references (per-service systemd units, SSE wording, FMG "session expired" advice contradicting the Bearer-auth model).

**Follow-ups:**
- [ ] `GROUP_THRESHOLD = 3` is a first guess — revisit once engineers have opinions on when a group beats inline members
- [ ] Auto-group names (`GRP_<ticket>_SRC/DST`) are ticket-scoped; consider purpose-based naming guidance in naming.yaml for groups meant to be reused across tickets

## Session summary — 2026-07-04 (deterministic change-planner conversion)

**Architectural conversion completed** ("LLM orchestrates, code computes"):
- **`planner/` package** — new deterministic core. `plan_change()` computes zone verdict (live 4THealth), existing-rule coverage, object reuse vs. create, rule **insertion point** (first-match shadowing analysis with `shadowed_by`/`would_shadow` reporting), naming/logging/risk/approval, and exact FortiGate CLI. Emits the `render_report.py` payload directly. Runs as an MCP tool **and** as a standalone CLI (`python -m planner ... --firewall DEVICE:ADOM`) with no LLM in the path.
- **`fortimanager_mcp/matching.py`** — replaced the substring service/address matching in `query.py`. **Fixed a real correctness bug:** requested service "80" previously matched any object named `TCP_8080` (substring); now service objects resolve to numeric proto/port ranges and address groups recurse with cycle guards. Negate flags, schedules, and disabled status are honoured. `search_policies` now returns `{policies, packages_searched, packages_failed, degraded}` — package fetch failures are no longer silently swallowed (the old empty-result-on-timeout worry is now structurally handled: `degraded=True` forbids "already covered"/"no rule exists" conclusions).
- **`fwanalyst_server/`** — single unified MCP server (port 8000, streamable-HTTP at `/mcp`) aggregating all 27 tools + `plan_change`, behind static-bearer auth (fail-closed; token via `FW_ANALYST_TOKEN` or `credentials.yaml server.auth_token`). Replaces the five unauthenticated SSE ports. Verified live in Docker: 401 without token, 200 with.
- **`/analyze-request` collapsed** — Steps 2–7 (verdict, rule search, decision table, CLI assembly) are no longer prose the LLM executes; the skill now calls `plan_change` once and presents the result verbatim.
- Infra updated: single-service docker-compose (dev + CI), auth-aware smoke checks, CI workflow installs all packages and runs the full test suite, `systemd/fw-analyst.service` (single unit) replaces the per-package plan.
- Test suite grew from 39 to 147 (matching semantics, insertion analysis, standards rules, engine end-to-end with fake clients, CLI generation exact strings, auth middleware).

**Follow-ups created by this conversion (see line items below):**
- [ ] TLS termination still required — auth now exists but transport is plain HTTP (existing blocker, unchanged)
- [ ] Multi-VDOM devices: planner fetches `vdom/root` interfaces/routes only (pre-existing client behaviour) — decide explicit VDOM support or document out-of-scope
- [ ] Section/label conventions for rule placement ("VPN rules go in the VPN section") are not encoded — insertion analysis is shadow-correct but section placement is engineer judgment; could be added to naming.yaml later
- [ ] NAT'd requests: `plan_change` analyses the addresses it is given — the VIP-vs-real-destination question from 2026-07-02 is still an intake-level decision to encode

---

## Session summary — 2026-07-02 (device-zone-map + live walkthrough)

**Completed:**
- Ran `scripts/import_zone_map.py --from-fortimanager` against the lab FortiManager (192.0.2.10) and populated `device_zone_map.yaml` for `FortiWiFi-71G` (gitignored, not in repo): `wan1` → `Internet`, `internal`/`FTG_Test` → `IT Lab`; `fortilink`/`wqt.root` and 17 unused/disabled interfaces left unmapped by design. Verified via `get_interface_map()` that `zone_map_missing` correctly clears for mapped interfaces.
- Decided and documented engineer workstation setup as a **git sparse-checkout** of this single repo (`.claude` + `scripts` only) — see `docs/engineer-workflow.md` §1. Rejected a full clone (unnecessary clutter) and a second workstation-only repo (drift risk, since skills and `scripts/render_report.py` change in lockstep with server code).
- Created `.claude/mcp_servers.json.example` (previously referenced in `docs/configuration.md` as "the example" but never actually existed in the repo).
- Ran two full `/analyze-request` walkthroughs end-to-end against the live lab stack (zone_mcp → mock 4THealth on :8100, fortimanager_mcp → lab FMG, standards_mcp, `scripts/render_report.py`):
  1. No-NAT request, RFC1918 unregistered source → correctly returned `UNKNOWN`, no CLI generated.
  2. NAT/DNAT request (public source, VIP) → after a policy was added on the 4THealth side (`Internet → Internal-Zone: block all`), correctly returned `BLOCKED` and generated a full `blocked_exception` CLI (address objects, VIP, policy) with "do not push until approved" warnings baked into both `report.html` and `implementation.conf`, and a `critical` risk/approval chain requiring CISO sign-off.

**New gaps found this session, all fixed same-session (see line items below for detail):**
- `analyze-request/SKILL.md` Step 3 referenced tools that don't exist on the server (`get_policy_packages`, `search_rules`) — fixed to call the real `search_policies(adom, device, src_ip, dst_ip, service)`. Same stale references also found and fixed in `docs/architecture.md` (tool list + data-flow diagram).
- No `vip` object type in `standards_mcp/naming.yaml` — added (`VIP_<TICKET_ID>_<SEQ>`, matching the ticket-scoped convention already used by `policy`/`nat_rule`), plus updated the `get_naming_convention` docstring in `standards_mcp/server.py`.
- 4THealth's `Internet` zone (empty subnets, correct catch-all design) had zero policies referencing it as `from_zone`/`to_zone` — fixed by adding both `Internet → Internal-Zone: block all` and `Internet → WAN-Zone: block all` on the 4THealth side. Re-verified live: VIP-address and real-destination checks for the same NAT'd request now agree (both `BLOCKED`) — the ambiguity from the CHG0000001 walkthrough is resolved.

**Still open (not fixed this session):**
- RFC1918-private, unregistered source IPs (e.g. `192.168.20.20`) still have no resolution path — confirmed still `UNKNOWN` even after the `Internet` zone policy fixes, since those only cover public IPs. Per documented process, this requires 4THealth subnet registration, not automated handling.
- The `Internal-Zone` / FortiManager interface-name mismatch (already tracked below) — reconfirmed a second time, live, not yet fixed.
- The skill still has no explicit rule for *which* address (VIP vs. real destination) to check for NAT'd requests — no longer produces conflicting verdicts now that both policies exist, but the ambiguity in the skill's instructions is still there and should be resolved deliberately, not just by coincidence of the two verdicts currently agreeing.

---

## Blocking for first test server deployment

- [ ] **Test FortiManager connectivity against the two production hosts** — FMG-SITE-A (10.0.0.101) and FMG-SITE-B (10.0.0.102) still untested.
  - [x] **Auth model corrected and confirmed against a test FMG (7.6.x)** — `fortimanager_mcp/client.py` originally implemented session-based login (hardcoded `user: "api"`, `passwd: <key>`), which does not work for a **REST API Administrator** account (FortiManager's dedicated API-key admin type — no password, no session; the key is sent as an `Authorization: Bearer` header on every call). Rewrote the client accordingly; verified live against a test FMG (192.0.2.10, 7.6.x) — `get_adoms()`/`get_devices()` returned real data. See `docs/configuration.md#fortimanager` and `docs/troubleshooting.md` for the corrected setup/debugging steps. **Still need:** confirm the two production accounts (FMG-SITE-A, FMG-SITE-B) are also REST API Administrator type with JSON API Access + correct Trusted Hosts before relying on this against production.
  - Specifically test empty-response-on-timeout behavior — FortiManager can return HTTP 200 with an empty result set on session expiry rather than an error. Confirm the client handles this correctly.

- [x] **Create docker-compose.yml** — a full-compose example was added to run all servers as a unit
  - standards_mcp → port 8000
  - fortimanager_mcp → port 8001
  - feedback_mcp → port 8002
  - intake_mcp → port 8003
  - zone_mcp → port 8004
  - netbrain_mcp → port 8005 (add when integration is ready)
  - **Fixed a real startup bug**: `mcp run <file> --transport sse --port N` doesn't work on the installed `mcp` version (1.28.1) — `FastMCP.run()` only accepts `transport`; host/port come from `FASTMCP_HOST`/`FASTMCP_PORT` env vars. `docker-compose.ci.yml` already used the correct `python -m <pkg>` + env var form; `docker-compose.yml` (dev) still had the broken form until now. Also fixed the same bug in `scripts/start-all.sh`, `CLAUDE.md`, and `docs/installation.md`, which all documented/ran the broken invocation.

- [x] **Add developer helpers** — scripts/start-all.sh, scripts/smoke-test.sh, scripts/run_smoke.py were added for local dev and smoke testing

- [x] **Add CI smoke-test workflow** — GitHub Actions workflow builds a dev image, runs unit tests, and performs containerized smoke tests; uploads logs on failure

- [x] **Docker dev image** — Dockerfile.dev and .dockerignore added (used by CI)

- [x] **Unit tests scaffolded** — tests/test_policy_engine.py plus additional unit tests for clients added; run with pytest

- [ ] **TLS / nginx reverse proxy** — static-bearer auth is now enforced on the single port 8000 (2026-07-04), but the transport is still plain HTTP; TLS termination should be in place before any real change request data flows through the system, especially for deployments in a regulated environment (NERC CIP, HIPAA, SOX, etc.).

- [x] **Write the missing systemd unit files** — obsoleted by the 2026-07-04 consolidation: production is now a single `fwanalyst_server` process, and `systemd/fw-analyst.service` (one unit, `MCP_TRANSPORT=http` + `FW_ANALYST_TOKEN` via EnvironmentFile) replaces the planned five per-package units.

- [ ] **Get IT/InfoSec approval for Claude Code on engineer workstations** — Claude Code is a commercial AI tool. Installation on company workstations may require change control, security review, or license approval. Do not proceed to team pilot without this clearance.

- [x] **Data-sensitivity posture decided (2026-07-17)** — after discussion, the working assumption is that this codebase itself carries no regulated data (no real credentials, no live topology once `fmg-test.md`/`todo.md`/etc. are scrubbed per `SECURITY.md`), and 4tAnalyst is usable today with Claude Code against an inference path of the deploying org's choice (direct Anthropic API or Bedrock). Responsibility for classifying *their own* data (BCSI, PHI, cardholder data, PII, or otherwise) and clearing it against *their own* compliance program shifts to whoever deploys this tool in a regulated environment — it is no longer treated as a blocker for this repo's own development. See the generalized `docs/compliance.md` for the reasoning and the deployer-facing checklist.
  - **Bedrock**: data goes to the deploying org's own AWS account/Bedrock endpoint; governed by their existing AWS enterprise agreement — generally the stronger posture for orgs already on AWS
  - **Anthropic direct API / Claude Max**: data goes to Anthropic's infrastructure under Anthropic's terms (or a negotiated enterprise agreement)
  - **Self-hosted model**: no external data transmission; highest infrastructure cost; most conservative posture regardless of regulatory regime
  - **Still recommended, not a hard gate**: orgs with regulated data (NERC CIP BCSI, HIPAA PHI, SOX financial records, GDPR/CCPA PII, etc.) should not type raw sensitive identifiers into prompts until they've made their own inference-path and data-handling determination — see `docs/compliance.md`.

- [ ] **(Deployer responsibility, not a repo blocker) Engage your organization's compliance team if deploying in a regulated environment** — 4tAnalyst outputs may become part of change records and audit evidence for whichever regime applies to the deploying org. Bring `docs/compliance.md` and `SECURITY.md` to that engagement. No longer treated as a prerequisite for this repo's own progress, since the repo carries no live regulated data.

- [ ] **Verify cloud provider data processing terms** (if using Bedrock or another managed inference path) — confirm with your account team that inference data is covered under your existing enterprise DPA, and check whether provider-side invocation logging is enabled and how those logs are handled.

- [ ] **MCP-as-boundary mitigation (optional hardening, not required for pilot)** — intake_mcp currently returns raw IPs to Claude Code, which then sends them to the inference endpoint. For deployments with sensitive/regulated zones, the mitigation is: engineer provides a ticket number → MCP resolves IPs internally → only zone names and verdicts reach the inference endpoint. Raw sensitive identifiers never appear in prompts. Kept as a Phase 3 item for orgs that want it; see `docs/compliance.md` for architecture detail.

---

## Needed for engineer workflow

- [x] **Create `.claude/skills/` directory with skill files** — engineer slash commands
  - `analyze-request/SKILL.md` — full end-to-end request analysis (zone verdict + firewall rule search + naming/logging + approval chain) + generated `report.html`/`implementation.conf` for ticket attachment (Step 7)
  - `check-policy/SKILL.md` — quick zone policy verdict for a src→dst flow
  - `validate-rule/SKILL.md` — pre-submission rule validation against naming/logging standards (FortiGate only)
  - `generate-peer-review/SKILL.md` — structured peer review package for second-engineer sign-off
  - `record-decision/SKILL.md` — audit trail entry to the feedback store
  - `missing-info/SKILL.md` — triage incomplete requests and draft follow-up to submitter
  - **Topology note**: engineer must declare firewalls explicitly; NetBrain integration planned for auto path-discovery (details TBD)
  - **Note**: these were originally flat `.md` files directly under `.claude/skills/`, which Claude Code does not register as slash commands (it expects `<name>/SKILL.md`). Restructured into per-skill folders so they actually load.

- [x] **`/analyze-request` generates ticket-attachable artifacts** — Step 7 now writes `output/<ticket_id_or_timestamp>/report.html` and `implementation.conf` (FortiGate CLI commands, or exception-request language if the verdict is BLOCKED) via `scripts/render_report.py` (stdlib-only, no new dependency). Covers four cases: `new_rule`, `blocked_exception`, `already_covered` (no commands needed), `unknown_no_action` (verdict couldn't be determined). 19 unit tests in `tests/test_render_report.py`. `output/` is gitignored. See `docs/superpowers/specs/2026-07-01-analyze-request-artifacts-design.md` for the design.

- [x] **Create `.claude/mcp_servers.json.example`** — added; previously referenced by `docs/configuration.md` as "the example" but never actually existed in the repo.
- [ ] **Promote `.mcp.json.example` to a committed `.mcp.json`** — fill in the RHEL server's real hostname (`https://`, once TLS is live) and commit it. Now that the token is `${FW_ANALYST_CLIENT_TOKEN}` (env-var expansion, not a literal value), the file itself carries no secret, so committing the real version is safe and gives engineers zero-config setup via sparse-checkout + `git pull`. (Note: `.mcp.json` is currently gitignored as defense in depth — this would need an explicit `!.mcp.json` exception or committing under a different tracked name.)
- [x] **Fix `analyze-request/SKILL.md` Step 3** — it instructed calling `get_adoms()` → `get_policy_packages(adom)` → `search_rules(adom, package, ...)`, but neither `get_policy_packages` nor `search_rules` exist on `fortimanager_mcp/server.py`. Fixed to call `search_policies(adom, device, src_ip, dst_ip, service)` directly — no package-lookup step needed. Also fixed the same stale references in `docs/architecture.md` (tool list and data-flow diagram). Re-verified live post-fix: `search_policies(client, 'root', 'FortiWiFi-71G', '8.8.8.8', '10.1.1.7', 'ssh')` returns real data.
- [x] **Decided: engineer workstation setup = git sparse-checkout of this repo** (`.claude` + `scripts` only), not a full clone or a separate distributable/second repo. Rationale: skills (`.claude/skills/`) and `scripts/render_report.py` change in lockstep with server-side code (e.g. commit `f88e0e5` touched `fortimanager_mcp/query.py` and `analyze-request/SKILL.md` together) — a second repo or static package would drift. Sparse-checkout keeps one source of truth while still giving engineers a slim local footprint. Documented in `docs/engineer-workflow.md` §1.
  - [ ] **Set engineer team repo access to read-only** — sparse-checkout doesn't restrict push; that's a repo-permissions setting (GitHub/GitLab team role) independent of checkout method. Needed so engineers can `git pull` updates but can't accidentally push into skills/server code.
  - [x] **Write a one-page onboarding doc/README for `fw-analyst-workstation`** distinct from the full `docs/engineer-workflow.md` — engineers doing the sparse clone don't need the server-deployment context, just the clone/sparse-checkout/verify steps. **Done 2026-07-17**: `docs/workstation-onboarding.md` — clone/sparse-checkout/Claude Code install/MCP config/verify only, links out to `docs/engineer-workflow.md` §2 for working an actual request. Linked from `README.md`'s doc table and `CLAUDE.md`'s Key Reference Files.

- [x] **Documentation** — public-repo-ready docs created
  - `README.md` — front door: what it does, architecture diagram, quick start, links
  - `docs/installation.md` — server and workstation setup step by step
  - `docs/configuration.md` — credentials.yaml reference, env vars, engineer workstation config
  - `docs/usage.md` — all six slash commands with examples and workflow diagram
  - `docs/troubleshooting.md` — common errors with root causes and fixes
  - `docs/architecture.md` — design decisions, data flow, phase roadmap
  - `docs/engineer-workflow.md` — end-to-end how-to guide for engineers (setup, request intake, data flow, troubleshooting)
  - `docs/compliance.md` — general data-sensitivity/compliance considerations for regulated deployments (NERC CIP as worked example; HIPAA/SOX/PCI-DSS/GDPR equally applicable), inference path comparison, questions for your own compliance team
  - `SECURITY.md` — credential handling, sensitive data checklist, vulnerability reporting
  - `CONTRIBUTING.md` — who maintains what, how to add a server, PR guidelines

- [ ] **Create `docs/zone-name-mapping.md`** — translation table between 4THealth policy zone names and FortiManager ADOM zone names. Required before zone-to-rule mapping can be fully validated. Requires input from engineers familiar with the FortiManager environment.
  - **Confirmed with a live example**: on the test FMG, 4THealth's `Internal-Zone` does not correspond to FortiWiFi-71G's `internal` interface (192.168.1.0/24) — a destination IP classified as `Internal-Zone` actually resolved to the device's `FTG_Test` interface (10.1.1.0/24). `/analyze-request` Step 7 now surfaces this kind of mismatch per-firewall in its `warnings` output (both `report.html` and `implementation.conf`) rather than silently trusting the zone name, but the underlying mapping table is still needed.
  - **Reconfirmed 2026-07-02** on a second live `/analyze-request` run against the same mismatch.

- [ ] **`analyze-request/SKILL.md` Step 2 still has no explicit rule for which address (VIP or real destination) to zone-check on a NAT'd request.** The concrete symptom that surfaced this — VIP and real-destination checks disagreeing (`UNKNOWN` vs `BLOCKED`) for the same request — is now resolved (see the `Internet → WAN-Zone`/`Internet → Internal-Zone` fix below), but that's a coincidence of both zones now being fully modeled, not a rule in the skill. Add an explicit instruction once the team decides the intended semantics (a FortiGate policy actually filters on the pre-NAT/VIP address, for what it's worth) so future zone-catalog gaps don't silently produce inconsistent verdicts again.

- [x] **No `vip` object type in `standards_mcp/naming.yaml`** — DNAT/VIP objects (`config firewall vip`) had no documented naming convention, unlike host/network/policy/nat_rule. Found live while generating a `blocked_exception` CLI for a NAT'd request. Fixed: added a `vip` entry (`VIP_<TICKET_ID>_<SEQ>`, matching the ticket-scoped convention already used by `policy`/`nat_rule`) and updated the `get_naming_convention` docstring in `standards_mcp/server.py` to list it. Verified live: `get_naming_convention('vip', 'fortigate')` returns the new pattern.

---

## Data accuracy prerequisites (must complete before any engineer pilot)

- [x] **Resolve standards_mcp vs zone_mcp data overlap** — `standards_mcp` has a `check_traffic` tool that reads from the static `policy_db.json` (TUFIN-era data). `zone_mcp` has `check_ip_traffic` which queries 4THealth live. These two paths can return different answers for the same flow. Until standards_mcp is migrated to live 4THealth data, skills must use `zone_mcp` exclusively for policy verdicts. **Already documented** — CLAUDE.md's "Critical data-source warning" section (and the `fwanalyst_server` tool instructions string) both state this explicitly: use `zone_mcp` for verdicts, `standards_mcp` only for naming/logging/approval chains. Confirmed 2026-07-17 via graphify query — no further action needed unless standards_mcp migrates to live data.

- [ ] **Populate `standards_mcp/naming.yaml`** with real values — confirm H_/N_ prefixes match actual naming in use on FortiGate; validate zone abbreviations against real rule names
- [ ] **Populate `standards_mcp/review_requirements.yaml`** with real, compliance-team-validated values — do not use placeholder approval chains or SLA hours in any real submission
- [ ] **Validate zone names in 4THealth** against ADOM/zone names visible in FortiManager — mismatches produce UNKNOWN verdicts
- [x] **Found and fixed live: 4THealth's `Internet` zone (empty subnets, intentional catch-all for public/non-RFC1918 IPs) had zero policies referencing it.** The zone itself was already correctly classifying public IPs (e.g. `8.8.8.8` → `src_zones: ["Internet"]`) — the gap was the policy table, not the zone catalog. Added both `Internet → Internal-Zone: block all` and `Internet → WAN-Zone: block all` on the 4THealth side. Re-verified live: the VIP-address check (`192.168.40.150`, `WAN-Zone`) and the real-destination check (`10.1.1.7`, `Internal-Zone`) for the same NAT'd request now both return `BLOCKED` (previously `UNKNOWN` vs `BLOCKED`) — see the still-open Step 2 rule item above for the remaining skill-instruction gap.
- [ ] **Define policy data staleness SLA** — document how often the 4THealth zone/policy database is updated and what the maximum acceptable lag is before engineers must treat verdicts as untrustworthy
- [ ] **Resolve engineer identity for audit log** — free-form string is not audit-grade for a regulated environment (NERC CIP, HIPAA, PCI-DSS, etc.). Decide: AD/Entra token, ServiceNow user ID, or per-engineer API key. Do not begin recording official change decisions until this is resolved.

---

## Deployment infrastructure (when ready to go to central server)

- [ ] **nginx / reverse proxy config** — moved to blocking list above; must have TLS before production
- [ ] **Smoke test checklist after deploy**
  - `get_adoms()` on FortiManager
  - `check_ip_traffic()` on zone_mcp with a known IP pair
  - `parse_spreadsheet_file()` on a real .xlsx
  - `record_feedback()` on Feedback
  - Verify FortiManager returns a real error (not a silent empty result) when queried with an invalid session
- [x] **Rate limiting / call budget** — a runaway Claude Code session could generate hundreds of API calls against FortiManager. Implement per-session call budgets or rate limiting on the MCP servers before multi-engineer use. **Fixed 2026-07-17**: `fwanalyst_server/rate_limit.py` adds a per-`Mcp-Session-Id` sliding-window ASGI middleware (default 300 req/60s, `429 Retry-After` past that; `FW_ANALYST_RATE_LIMIT_MAX=0` disables). Wired into `__main__.py` inside `require_bearer` so unauthenticated requests never consume budget. 6 new tests in `tests/test_rate_limit.py` (window expiry, per-session isolation, non-HTTP scopes unmetered, invalid-config guard). Documented in `CLAUDE.md`, `docs/architecture.md`, `docs/configuration.md`.

---

## Open questions (need answers before Phase 3)

- [x] Zone naming consistency — **confirmed: 4THealth policy zone names differ from FortiManager ADOM zone names; a mapping table is required**
  - See `docs/zone-name-mapping.md` (to be created — placeholder referenced in `docs/engineer-workflow.md`)
- [x] Network topology / IPAM access — partially resolved via 4THealth zone policy API (`zone_mcp`); full path-level topology pending NetBrain integration (details TBD)
- [ ] Ansible inventory structure — which firewall maps to which IP range, needed for Phase 5 change preview
- [ ] Engineer identity for audit log — moved to data accuracy prerequisites above as a blocker
- [x] Multi-hop traffic percentage — **~80% of OT requests cross multiple firewalls; ~70-80% of IT requests stay on a single firewall/package.** Manual firewall declaration is an acceptable interim approach; path auto-discovery remains a Phase 3 goal.
- [ ] Anthropic subscription model — per-seat Claude Max or API key? TBD; currently under investigation. Impacts per-engineer setup and usage tracking.
- [ ] Rollback plan for a bad recommendation — if the tool suggests an incorrect approval chain and a change proceeds without required approvals, what is the remediation process? Governance decision needed before production use.
- [x] 4THealth API dependency — **user's team owns 4THealth.** Internal escalation path for outages and API changes. Document the internal owner and runbook in `docs/engineer-workflow.md` when deploying to production.

---

## Future phases (not needed for initial testing)

- [x] **Phase 2** — FortiManager MCP, IP-to-zone mapper (`zone_mcp` — 4THealth external API, live)
  - 5 tools: `query_zone_policy`, `get_zones`, `get_policies`, `find_zone_for_ip`, `check_ip_traffic`
  - 33 zones, 161 policies confirmed live
- [ ] **NetBrain integration** — build `netbrain_mcp` (port 8005) once API details are available. Goal: given a src/dst IP, return the firewalls in the traffic path. This eliminates the need for engineers to declare firewalls manually. Framed as a hint the engineer confirms, not an authoritative path declaration.
  - Status: blocked on API access and documentation from NetBrain team
  - When ready: add `netbrain_mcp` to the package list, docker-compose, and `/analyze-request` skill (path suggestion step)

- [ ] **Phase 3 (revised)** — Full team deployment + feedback collection + risk scorer
  - Get engineers using the system on real tickets before building the recommendation engine
  - Activate `feedback_mcp` and `/record-decision` — collect 4–8 weeks of real decision data
  - Lock the `feedback_mcp` data schema now (before production decisions are recorded) so it matches what Phase 4 will need
  - Build risk scorer (zone-based, rule-based — does not require feedback data)
  - Add basic path suggestion: "based on routing tables, this subnet likely routes via [device]" — framed as a hint, not authoritative. Uses existing `get_routing_table` data.
- [ ] **Phase 4** — Recommendation engine (built on real feedback data from Phase 3)
  - Object reuse vs. create-new suggestions
  - Precedent lookup via `get_similar_cases`
  - Write spec before building — define "recommendation" concretely: what inputs, what outputs, what confidence model
- [ ] **Phase 5** — mTLS hardening, Ansible change preview, Postgres migration, HA, authenticated engineer identity
