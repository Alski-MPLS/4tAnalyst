---
name: generate-peer-review
description: Generate a structured peer review package for a firewall change — suitable for the second engineer to sign off on before CAB submission.
---

# Generate Peer Review Package

## Purpose
Produces a ready-to-send peer review document for a firewall change. The reviewing engineer should be able to read this and make a go/no-go decision without needing to query any systems themselves.

## Usage
`/generate-peer-review`

Claude will prompt for details if not already available from a prior `/analyze-request` in the same conversation.

## Workflow

### Step 1 — Gather or reuse context
If `/analyze-request` was already run in this conversation, reuse those results.
Otherwise ask for:
- Source IPs/CIDRs and destination IPs/CIDRs
- Service(s)
- Business justification
- Firewalls to be modified
- Proposed rule/object names
- Submitting engineer name

Then run the same lookups as `/analyze-request` (zone verdict, existing rules, naming, logging, approval requirements).

### Step 2 — Produce the peer review document

```
═══════════════════════════════════════════════════════
FIREWALL CHANGE PEER REVIEW
═══════════════════════════════════════════════════════
Submitted by : [engineer name]
Date         : [today's date]
Risk level   : [low | medium | high | critical]

───────────────────────────────────────────────────────
CHANGE DESCRIPTION
───────────────────────────────────────────────────────
[Plain-English description of what this change does]

Firewalls affected : [list]
Platform           : FortiGate (FortiManager-managed)

───────────────────────────────────────────────────────
TRAFFIC FLOWS
───────────────────────────────────────────────────────
[Table: Source | Destination | Service | Zone Verdict]

───────────────────────────────────────────────────────
ZONE POLICY ASSESSMENT
───────────────────────────────────────────────────────
[For each flow: src zones, dst zones, verdict, governing rules]
[If any flow is BLOCKED: flag as POLICY EXCEPTION — explicit callout]
[If any IP is UNKNOWN: flag as UNCLASSIFIED IP — must be resolved before approval]

───────────────────────────────────────────────────────
EXISTING RULES (pre-change state)
───────────────────────────────────────────────────────
[For each firewall: any existing rules that overlap with this request]
[None found / rule name + action if found]

───────────────────────────────────────────────────────
PROPOSED OBJECTS AND RULES
───────────────────────────────────────────────────────
[List each object to be created: name, type, value]
[List the rule to be created: name, src, dst, service, action, logging]
[Naming convention: PASS / FAIL per object]
[Logging settings: PASS / FAIL]

───────────────────────────────────────────────────────
APPROVAL REQUIREMENTS
───────────────────────────────────────────────────────
Required approvers : [list of roles]
Security review    : [required | not required]
Change window      : [when]
SLA                : [hours]

───────────────────────────────────────────────────────
REVIEWER CHECKLIST
───────────────────────────────────────────────────────
The peer reviewer must confirm each item:

[ ] Traffic flows are consistent with stated business justification
[ ] Zone policy verdict is correct for the intended zones
[ ] No existing rule already covers this traffic (no duplicate)
[ ] All object names follow naming conventions
[ ] Logging settings meet requirements
[ ] Correct firewalls are listed for this traffic path
[ ] Risk level classification is appropriate
[ ] Approval chain is correct for this risk level

[ ] APPROVED for CAB submission
[ ] REJECTED — see comments below

Reviewer signature: _______________________  Date: ____________
Comments:

═══════════════════════════════════════════════════════
```

## Notes
- The peer reviewer is a second engineer, not the original submitter
- If any BLOCKED verdicts exist, the peer reviewer cannot approve — security team must sign off first
- If naming or logging validation failed, the submitter must fix those items before the peer reviewer signs
- Output the document as plain text suitable for pasting into an email or ticket
