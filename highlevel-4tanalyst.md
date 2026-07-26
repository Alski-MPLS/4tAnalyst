# 4tAnalyst: High-Level Overview

> **Last updated: 2026-07-07.** This document reflects the current state of the system as of the 2026-07-05 hardening session. The original vision document (multi-server SSE architecture) has been superseded by what was actually built. See `docs/architecture.md` for the technical deep-dive and `todo.md` for the full session history.

---

## Problem Statement

Firewall engineers spend ~40% of their time on rule request processing — parsing incoming requests, determining affected firewalls, researching existing policies, validating against standards, and coordinating peer review. The goal is to reduce this to research-only judgment calls, with AI handling the repetitive analysis and documentation.

---

## What Was Built

4tAnalyst is a Claude Code–based assistant that automates firewall rule request analysis for an energy utility. It exposes MCP tools so Claude Code can validate requests against company network segmentation policy, naming conventions, and approval workflows — eliminating the need for engineers to manually check policy matrices and route requests.

**Core design principle: the LLM orchestrates, code computes.** All correctness-critical analysis (rule coverage, object reuse, insertion point, CLI generation) lives in the deterministic `planner/` package — pure Python, pytest-covered, no LLM anywhere in the decision path. Claude Code is the conversational front end: it collects the request, calls `plan_change`, and presents the result verbatim.

The system targets Fortinet (FortiManager/FortiGate) exclusively. A NetBrain integration is planned for automated path discovery when API access becomes available.

---

## Architecture

```
Engineer Laptop                           Engineer terminal (no LLM path)
  Claude Code                               python -m planner
      │                                         │
      │ MCP streamable-HTTP + bearer token      │
      ▼ (port 8000, path /mcp)                  │
fwanalyst_server (single process) ──────────────┤
  ├── plan_change ─────────▶ planner/  ◀────────┘
  │                            ├──▶ 4THealth zone policy API
  │                            ├──▶ FortiManager JSON-RPC (7.4/7.6)
  │                            └──▶ standards YAML + render_report
  ├── standards tools   ──▶ naming.yaml, review_requirements.yaml
  ├── fortimanager tools ──▶ FortiManager API (read-only)
  ├── feedback tools     ──▶ SQLite (decisions + audit trail)
  ├── intake tools       ──▶ local .xlsx parser
  └── zone tools         ──▶ 4THealth zone policy API
```

One authenticated endpoint (port 8000, static bearer token, fail-closed) replaces the original five unauthenticated SSE ports. All API credentials live only on the central server. Engineers never connect directly to FortiManager.

The planner also runs as a standalone CLI (`python -m planner --src ... --dst ... --service ... --firewall DEVICE:ADOM`) with no LLM in the path — important in a regulated environment (NERC CIP, HIPAA, PCI-DSS, etc.) where the AI inference approval may come later than the deterministic tool itself.

---

## The Deterministic Planner (built 2026-07-04, hardened 2026-07-05)

`plan_change(src, dst, service, firewalls, justification, ticket_id)` accepts multi-value inputs (comma-separated strings or lists) and produces **one consolidated policy per firewall** covering every combination. What it computes, in tested code:

1. **Zone verdict** — live 4THealth query per src×dst×service combination. IPs 4THealth cannot resolve default to the catch-all **Internet** zone (with a note) and the verdict is re-derived from the live policy table — Internet zone is always critical risk. Any UNKNOWN combination makes the whole request UNKNOWN. Mixed ALLOWED+BLOCKED verdicts raise an explicit error: the engineer must split the request, not paper over it with one rule.

2. **Existing-rule coverage** — set-semantics matching against every policy package on each named device (`fortimanager_mcp/matching.py`): service objects resolve to numeric proto/port ranges (so "80" cannot match `TCP_8080`), address groups recurse with cycle guards, negate/schedule/disabled status honoured, and coverage judged only for rules scoped to the flow's actual interface pair (a broad LAN→WAN rule never "covers" an east-west flow). "Already covered" requires every src×dst pair fully covered. Package fetch failures mark the snapshot **degraded** — a degraded device is never reported as "already covered."

3. **Object reuse and grouping** — finds existing address/service objects before creating new ones. Sides with more than 3 members automatically get a dedicated address group (`GRP_<ticket>_SRC/DST`); a named group can also be forced via `src_group`/`dst_group`.

4. **Insertion point** — first-match shadowing analysis places the new rule before the first enabled policy that would otherwise match any of the traffic, with `shadowed_by`/`would_shadow` reported.

5. **Option B (group-append alternative)** — when a near-miss enabled rule would cover the flow if missing endpoints were appended to an address group it references, the plan offers that smaller change as an alternative — always with the ADOM-wide blast radius (every other rule referencing the group, directly or via nesting), never for negated sides. Engineer chooses Option A (new policy) or Option B, never both.

6. **Standards** — risk level, logging profile, approval chain. Previously prose in SKILL.md; now unit-tested code.

7. **Output** — exact `scripts/render_report.py` payload → `report.html` + `implementation.conf` under `output/<ticket-id>/`, ready to attach to the change ticket.

Two runs on the same inputs produce the same plan — auditable behaviour for a regulated environment.

---

## Phase Status

| Phase | Scope | Status |
|---|---|---|
| 1 | Standards MCP — zone matrix, naming, review requirements | **Complete** |
| 2 | FortiManager MCP, IP-to-zone mapper (zone_mcp / 4THealth) | **Complete** |
| 3 (revised) | Deterministic planner + unified server + multi-value consolidation + Option B + Internet catch-all + interface-scoped coverage *(delivered early)* | **Complete** |
| 3 (remaining) | Full team deployment, feedback collection (4–8 weeks real data), risk scorer; NetBrain topology integration (pending API access) | **Planned** |
| 4 | Recommendation engine (built on feedback data), object reuse suggestions, precedent lookup | **Planned** |
| 5 | mTLS hardening, Ansible change preview, Postgres migration, HA, authenticated engineer identity | **Planned** |

### What shifted from the original plan

The original Phase 3 "Rule Recommendation Generator" was built ahead of schedule, but as a **deterministic package** rather than an LLM-generated recommendation. This is the correct architecture for a regulated environment — the correctness-critical path is tested code, not model output. The recommendation engine (Phase 4) will be built on top of real feedback data from Phase 3 deployment.

The multi-server SSE architecture (one port per MCP server) was replaced by a single authenticated server — one TLS termination point, one bearer token, one health check.

---

## Key Technology Decisions

| Concern | Decision | Rationale |
|---|---|---|
| Interface for engineers | Claude Code (existing install) | Zero new tooling; works on Windows 11 and Mac |
| Correctness-critical analysis | Deterministic `planner/` package, not LLM prose | Auditable, regression-tested, runs without an LLM |
| Server architecture | Single `fwanalyst_server` (port 8000, bearer auth) | One TLS termination, one token check; unauthenticated multi-port SSE was a compliance finding waiting to happen |
| Multi-value requests | One `plan_change` call → one consolidated policy | Engineers don't think in per-flow units; one rule should cover the full request |
| Unresolved IPs | Default to Internet catch-all zone (never silent UNKNOWN) | Enumerating all internet space as subnets is not viable; unmatched = Internet, critical risk |
| Mixed ALLOWED+BLOCKED verdicts | Refuse to consolidate — error, ask engineer to split | One rule cannot honour both; silent consolidation would create a compliance gap |
| Group-append alternative | Always show blast radius; never for negated sides | Editing a shared group changes every rule referencing it; the engineer must see the full scope before choosing |
| Fortinet only | FortiManager MCP | This deployment's environment uses FortiGate/FortiManager |
| Request intake | Local .xlsx parser + manual conversational entry | ServiceNow API not available |
| Zone/policy source of truth | 4THealth live API (via zone_mcp) | 4THealth has a built-in admin UI and API; eliminates TUFIN CSV exports |
| Feedback store | SQLite (Phase 1–3), Postgres (Phase 5) | Zero-ops for a small team; migrate when concurrency grows |
| Engineer workstation setup | Git sparse-checkout of this repo (`.claude` + `scripts` only) | Skills and `render_report.py` change in lockstep with server code — a separate repo would drift |

---

## What This Does NOT Do (intentionally)

- **Does not auto-push changes.** The Ansible push remains engineer-controlled on the Monday/Thursday schedule. The system pre-stages, not executes.
- **Does not replace peer review.** It generates the peer review package. The second engineer still approves.
- **Does not access production firewalls directly.** All firewall queries go through the FortiManager management API — not device CLIs.
- **Does not store firewall credentials on engineer laptops.** Credentials live only on the central MCP server.
- **Does not integrate with ServiceNow.** No read-only API access is available. Intake is handled via the standard .xlsx request form or manual conversational entry.
- **Does not make LLM decisions about rule correctness.** The planner computes coverage, reuse, and insertion deterministically. The LLM presents the result — it does not derive it.

---

## Success Metrics

| Metric | Baseline | Target |
|---|---|---|
| Time per request (research phase) | ~40% of engineer time | Reduce by 60–70% |
| Time to peer-review-ready package | Hours | 15–30 minutes |
| Standards violations caught before change | Inconsistent | 100% automated pre-check |
| Recommendation acceptance rate | n/a (tracking starts at Phase 3 deployment) | Target >70% unmodified |
| Audit trail completeness | Manual/ad-hoc | 100% of requests |
| Deterministic plan reproducibility | n/a | Two runs on same inputs → same output |

---

## Risks and Current Status

| Risk | Mitigation | Status |
|---|---|---|
| Engineers distrust AI recommendations | Transparent reasoning on every recommendation; deterministic planner output is verifiable; easy override | Addressed by planner architecture — engineers see exactly what the code computed |
| Incorrect coverage determination (duplicate/shadowed rules) | Set-semantics matching (not substring), interface-scoped coverage, degraded-flag prevents false "already covered" | **Fixed 2026-07-04/05** |
| LLM uses stale standards path (`standards_mcp.check_traffic`) instead of live zone verdict | CLAUDE.md documents the rule: use `zone_mcp` for verdicts; `standards_mcp` for naming/logging only | Open — `standards_mcp.check_traffic` still exists; relies on engineer instruction discipline until migrated |
| API access to FortiManager is restricted or unstable | Primary/secondary failover, typed degradation, retries | FortiManager auth model confirmed (REST API Administrator, Bearer header); prod hosts not yet tested |
| Regulated/sensitive data leaves internal network via AI inference | MCP-as-boundary mitigation (ticket number in, zone names out — Phase 3); interim: engineers enter zone names not raw IPs for sensitive-zone requests | **Interim guidance active**; mitigation not yet built |
| Transport is plain HTTP | Bearer auth now enforced on port 8000; TLS termination (nginx) required before production | **Blocking** — TLS is the remaining infrastructure gap |
| Spreadsheet template varies between requesters | Parser matches tab names and column headers flexibly; missing fields flagged rather than failing silently | Handled |
| Central server becomes a single point of failure | HA/redundancy in Phase 5; read-only operations so degraded mode = engineers work manually (same as today) | Phase 5 item |
