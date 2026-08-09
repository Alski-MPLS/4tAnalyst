# Security

## Credential handling

**`credentials.yaml` is gitignored and must never be committed.** It contains API keys for FortiManager and the 4THealth zone policy system. Use `credentials.yaml.example` as a template.

If you accidentally commit credentials:
1. Immediately revoke and rotate the affected API keys in the respective systems
2. Remove the file from git history using `git filter-repo` or contact your GitHub admin
3. Audit access logs on the affected systems for unauthorized use

All API credentials are stored on the central MCP server only. Engineer workstations hold no credentials — they connect to the central server over HTTPS/SSE.

## Network access

The central MCP server should have:
- **Outbound only** to FortiManager and 4THealth management IPs on port 443 (and NetBrain when integration is ready)
- **Inbound** from engineer workstation subnets on port 8000 only (unified server, bearer-token auth; front with TLS — either a reverse proxy or the server's own direct-uvicorn TLS option, see `docs/tls-setup.md`)
- **No internet access** required

Engineer workstations need only outbound HTTPS to the central server. No direct firewall management API access is required or recommended.

## What this system can and cannot do

**Read-only throughout.** All MCP tools make read-only API calls. No tool can create, modify, or delete firewall rules, objects, or policies. This is enforced at the API layer — the service accounts used have read-only profiles.

**No execution.** 4tAnalyst produces recommendations and peer review packages. The Ansible push that implements changes is a separate, human-initiated process outside this system.

**No credentials on workstations.** Engineers never need and should never have direct API access to FortiManager. If an engineer asks for API keys "to test locally," direct them to use the central MCP server instead.

## Accuracy limitations and advisory status

All tool outputs — zone policy verdicts, rule search results, naming validations, approval chains, and peer review packages — are **advisory only**. They are research aids, not authoritative decisions.

- **Policy verdicts reflect intended segmentation policy**, not the live state of firewall rules. ALLOWED means the zone policy permits the traffic in principle; it does not mean a rule exists or that the traffic will actually pass.
- **Zone resolution depends on the 4THealth database being current.** An IP recently moved to a new subnet, or a subnet not yet registered in 4THealth, will return UNKNOWN. Treat UNKNOWN as BLOCKED pending manual verification — do not treat it as "no policy found, probably okay."
- **Engineers are accountable for all decisions.** The tool accelerates research; it does not replace professional judgment or peer review.
- **Peer review packages are drafts**, not completed reviews. No AI-generated document should be filed as an official change record or audit evidence without human review and explicit attestation by the reviewing engineer.

## Engineer identity in the audit log (current limitation)

The audit log records an `engineer_id` string provided by the engineer at time of decision. This is **not authenticated** — any string can be entered. For audit purposes in a regulated environment (NERC CIP, HIPAA, PCI-DSS, or your organization's own change-management standard), do not rely solely on the audit log for identity verification until authenticated identity (AD/Entra) is implemented.

Until then, cross-reference recorded decisions against ServiceNow ticket history and CAB records for audit evidence. Do not begin recording official change decisions until this limitation is understood and accepted by the compliance team.

**Separately, the unified server emits an access log** (stdout/journald, not the feedback_mcp SQLite audit log above): one INFO line per tool call with the tool name and the caller's token label (`server.tokens` label, or `"admin"` for the primary token) — never call arguments or the token itself. This is infrastructure-level access logging, not a substitute for the decision-level audit trail in `feedback_mcp`.

## Regulated-environment compliance posture

4tAnalyst is a research and documentation aid. It is **not a replacement for any step in your organization's documented change management process** — whether that process is governed by NERC CIP, HIPAA, PCI-DSS, SOX, or an internal policy. Before using 4tAnalyst outputs as part of an official change record:

1. Confirm with your compliance team that AI-assisted analysis tools are acceptable under your current documented procedures.
2. Ensure any filed documents are attested by a named human reviewer, not presented as AI-generated outputs.
3. Do not treat `review_requirements.yaml` approval chain values as authoritative until they have been validated and signed off by the compliance team.

## Sensitive data in this repository

This repository may be made public. A named reviewer must sign off on each item below before any merge to a public branch. Do not publish without completing this checklist.

**2026-07-25 remediation:** `credentials.yaml`, `policy_db.json`, and `fmg-test.md`'s pre-scrub content
were confirmed/purged from full git history via `git filter-repo` (path removal + literal-string
replacement), followed by a force-push. `standards_mcp/policy_db.json` and `standards_mcp/policy-data/`
(the source CSVs behind it) are now gitignored and untracked — this repo ships no real segmentation
data; generate your own locally with `python standards_mcp/build_policy_db.py` against your own CSV
exports. `docs/test-results/`, `.claude/worktrees/`, `.claude/settings.json` (hardcoded a personal
machine path), and `docs/superpowers/` (internal planning docs reusing lab IPs) were also untracked.
Real hostnames/IPs found in `todo.md`, `standards_mcp/naming.yaml`, `CLAUDE.md`, and `zone_mcp/*.py`
were replaced with placeholders repo-wide, including in history.

| File | Risk | Status |
|---|---|---|
| `credentials.yaml` | API keys | Never committed — confirmed via `git log --all --full-history -- credentials.yaml` |
| `todo.md` | Contained production VM/FortiManager IPs and hostnames | Scrubbed (2026-07-25), then removed from the public repo entirely (2026-08-08) |
| `standards_mcp/naming.yaml` | Internal zone abbreviations (OT, CIP-H, GAS-SCADA, etc.) reveal internal network segmentation vocabulary | **Still open** — terminology itself (not a leaked value) remains; review with security team before publishing |
| `standards_mcp/review_requirements.yaml` | Internal role names and approval chain structure | **Still open** — review with compliance team before publishing |
| `docs/architecture.md` | Describes internal topology, port assignments, and component roles | **Still open** — review for internal-specific detail |
| `highlevel-4tanalyst.md` | Full architecture description with OT/IT/CIP segmentation details | Removed from the public repo (2026-08-08) |
| `standards_mcp/policy_db.json`, `standards_mcp/policy-data/` | Real internal subnets, site names, and zone topology | Untracked, gitignored, and purged from git history (2026-07-25) |
| `fmg-test.md` | Pre-scrub version had real hosts/IPs at commit `d2a2015` | Purged from git history (2026-07-25) |

## Issuing engineer tokens

Engineers connect to the central MCP server using per-engineer bearer tokens scoped to one or more ADOMs. This section covers the admin workflow for creating and revoking those tokens.

### Generating a token

```bash
openssl rand -hex 32
```

This produces a 64-character hex string. Each engineer gets a unique token.

### Adding the token to credentials.yaml

Open `credentials.yaml` on the central server and add an entry under `server.tokens`:

```yaml
server:
  adom_restriction: true
  auth_token: "..."   # admin token — unchanged

  tokens:
    # Existing entries...
    - token: "a1b2c3d4..."        # 64-char hex from openssl rand -hex 32
      label: "firstname-lastname" # human-readable; appears in audit logs only
      adoms: ["OT-ADOM"]          # list the ADOMs this engineer needs
                                  # use ["*"] for full access (same as auth_token)
```

To restrict to multiple ADOMs: `adoms: ["OT-ADOM", "GAS-ADOM"]`.
To grant full access (e.g., a second admin or a tester): `adoms: ["*"]`.

After editing `credentials.yaml`, restart the unified server for the change to take effect:

```bash
systemctl restart 4tanalyst   # or however the server is managed at your site
```

### Sending the token to the engineer

Send the token over a secure channel — encrypted email, a privileged ticket in ServiceNow, or an internal secrets manager. Do not send it via unencrypted email, Teams/Slack DM (unless E2E encrypted), or document it in the firewall change ticket.

Tell the engineer:
- Their token value (64 hex chars)
- The central server hostname and port (e.g., `4tanalyst.internal.example.com:8000`)
- Which ADOMs they have access to, so they can verify
- To direct them to `docs/workstation-onboarding.md` if they need setup instructions

### Revoking a token

Remove the engineer's `tokens` entry from `credentials.yaml` and restart the server. The token is immediately invalid once the server reloads. No other action is required — the server carries no session state.

If you suspect a token was compromised (exposed in a chat log, committed to git, etc.):
1. Remove the entry from `credentials.yaml` immediately
2. Restart the server
3. Generate a new token and reissue to the engineer if their access should continue
4. Review the audit log (`feedback_mcp.get_audit_log`) for any unexpected activity under that engineer's label

### Disabling ADOM filtering entirely

If your deployment has a single team and all engineers need full access, set `adom_restriction: false` in `credentials.yaml`. Every recognized token (primary `auth_token` and all `tokens` entries) gets unrestricted access. Unrecognized tokens are still rejected with 401.

### Token rotation

There is no automatic expiry — tokens are valid until removed from `credentials.yaml`. Rotate on a schedule, not just on suspected exposure.

**Rotating the admin token (`server.auth_token`):**
1. Generate a new value: `openssl rand -hex 32`
2. Update `auth_token` in `credentials.yaml` (or the `FW_ANALYST_TOKEN` env var, which takes precedence if set — update it there instead, or in addition, depending on how the unit/container is configured)
3. Restart the unified server: `systemctl restart 4tanalyst` (or however it's managed at your site)
4. Distribute the new token to every holder over a secure channel (see "Sending the token to the engineer" above) — every consumer of the old admin token loses access the moment the server restarts

**Rotating a per-engineer token:**
1. Generate a new value: `openssl rand -hex 32`
2. Replace the `token` field on that engineer's entry under `server.tokens` in `credentials.yaml` — keep the `label` and `adoms` unchanged
3. Restart the server
4. Send the new token to the engineer over a secure channel; the old value stops working immediately on restart

**When to rotate:**
- **Immediately** on suspected exposure (committed to git, pasted in an unencrypted channel, screen-shared, laptop lost/stolen) — do not wait for a scheduled rotation
- **On team membership change** — rotate (or revoke, if the engineer is leaving) any per-engineer token when someone joins, leaves, or changes roles/ADOM scope
- **Periodically** as a baseline hygiene practice (e.g., annually, or per your org's credential-rotation policy), even with no known exposure

Both rotation paths require a server restart (tokens are read from `credentials.yaml`/env at startup, not reloaded live). The server carries no session state, so a restart is safe at any time — every connected engineer simply reconnects, no in-flight work is lost beyond the current request.

---

## Reporting vulnerabilities

**Do not open a public GitHub issue for a security vulnerability.** Report it privately through GitHub Security Advisories: go to this repository's **Security** tab, then **Report a vulnerability**. That opens a private channel visible only to the maintainers.

Please include:

- what the issue is and where in the code it lives,
- how to reproduce it (a failing test or a minimal request/fixture is ideal),
- the impact you believe it has.

You should get an acknowledgement within a week. Once a fix is ready, the advisory is published and credit given unless you would rather stay anonymous.

If you are running your own deployment of 4tAnalyst and discover a vulnerability that also implicates your live environment (e.g. a leaked credential, an exposed endpoint), report it to your own organization's security team *first* so they can contain the immediate exposure, then follow up with the advisory above so the fix reaches everyone else running this code. Do not include exploit details, real hostnames, IPs, or other internal network information in the public advisory thread or in any public issue.

## Threat model

4tAnalyst is a **read-only research and documentation aid** — see "What this system can and cannot do" above. No tool in this repo can create, modify, or delete a firewall rule, object, or policy; the service accounts it uses are read-only by design. Security-relevant bug classes here look like:

- **Auth/authorization defects** — anything that lets a request reach a tool without a valid bearer token, or lets a token access an ADOM it is not restricted to (see `fwanalyst_server/auth.py`, `_require_adom()` guards in `fortimanager_mcp/server.py`).
- **Credential or secret leakage** — a code path that logs, echoes, or otherwise exposes `credentials.yaml` contents, API keys, or bearer tokens (access logging is tool-name-only by design; see `context.py`/`_logged()`).
- **Unsound coverage or verdict decisions** in the deterministic planning core ([`fortigate-change-planner`](https://github.com/Alski-MPLS/fortigate-change-planner)) that could cause a real firewall change to be under-scoped or a blocked flow to be reported as allowed. That project has its own `SECURITY.md` and threat model for this class of issue.
- **Sanitization gaps** — error messages or logs from `fortimanager_mcp`/`zone_mcp` that leak internal hostnames, IPs, or raw upstream API responses to a caller who shouldn't see them.

Report issues in any of these categories the same way as above, whether they live in this repo or in `fortigate-change-planner`.
