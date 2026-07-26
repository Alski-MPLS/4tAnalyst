# FortiManager MCP — Remote Server Test Guide

## What to copy

You only need these files. Place them in the same directory structure on the remote server:

```
/your/path/
├── credentials.yaml
└── fortimanager_mcp/
    ├── __init__.py
    ├── client.py
    ├── query.py
    ├── server.py
    └── pyproject.toml
```

`credentials.yaml` must sit one level above the `fortimanager_mcp/` directory. If you'd rather
put it elsewhere, set the `CREDENTIALS_FILE` environment variable to its full path.

---

## credentials.yaml (fortimanager block)

```yaml
fortimanager:
  hosts:
    - host: "fmg-site-a.internal.example.com"  # or IP
      api_key: "CHANGEME"
    - host: "fmg-site-b.internal.example.com"  # or IP
      api_key: "CHANGEME"
  port: 443
  verify_ssl: false          # self-signed certs in lab
  version: "7.4"
  session_timeout: 300
```

---

## Setup on the remote server

```bash
# Install uv if not present
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install the package (run from the directory containing fortimanager_mcp/)
uv pip install -e fortimanager_mcp/
```

---

## Test sequence

Run each step in order. Each one depends on output from the previous.

### Step 1 — List ADOMs

Confirm connectivity and get ADOM names.

```bash
uv run python -c "
from fortimanager_mcp import query
from fortimanager_mcp.server import _fortimanager_client

with _fortimanager_client() as c:
    print(query.list_adoms(c))
"
```

Expected: a list of dicts with `name`, `status`, `os_type`, `desc`.

---

### Step 2 — List devices in an ADOM

Replace `<adom>` with a name from step 1.

```bash
uv run python -c "
from fortimanager_mcp import query
from fortimanager_mcp.server import _fortimanager_client

with _fortimanager_client() as c:
    print(query.list_devices(c, '<adom>'))
"
```

Expected: list of FortiGate devices with `name`, `ip`, firmware version, HA mode, connection status.

---

### Step 3 — Search address objects by IP

Replace `<adom>` with a name from step 1. Tests both per-ADOM and global object lookup.

```bash
uv run python -c "
from fortimanager_mcp import query
from fortimanager_mcp.server import _fortimanager_client

with _fortimanager_client() as c:
    print(query.search_address_objects(c, '<adom>', '10.1.1.1'))
"
```

Expected: list of address objects whose subnet contains `10.1.1.1`, with `name`, `subnet`, `adom_scope`.

---

### Step 4 — Get interface map for a device

Replace `<adom>` and `<device>` with values from steps 1–2.

```bash
uv run python -c "
from fortimanager_mcp import query
from fortimanager_mcp.server import _fortimanager_client

with _fortimanager_client() as c:
    print(query.get_interface_map(c, '<adom>', '<device>'))
"
```

Expected: dict with `firmware`, `ha_mode`, and a list of interfaces with IP, zone, VLAN, and status.

---

### Step 5 — Search policies matching a traffic flow

Replace `<adom>` and `<device>` with values from steps 1–2. Use real IPs from your environment.

```bash
uv run python -c "
from fortimanager_mcp import query
from fortimanager_mcp.server import _fortimanager_client

with _fortimanager_client() as c:
    print(query.search_policies(c, '<adom>', '<device>', src_ip='10.1.1.1', dst_ip='10.2.2.2'))
"
```

Expected: list of matching policies with `source`, `destination`, `service`, `action` (accept/deny), `log`.

---

### Step 6 — Get routing table

```bash
uv run python -c "
from fortimanager_mcp import query
from fortimanager_mcp.server import _fortimanager_client

with _fortimanager_client() as c:
    print(query.get_routing_table(c, '<adom>', '<device>'))
"
```

Expected: list of static routes sorted by sequence number, each with `dst`, `gateway`, `device` (interface), `distance`.

---

## Common errors

| Error | Likely cause | Fix |
|-------|-------------|-----|
| `ConnectionError` / `SSLError` | Wrong host or port | Check `credentials.yaml` hosts; set `verify_ssl: false` for self-signed certs |
| `FortiManagerAPIError: -11` | Authentication failed | API key is wrong or not a REST API key (must be generated under System > Admin > Administrators, type "API User") |
| `FortiManagerAPIError: -9` | Object not found | ADOM name or device name is wrong — re-run step 1/2 to get exact names |
| Empty `[]` from `search_policies` | No package installed on that device, or IPs don't match any object | Try without src/dst first to list all policies |
