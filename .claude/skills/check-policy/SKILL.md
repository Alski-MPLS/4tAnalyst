---
name: check-policy
description: Quick zone policy verdict for a src→dst flow. Use when you just need to know if traffic is ALLOWED/BLOCKED/UNKNOWN without a full request analysis.
---

# Check Zone Policy

## Purpose
Fast single-call verdict for a traffic flow. No firewall queries, no approval chain — just zone resolution and policy verdict. Good for answering "is this even allowed by policy?" before doing a full analysis.

## Usage
`/check-policy <src> <dst> [service]`

Examples:
- `/check-policy 10.91.0.5 10.1.0.10 443`
- `/check-policy 10.91.0.0/24 10.50.0.0/24 ssh`
- `/check-policy 10.91.0.5 10.1.0.10` (no service — checks zone-level access only)

## Workflow

1. Parse src, dst, and optional service from the user's input
2. Call `check_ip_traffic(src_ip, dst_ip, service)` from the `zone_policy` MCP server
3. Present the result clearly:

```
Zone Policy Check
─────────────────
Source:      <src_ip>  →  zones: [<src_zones>]
Destination: <dst_ip>  →  zones: [<dst_zones>]
Service:     <service or "any">

Verdict: ALLOWED | BLOCKED | UNKNOWN

Governing rules:
  [policy_set] [from_zone] → [to_zone]: [access_type]

[If BLOCKED]:  Traffic is explicitly denied. An exception requires security team approval.
[If UNKNOWN]:  One or both IPs are unclassified — no zone matched. Treat as denied.
               Verify the IPs are correct; the zone DB may need updating if they are.
[If ALLOWED]:  Traffic is permitted by policy. Use /analyze-request for full request analysis.
```

## Notes
- src and dst can be CIDRs — the API resolves them to zones
- Multiple flows: if the user supplies a list, call `query_zone_policy` with the full list instead of `check_ip_traffic`; present results as a table
- This does NOT check actual firewall rules — only the segmentation policy. Use `/analyze-request` to check whether a rule already exists on a specific firewall
