# 4tAnalyst Workstation Onboarding

One page to get a firewall engineer's laptop working. If you're deploying or maintaining the *server*, see `docs/installation.md` and `docs/engineer-workflow.md` §1 instead — this page is checkout/verify steps only.

You never install Python, credentials, or MCP server packages locally, and you never handle FortiManager/4THealth API keys — those live only on the central server (see `SECURITY.md`).

## 1. Get a slim checkout

A sparse checkout pulls down only the slash commands and the local report-rendering script — not the server packages, tests, or docs you don't need on a laptop:

```bash
git clone --filter=blob:none --sparse <repo-url> 4tAnalyst-workstation
cd 4tAnalyst-workstation
git sparse-checkout set .claude scripts
```

Your team access to this repo is **read-only**. If you spot a bug in a skill or a naming rule it enforces, report it to the FW engineering team (see `CONTRIBUTING.md`) rather than editing your local copy.

To pick up later updates (new/changed skills, render-script fixes):

```bash
git pull
```

## 2. Install Claude Code

Install from [claude.ai/code](https://claude.ai/code). You need an Anthropic subscription (Claude Max or API access) — confirm with IT that your account is provisioned first.

## 3. Request your bearer token from the admin

Each engineer gets their own bearer token scoped to the ADOMs they need. Contact the FW engineering team lead and ask for a **4tAnalyst bearer token**. Let them know which ADOMs you need access to (e.g., "OT-ADOM and GAS-ADOM" or "all ADOMs"). They will generate the token and send it to you over a secure channel.

The token is a random hex string (64 characters). Treat it as a password:
- Do not email it in plaintext or paste it into Teams/Slack without encryption
- Do not commit it to any file in the repo
- If you suspect it was exposed, contact the admin immediately to rotate it

You will put this token into the `mcp_servers.json` file in the next step.

> **Admins:** see the **Issuing engineer tokens** section in `SECURITY.md` for the provisioning procedure.

## 4. Point Claude Code at the central server

The server list lives at `.claude/mcp_servers.json`, inside the checkout. If the team has already committed the real hostname there, `git pull` is all you need.

If it still shows a placeholder (`.claude/mcp_servers.json.example`), copy it to `.claude/mcp_servers.json` and fill in the real hostname and token the admin gave you:

```json
{
  "mcpServers": {
    "4tanalyst": {
      "type": "http",
      "url": "https://<central-server>:8000/mcp",
      "headers": { "Authorization": "Bearer <your-token-here>" }
    }
  }
}
```

Replace `<central-server>` with the hostname the admin provides and `<your-token-here>` with the 64-character token from Step 3.

Use `https://`, not `http://` — plain HTTP is not acceptable for this data in a regulated environment (NERC CIP, HIPAA, PCI-DSS, etc.).

## 5. Verify

From inside `4tAnalyst-workstation`, start Claude Code and run:

```
/check-policy 10.0.0.1 10.0.0.2 tcp/443
```

A zone verdict (ALLOWED / BLOCKED / UNKNOWN) means you're done. A connection error means the server isn't reachable yet — see `docs/engineer-workflow.md` §4 (Troubleshooting) or ask the FW engineering team to confirm the hostname, token, and that the central server is running.

## What's next

Once connected, `docs/engineer-workflow.md` §2 walks through working an actual firewall request end-to-end with the six slash commands (`/analyze-request`, `/check-policy`, `/validate-rule`, `/generate-peer-review`, `/record-decision`, `/missing-info`).
