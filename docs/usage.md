# Usage

All engineer interaction happens through Claude Code slash commands. Open the `4tAnalyst` directory (or any directory with the `.claude/` folder) in Claude Code and use the commands below.

---

## Slash commands

### `/analyze-request` — Full request analysis

The primary workflow command. Takes a firewall change request and produces a complete structured analysis covering zone policy, existing rules on the named firewalls, naming/logging compliance, and required approvals.

**What you need to have ready:**
- Source IP(s) or CIDR(s) — multiple values are fine; they go into ONE consolidated rule
- Destination IP(s) or CIDR(s) — same
- Service(s) (port number, port name, or proto/port — e.g. `443`, `ssh`, `tcp/8443`; multiple allowed)
- Business justification
- **The names of the firewalls that need to be modified** — 4tAnalyst does not auto-discover the path; the submitting engineer is expected to know which devices are in the traffic path
- Ticket ID (optional) — if you have one, the generated report and CLI config are saved under it; otherwise they're saved under a timestamped folder
- Optionally, a name for a source or destination address group — sides with more than 3 members are grouped automatically (`GRP_<ticket>_SRC/DST`); naming a group forces grouping at any size

**Example:**

```
/analyze-request

Source:      10.91.0.15, 10.91.0.16
Destination: 10.50.0.22
Service:     443, tcp/22
Firewalls:   SITE01-FW01, COLO-FW02
Justification: SCADA historians need to push data to the PI server in the IT DMZ
```

**What comes back:**
- Zone resolution for every IP and a policy verdict for every source×destination×service combination. IPs that don't resolve to a named zone are treated as the catch-all **Internet** zone (critical risk). If some combinations are ALLOWED and others BLOCKED, the analysis stops and tells you to split the request — one rule cannot honour both.
- Existing rule search results per named firewall — "already covered" only if *every* combination is covered by an enabled rule on the flow's actual interfaces
- One consolidated policy per firewall (Option A), plus — when a near-miss rule exists — an **Option B**: append the missing endpoint(s) to an address group that rule already references, always shown with the full list of other rules that group change would affect. Choose one option, never both.
- Naming convention check for all objects that would need to be created
- Logging requirements for the rule type
- Approval chain (approvers, change window, SLA) based on zone risk classification
- Two files saved under `output/<ticket-id>/` (or a timestamped folder if you didn't provide a ticket ID): `report.html`, a formatted version of the analysis, and `implementation.conf`, the exact FortiGate CLI commands to implement the change — or, if the verdict is BLOCKED, the exception language and placeholders needed to request approval. Attach both to the change ticket.

---

### `/check-policy` — Quick zone policy verdict

Fast verdict for a flow without running the full analysis. Use this when you just need to know if a traffic pattern is allowed by policy before committing to a full request.

```
/check-policy 10.91.0.5 10.1.0.10 443
/check-policy 10.91.0.0/24 10.50.0.0/24 ssh
/check-policy 10.91.0.5 10.1.0.10          # no service — zone-level check only
```

Returns: source zones, destination zones, verdict, and the governing rules.

---

### `/missing-info` — Triage an incomplete request

Paste in a request as-is and Claude will identify what's missing and draft a follow-up message to the submitter.

```
/missing-info

From ticket:
"Need port 443 opened from the plant historian to the PI server.
Please add the firewall rule ASAP."
```

What comes back:
- What was found vs. what's missing
- A plain-English follow-up message you can paste into the ticket

This is most useful when requests come in via email or a ticket without the standard form.

---

### `/validate-rule` — Pre-submission validation

Validates a proposed rule against naming conventions and logging requirements before it goes to peer review. Catches issues early.

Run `/validate-rule` and Claude will prompt for:
- Platform (fortigate)
- Rule name and object names (host, network, service objects)
- Action and logging settings
- Firewalls this rule applies to

Returns a pass/fail report per object and a clear list of items to fix before submission.

---

### `/generate-peer-review` — Peer review package

Produces a formatted peer review document ready to send to the second engineer. If `/analyze-request` was already run in the same conversation, most fields are pre-populated.

The output document includes:
- Change description
- Traffic flow table with zone verdicts
- Pre-change state (existing rules found or not found)
- Proposed objects and rules with naming validation results
- Approval requirements
- Reviewer checklist with signature line

Copy the output into your ticket, email, or Teams message.

---

### `/record-decision` — Record the outcome

Stores the approved/rejected/deferred decision in the feedback store for audit trail purposes. Run this at the end of every analysis — approved and rejected decisions both matter.

```
/record-decision
```

Claude will prompt for the decision, reviewer name, and optional ticket reference. It pre-populates request details from the current conversation context.

---

## Typical workflow

```
New request comes in
        │
        ▼
/missing-info          ← Is the request complete? Draft follow-up if not.
        │
        ▼
/analyze-request       ← Full analysis: zone verdict + existing rules + standards check
        │
   ┌────┴────┐
   │         │
ISSUES    LOOKS GOOD
   │         │
Fix them    ▼
        /validate-rule  ← Final pre-submission check on proposed object/rule names
                │
                ▼
        /generate-peer-review  ← Package for second-engineer sign-off
                │
                ▼
        Second engineer reviews
                │
                ▼
        /record-decision  ← Log the outcome (approved/rejected/deferred)
```

---

## Reading the zone verdict

Every analysis returns one of three verdicts:

| Verdict | Meaning | What to do |
|---|---|---|
| **ALLOWED** | Traffic is explicitly permitted by the segmentation policy | Proceed — check if an existing rule already covers it before creating a new one |
| **BLOCKED** | Traffic is explicitly denied by policy | A policy exception is required — security team must approve before the rule can be created |
| **UNKNOWN** | The zones resolved, but no policy covers the zone pair | Verify the IPs are correct; the 4THealth policy table may need updating. Treat as denied until resolved |

**Note:** ALLOWED means policy permits the traffic in principle. It does not mean a firewall rule already exists — use `/analyze-request` to check actual rules on the specific devices.

**Unresolved IPs:** `/check-policy` (a direct 4THealth query) returns UNKNOWN when an IP doesn't match any zone subnet. The full `/analyze-request` planner goes one step further: an unresolved IP is treated as the catch-all **Internet** zone, the verdict is re-derived from the live policy table, and the flow is classified critical risk with the internet-inbound/outbound logging profile. The report notes explicitly when this defaulting happened — verify the IP really is external before implementing.

---

## Firewall topology note

4tAnalyst does not automatically determine which firewalls sit in the traffic path. The submitting engineer is expected to know and state which devices need to be modified. This is a deliberate design choice — automatic path discovery requires a complete network topology that is not yet available across all sites.

When in doubt about which firewall handles a segment, use `/check-policy` to verify the zone first, then consult the network diagram or ask the network team before running `/analyze-request`.
