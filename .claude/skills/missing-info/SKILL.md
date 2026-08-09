---
name: missing-info
description: Identify what information is missing or ambiguous in a firewall change request before analysis can proceed. Use when a request comes in incomplete.
---

# Identify Missing Information

## Purpose
Triages an incoming firewall request and produces a clear list of what's missing before analysis can begin. Avoids wasting time on a partial analysis or sending vague follow-up emails.

## Usage
`/missing-info`

Paste or describe the change request. Claude will identify gaps.

## Workflow

### Step 1 — Parse what was provided
Extract whatever is present in the request:
- Source IPs or hostnames
- Destination IPs or hostnames
- Service(s) / port(s)
- Business justification
- Firewalls or network segments mentioned
- Requestor name / team

### Step 2 — Resolve what can be resolved silently
- If hostnames were given instead of IPs, note that IPs are needed (we cannot resolve DNS here)
- If a service name like "web traffic" was given without a port, flag it as ambiguous
- If "the firewall" is mentioned without a name, flag it

### Step 3 — Zone lookup for what we do have
If src and/or dst IPs were provided, call `find_zone_for_ip(ip)` for each one.
- If a zone is found: include it in the summary as "already resolved — no action needed"
- If no zone is found (UNKNOWN): flag it as an additional gap — the IP may be wrong or outside the organization's managed space

### Step 4 — Produce the missing-info summary

```
## Missing Information — Firewall Request Triage

What we have:
  [Bulleted list of what was provided and what it resolved to]
  Source:      [IP or "not provided"]  →  Zone: [zone name or "unclassified"]
  Destination: [IP or "not provided"]  →  Zone: [zone name or "unclassified"]
  Service:     [port/name or "not provided"]
  Firewalls:   [names or "not provided"]
  Justification: [present | missing]

What's needed before analysis can proceed:
  [ ] [Missing item 1 — specific question to ask the submitter]
  [ ] [Missing item 2]
  ...

Suggested follow-up message to submitter:
───────────────────────────────────────────
Hi [name if known],

To complete the analysis of your firewall change request, please provide
the following:

[Numbered list of specific questions — one sentence each, no jargon]

Thanks,
[sign-off]
───────────────────────────────────────────
```

## What always required (flag if any are missing)
- Specific source IP(s) or CIDR(s) — hostnames are not sufficient
- Specific destination IP(s) or CIDR(s)
- Specific port and protocol (not just "web traffic" or "database")
- The firewalls that need to be modified (engineer must know and state these)
- A business justification — which application, which team, what breaks without this rule

## Notes
- Do not start a full analysis if firewalls are missing — we cannot search rules without a specific device
- Do not assume a port from a service description — always ask for the explicit port if not given
- If the request is complete, say so and suggest running `/analyze-request`
