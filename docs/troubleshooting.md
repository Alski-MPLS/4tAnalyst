# Troubleshooting

## MCP server not reachable

**Symptom:** Claude Code shows "MCP server unavailable" or the slash commands return connection errors.

**Check:**
1. Verify the central server is running: `ps aux | grep fwanalyst_server` — one process
2. Verify the port is listening: `ss -tlnp | grep 800`
3. From your workstation, test the connection:
   ```
   curl -X POST http://<server-ip>:8000/mcp   # expect HTTP 401 (auth enforced)
   ```
   A healthy server returns `401 Unauthorized` without a token (that's the auth wrapper working). A refused connection means the server isn't up. A timeout means a network/firewall issue between your workstation and the server.
4. Check that `.claude/mcp_servers.json` has the correct URL and a current bearer token

---

## Zone policy returns UNKNOWN for a known IP

**Symptom:** `/check-policy` returns `verdict: UNKNOWN` and empty `src_zones` or `dst_zones` for an IP you know is on the internal network.

**Causes and fixes:**

1. **IP is not in any zone's subnet list** — The most common cause. Log in to the 4THealth admin UI and verify the IP's subnet is defined under the correct zone. If it's missing, add it.

2. **Wrong IP entered** — Double-check the IP against the actual device. NAT can cause confusion — use the pre-NAT (internal) IP, not the translated address.

3. **IP is genuinely outside managed space** — Some segments (e.g., vendor-managed OT equipment) may not be in the zone DB. If the IP is legitimate and should be zoned, request it be added to 4THealth.

Note the difference between the two paths: `/check-policy` (direct 4THealth query) reports unresolved IPs as UNKNOWN. The full `/analyze-request` planner instead defaults unresolved IPs to the catch-all **Internet** zone, re-derives the verdict from the live policy table, and classifies the flow critical risk — the report notes when this happened. If you see "treated as the catch-all 'Internet' zone" for an IP you know is internal, fix the 4THealth subnet registration and re-run instead of implementing an Internet-zone rule.

---

## Planner refuses a multi-value request ("split the request")

**Symptom:** `/analyze-request` or `python -m planner` errors with:
```
[request] Zone policy gives mixed verdicts — ALLOWED for ... but BLOCKED for ...
```

**This is intentional, not a failure.** When a consolidated request (multiple sources, destinations, or services) contains some combinations that zone policy allows and others it blocks, a single firewall rule cannot honour both. Split the request into one per verdict — the allowed portion proceeds normally, the blocked portion becomes an exception request — and re-run each separately.

---

## FortiManager queries failing

**Symptom:** FortiManager tools return errors.

**Check:**

1. **Login fail (`-22`) when the server starts up:**
   `fortimanager_mcp` authenticates using a Bearer API key, not a session
   login — see [Configuration — FortiManager](configuration.md#fortimanager)
   for the difference. `-22` is a generic error FortiManager returns for
   several distinct causes, so check all of these on the account's config
   page (System Settings → Admin → Administrators):
   - `api_key` in `credentials.yaml` isn't from a **REST API Administrator**
     account (a regular admin's password will never work here)
   - **JSON API Access** is not enabled on the account
   - **Trusted Hosts** doesn't include the IP the MCP server actually calls
     from (same-subnet traffic egresses as the calling host's real interface
     IP, not any container-internal IP)

2. **No permission for the resource (`-11`):**
   The API key authenticated, but the specific endpoint or ADOM isn't
   permitted for this admin's profile/scope. Check **Admin Profile** and
   **Administrative Domain** on the account, not the key itself.

3. **Permission denied (`-10`):**
   The API account doesn't have access to that ADOM. The account needs read access to all ADOMs it will be queried against.

4. **Object not found (`-9`):**
   The device or policy package name doesn't exist in that ADOM. Use `get_adoms()` and `get_devices(adom)` to verify exact names before passing them to other tools.

5. **Connection refused:**
   Check the FortiManager IP and port in `credentials.yaml`. FortiManager JSON-RPC runs on port 443 at `/jsonrpc`.

---

## Standards / naming returns placeholder values

**Symptom:** `/validate-rule` shows naming patterns like `[prefix]-[zone]-[description]` instead of real patterns.

**Fix:** `standards_mcp/naming.yaml` and `standards_mcp/review_requirements.yaml` still have placeholder values. The team needs to populate these with actual conventions. See [Configuration — Standards files](configuration.md#standards-files-team-maintained) for what to fill in.

---

## `credentials.yaml not found` error

**Symptom:**
```
FileNotFoundError: credentials.yaml not found at /opt/fw-analyst/credentials.yaml
```

**Fix:** Copy the example file and fill it in:
```bash
cp credentials.yaml.example credentials.yaml
nano credentials.yaml
```

If the file is in a non-standard location, set the environment variable:
```bash
export CREDENTIALS_FILE=/path/to/your/credentials.yaml
```

---

## 4THealth API returns 503

**Symptom:**
```
ZonePolicyError: 4THealth API unavailable: External API is disabled
```
or
```
ZonePolicyError: 4THealth API unavailable: policy_db.json not found
```

**Fix:**
- `External API is disabled` — the 4THealth admin needs to enable the external API feature in the application settings.
- `policy_db.json not found` — the 4THealth application hasn't had its zone database initialized yet. Contact the 4THealth administrator.

---

## Slow response times

**Symptom:** Commands take more than 30 seconds to return.

**Check:**
1. FortiManager queries can be slow if the policy package is very large (thousands of rules). This is expected on first query — subsequent calls to the same package are faster.
2. If `check_ip_traffic` is slow, the 4THealth server may be under load. The default timeout is 30 seconds (configurable in `credentials.yaml` under `zone_policy.timeout`).
3. If the MCP server itself is slow to respond to Claude Code, check CPU/memory on the central server — each concurrent engineer session adds load.

---

## Getting more detail from the servers

To see server-level logs, run a server manually with logging enabled:

```bash
PYTHONUNBUFFERED=1 uv run python -m zone_mcp.server 2>&1 | tee zone_mcp.log
```

For SSE servers, add Python logging configuration:

```bash
PYTHONUNBUFFERED=1 LOG_LEVEL=DEBUG MCP_TRANSPORT=http FASTMCP_PORT=8000 FW_ANALYST_TOKEN=<token> uv run python -m fwanalyst_server
```
