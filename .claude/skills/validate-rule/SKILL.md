---
name: validate-rule
description: Validate a proposed or existing firewall rule against naming conventions, logging requirements, and zone policy. Use before submitting a rule for peer review or CAB approval.
---

# Validate Firewall Rule

## Purpose
Pre-submission validation of a firewall rule. Checks naming conventions, logging settings, and zone policy compliance. Designed to catch issues before the rule goes to peer review or CAB.

## Usage
`/validate-rule`

Claude will prompt for the rule details interactively.

## Workflow

### Step 1 — Collect rule details
Ask for:
- **Platform**: fortigate
- **Rule name** (as it will appear in the firewall)
- **Source objects**: names and IPs/CIDRs
- **Destination objects**: names and IPs/CIDRs
- **Service objects**: names and ports
- **Action**: allow or deny
- **Logging**: what logging is configured (log start, log end, alert on match)
- **Firewalls this rule applies to**

### Step 2 — Zone policy check
For each src/dst IP combination, call `check_ip_traffic(src_ip, dst_ip, service)`.

Flag if:
- Verdict is BLOCKED — the rule would be creating an exception to policy; note that security approval is required
- Verdict is UNKNOWN — one or both IPs are unclassified; the zone DB may need to be updated
- Verdict is ALLOWED — rule is consistent with policy (expected for routine requests)

### Step 3 — Naming convention validation
For each object in the rule call `get_naming_convention(object_type, platform)` and compare the proposed name against the pattern.

Check:
- Host objects (src/dst)
- Network objects (if CIDRs)
- Service objects (if non-standard ports)
- Rule/policy name itself

For each object: PASS / FAIL with the correct pattern shown when it fails.

### Step 4 — Logging validation
Determine the rule category (allow_internet_outbound, allow_internal, block_all, etc.) based on the zones and action, then call `get_required_log_settings(rule_type)`.

Compare required settings against what the engineer supplied. Flag any gaps.

### Step 5 — Output

```
## Rule Validation Report

Rule: [rule name]
Platform: fortigate
Firewalls: [list]

### Zone Policy
[For each src/dst pair]
  [src] → [dst] ([service]): ALLOWED | BLOCKED | UNKNOWN
  [Note if this is a policy exception and requires security sign-off]

### Naming Conventions
[For each object]
  [object name]: PASS | FAIL
  [If FAIL]: Expected pattern: [pattern], e.g. [example]

### Logging Settings
Required for [rule_type]:
  Log start:      required=[yes/no]  configured=[yes/no]  [PASS|FAIL]
  Log end:        required=[yes/no]  configured=[yes/no]  [PASS|FAIL]
  Alert on match: required=[yes/no]  configured=[yes/no]  [PASS|FAIL]
  SIEM forward:   required=[yes/no]  configured=[yes/no]  [PASS|FAIL]

### Overall
READY FOR REVIEW | ISSUES FOUND — [N] items must be fixed before submission
[Bulleted list of required fixes]
```

## Notes
- A rule that violates naming or logging standards should not be submitted for peer review until fixed
- A rule that contradicts zone policy (verdict BLOCKED) requires an explicit exception approval — note this prominently
- All rules are validated against FortiGate naming conventions
