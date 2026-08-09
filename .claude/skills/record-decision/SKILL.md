---
name: record-decision
description: Record the outcome of a firewall change analysis or peer review to the feedback store for audit trail and future learning.
---

# Record Decision

## Purpose
Stores the outcome of a completed analysis or peer review. Builds an audit trail and lets the team review decisions over time. Also feeds the future recommendation engine with real approval/rejection patterns.

## Usage
`/record-decision`

Claude will prompt for the decision details. If `/analyze-request` or `/generate-peer-review` was already run in this conversation, most fields can be pre-populated.

## Workflow

### Step 1 — Collect decision details
Required fields:
- **Decision**: approved / rejected / deferred
- **Submitting engineer**: name
- **Reviewing engineer** (if peer review was done): name
- **Rejection reason** (if rejected): what was wrong
- **Deferral reason** (if deferred): what information is still needed
- **Change ticket / reference number** (optional): ServiceNow or CAB ticket ID

Pre-populate from conversation context if available:
- src/dst IPs, service, zone verdict
- Firewalls to be modified
- Risk level
- Governing rules
- Any validation failures that were flagged

### Step 2 — Store the record
Call `record_feedback` from the `feedback` MCP server with the collected details.

Format the payload as:
```json
{
  "event_type": "rule_decision",
  "decision": "approved | rejected | deferred",
  "submitted_by": "engineer name",
  "reviewed_by": "reviewer name or null",
  "request": {
    "src": ["..."],
    "dst": ["..."],
    "service": "...",
    "firewalls": ["..."],
    "business_justification": "..."
  },
  "analysis": {
    "zone_verdict": "ALLOWED | BLOCKED | UNKNOWN",
    "src_zones": ["..."],
    "dst_zones": ["..."],
    "risk_level": "low | medium | high | critical",
    "governing_rules": [...]
  },
  "outcome": {
    "reason": "...",
    "ticket_ref": "..."
  }
}
```

### Step 3 — Confirm
After storing, confirm to the engineer:

```
Decision recorded.
  Decision:   [approved | rejected | deferred]
  Reference:  [ticket ref if supplied]
  Stored at:  [timestamp]

[If approved]:  Change is ready for CAB submission.
[If rejected]:  Submitter should be notified of the reason and asked to revise.
[If deferred]:  Reopen when the outstanding information is available.
```

## Notes
- Record every decision — approvals and rejections both matter for the audit trail
- If a rejection was due to naming or logging violations, record that specifically so the pattern can inform future submissions
- The feedback store is append-only — decisions cannot be edited after recording
