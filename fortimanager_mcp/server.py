"""
FortiManager MCP Server (7.4.x / 7.6.x compatible)

Exposes thirteen read-only tools to Claude:
  - get_system_status       : FortiManager version, hostname, serial, platform
  - get_ha_status           : FortiManager HA cluster status
  - get_adoms               : List all administrative domains
  - get_devices             : List FortiGates managed in an ADOM
  - search_devices          : Filter devices by name/platform/OS/connection status
  - search_policies         : Find policies matching a src/dst/service flow
  - get_address_object      : Look up an address object by name or IP
  - search_address_objects  : Find all objects containing a given IP
  - get_service_object      : Look up a service object by name or port
  - get_policy              : Full details for a specific policy ID
  - get_interface_map       : Interface-to-zone mapping for a device
  - get_routing_table       : Static routing table for a device
  - list_device_vdoms       : VDOMs configured on a device

Connection parameters (two hosts + API keys) are loaded from credentials.yaml
(gitignored).  Set CREDENTIALS_FILE env var to override the path.

Run locally (stdio):
  python -m fortimanager_mcp.server

Run as SSE server (production):
  mcp run fortimanager_mcp/server.py --transport sse --port 8002
"""

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from mcp.server.fastmcp import FastMCP

from fwanalyst_server.context import allowed_adoms_var
from fortimanager_mcp import client as _client_module
from fortimanager_mcp import query as _query

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Credentials loading
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent
_DEFAULT_CREDS = _REPO_ROOT / "credentials.yaml"


@lru_cache(maxsize=1)
def _load_creds() -> dict:
    creds_path = Path(os.getenv("CREDENTIALS_FILE", str(_DEFAULT_CREDS)))
    if not creds_path.exists():
        raise FileNotFoundError(
            f"credentials.yaml not found at {creds_path}. "
            "Copy credentials.yaml.example to credentials.yaml and fill in values."
        )
    with open(creds_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _fortimanager_client() -> _client_module.FortiManagerClient:
    """Build a connected FortiManagerClient from credentials.yaml."""
    cfg = _load_creds().get("fortimanager", {})

    raw_hosts = cfg.get("hosts", [])
    if not raw_hosts:
        raise ValueError(
            "fortimanager.hosts is empty in credentials.yaml. "
            "Add at least one entry with host and api_key."
        )

    hosts = []
    for entry in raw_hosts:
        h = entry.get("host", "").strip()
        k = entry.get("api_key", "").strip()
        if not h or not k:
            raise ValueError(
                f"Each fortimanager.hosts entry needs a non-empty host and api_key. "
                f"Bad entry: {entry}"
            )
        hosts.append((h, k))

    primary_host, primary_key = hosts[0]
    secondary_host, secondary_key = hosts[1] if len(hosts) > 1 else ("", "")

    c = _client_module.FortiManagerClient(
        primary_host=primary_host,
        primary_key=primary_key,
        secondary_host=secondary_host,
        secondary_key=secondary_key,
        port=int(cfg.get("port", 443)),
        verify_ssl=bool(cfg.get("verify_ssl", True)),
        version=str(cfg.get("version", "7.4")),
        session_timeout=int(cfg.get("session_timeout", 300)),
    )
    c.login()
    return c


def _require_adom(adom: str) -> dict | None:
    """Return error dict if the caller's token does not allow this ADOM, else None.

    Defaults to {"*"} (full access) when the ContextVar has no value — this
    preserves existing behaviour in stdio/dev mode where no auth middleware runs.
    """
    allowed = allowed_adoms_var.get({"*"})
    if "*" in allowed or adom in allowed:
        return None
    return {"error": f"ADOM '{adom}' is not in your allowed list."}


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="fortimanager",
    instructions=(
        "FortiManager read-only query server (7.4.x). "
        "Use get_adoms to discover administrative domains, get_devices to list FortiGates, "
        "search_policies to find rules matching a traffic flow, "
        "search_address_objects to find objects by IP (searches both per-ADOM and global ADOM), "
        "get_interface_map for zone assignments, and get_routing_table for path analysis. "
        "All operations are read-only — no changes are made to policy."
    ),
)


# ---------------------------------------------------------------------------
# Tool: get_system_status
# ---------------------------------------------------------------------------

@mcp.tool()
def get_system_status() -> dict[str, Any]:
    """
    Return FortiManager system status and version information.

    Returns version, hostname, serial number, and platform as normalised
    top-level fields, plus the full raw response under 'raw' (field names
    vary slightly by FortiManager version).
    """
    with _fortimanager_client() as c:
        return _query.get_system_status(c)


# ---------------------------------------------------------------------------
# Tool: get_ha_status
# ---------------------------------------------------------------------------

@mcp.tool()
def get_ha_status() -> dict[str, Any]:
    """
    Return FortiManager High Availability (HA) cluster status.

    Response shape (standalone vs cluster, member list) varies by topology,
    so the raw FortiManager response is returned as-is.
    """
    with _fortimanager_client() as c:
        return _query.get_ha_status(c)


# ---------------------------------------------------------------------------
# Tool: get_adoms
# ---------------------------------------------------------------------------

@mcp.tool()
def get_adoms() -> list[dict[str, Any]]:
    """
    List administrative domains (ADOMs) managed by FortiManager.

    Returns only ADOMs the caller's token is permitted to access.
    Returns a list of objects, each with:
      name      : str  — ADOM name
      status    : str  — operational status
      os_type   : str  — device OS family managed (FortiOS, etc.)
      desc      : str  — description
    """
    allowed = allowed_adoms_var.get({"*"})
    with _fortimanager_client() as c:
        adoms = _query.list_adoms(c)
    if "*" in allowed:
        return adoms
    return [a for a in adoms if a["name"] in allowed]


# ---------------------------------------------------------------------------
# Tool: get_devices
# ---------------------------------------------------------------------------

@mcp.tool()
def get_devices(adom: str) -> list[dict[str, Any]]:
    """
    List FortiGate devices managed within an ADOM.

    Parameters
    ----------
    adom : str
        ADOM name (from get_adoms).

    Returns device name, management IP, firmware version, HA mode,
    connection status, and database sync status.
    """
    if err := _require_adom(adom):
        return err
    with _fortimanager_client() as c:
        return _query.list_devices(c, adom)


# ---------------------------------------------------------------------------
# Tool: search_devices
# ---------------------------------------------------------------------------

@mcp.tool()
def search_devices(
    adom: str,
    name_filter: str = "",
    platform_filter: str = "",
    os_version_filter: str = "",
    connection_status: str = "",
) -> dict[str, Any]:
    """
    Filter FortiGate devices in an ADOM by name, platform, OS version,
    and/or connection status.

    Parameters
    ----------
    adom               : str  — ADOM name (from get_adoms)
    name_filter        : str  — Substring match on device name (optional)
    platform_filter    : str  — Substring match on platform (e.g. "FortiGate-VM") (optional)
    os_version_filter  : str  — Substring match on OS version (e.g. "7.4") (optional)
    connection_status  : str  — "up" or "down" (optional)

    All filters combine with AND. Filtering is client-side over get_devices —
    no additional FortiManager query is issued. Returns {count, devices}.
    """
    if err := _require_adom(adom):
        return err
    with _fortimanager_client() as c:
        return _query.search_devices(c, adom, name_filter, platform_filter,
                                      os_version_filter, connection_status)


# ---------------------------------------------------------------------------
# Tool: search_policies
# ---------------------------------------------------------------------------

@mcp.tool()
def search_policies(
    adom: str,
    device: str,
    src_ip: str = "",
    dst_ip: str = "",
    service: str = "",
) -> dict[str, Any]:
    """
    Find firewall policies that could match the given traffic parameters.

    Parameters
    ----------
    adom    : str  — ADOM name (from get_adoms)
    device  : str  — FortiGate device name (from get_devices)
    src_ip  : str  — Source IP or CIDR (optional, e.g. "10.1.2.3" or "10.1.0.0/16")
    dst_ip  : str  — Destination IP or CIDR (optional)
    service : str  — Port, proto/port, or service name (e.g. "443", "tcp/8443", "ssh")

    Matching is set-based: service objects are resolved to numeric proto/port
    ranges and address groups are recursed, so e.g. "80" never matches an
    object named TCP_8080. Searches all policy packages installed on the
    target device, including global-ADOM inherited objects.

    Returns a structured dict:
      policies          : matching policies sorted by package then policy ID,
                          each with full_cover / disabled / conditional_schedule /
                          unknown_refs flags in addition to the usual summary
      packages_searched : packages successfully queried
      packages_failed   : [{package, error}] for fetch failures
      degraded          : True if any package failed — an empty `policies`
                          list is then NOT proof that no rule exists
    """
    if err := _require_adom(adom):
        return err
    with _fortimanager_client() as c:
        return _query.search_policies(c, adom, device, src_ip, dst_ip, service)


# ---------------------------------------------------------------------------
# Tool: get_address_object
# ---------------------------------------------------------------------------

@mcp.tool()
def get_address_object(adom: str, name_or_ip: str) -> dict[str, Any]:
    """
    Look up an address object by name or IP address.

    Parameters
    ----------
    adom       : str  — ADOM name
    name_or_ip : str  — Exact object name (e.g. "H_10.1.2.3") or raw IP/CIDR.
                        Falls back to IP search if name lookup returns not-found.

    Returns the object's name, type, subnet, FQDN (if set), comment, and UUID.
    """
    if err := _require_adom(adom):
        return err
    with _fortimanager_client() as c:
        return _query.get_address_object(c, adom, name_or_ip)


# ---------------------------------------------------------------------------
# Tool: search_address_objects
# ---------------------------------------------------------------------------

@mcp.tool()
def search_address_objects(adom: str, ip: str) -> list[dict[str, Any]]:
    """
    Find all address objects that contain the given IP address or CIDR.

    Parameters
    ----------
    adom : str  — ADOM name
    ip   : str  — IP address (e.g. "10.1.2.3") or CIDR (e.g. "10.1.0.0/16")

    Searches both the per-ADOM object database and the global ADOM (for
    inherited objects). Use this before recommending creating a new object —
    an equivalent one may already exist.

    Returns a list of matching objects with their subnet, type, comment, and scope.
    """
    if err := _require_adom(adom):
        return err
    with _fortimanager_client() as c:
        return _query.search_address_objects(c, adom, ip)


# ---------------------------------------------------------------------------
# Tool: get_service_object
# ---------------------------------------------------------------------------

@mcp.tool()
def get_service_object(adom: str, name_or_port: str) -> dict[str, Any]:
    """
    Look up a service object by name or port number.

    Parameters
    ----------
    adom         : str  — ADOM name
    name_or_port : str  — Service name (e.g. "HTTPS") or port number (e.g. "443").
                          Falls back to substring search if exact name not found.

    Returns the service object's name, protocol, TCP/UDP port ranges, and comment.
    """
    if err := _require_adom(adom):
        return err
    with _fortimanager_client() as c:
        return _query.get_service_object(c, adom, name_or_port)


# ---------------------------------------------------------------------------
# Tool: get_policy
# ---------------------------------------------------------------------------

@mcp.tool()
def get_policy(adom: str, pkg: str, policy_id: int) -> dict[str, Any]:
    """
    Return full details for a specific firewall policy.

    Parameters
    ----------
    adom      : str  — ADOM name
    pkg       : str  — Policy package name
    policy_id : int  — Policy ID (from search_policies results)

    Returns all policy fields: source/destination interfaces and addresses,
    service, action, logging, NAT, and UUID.
    """
    if err := _require_adom(adom):
        return err
    with _fortimanager_client() as c:
        return _query.get_policy(c, adom, pkg, policy_id)


# ---------------------------------------------------------------------------
# Tool: get_interface_map
# ---------------------------------------------------------------------------

@mcp.tool()
def get_interface_map(adom: str, device: str) -> dict[str, Any]:
    """
    Return interface-to-zone assignments for a FortiGate device.

    Parameters
    ----------
    adom   : str  — ADOM name
    device : str  — FortiGate device name (from get_devices)

    Returns a list of interfaces with IP, zone membership, VLAN ID, alias,
    and admin status. Also returns device firmware version and HA mode.
    Use this to determine which zone an IP belongs to on a specific firewall.
    """
    if err := _require_adom(adom):
        return err
    with _fortimanager_client() as c:
        return _query.get_interface_map(c, adom, device)


# ---------------------------------------------------------------------------
# Tool: get_routing_table
# ---------------------------------------------------------------------------

@mcp.tool()
def get_routing_table(adom: str, device: str) -> list[dict[str, Any]]:
    """
    Return the static routing table configured on a FortiGate device.

    Parameters
    ----------
    adom   : str  — ADOM name
    device : str  — FortiGate device name (from get_devices)

    Returns static routes sorted by sequence number, each with destination
    prefix, gateway, egress interface, administrative distance, and priority.
    Use this for path analysis when determining which firewall is in the
    forwarding path between two IP addresses.
    """
    if err := _require_adom(adom):
        return err
    with _fortimanager_client() as c:
        return _query.get_routing_table(c, adom, device)


# ---------------------------------------------------------------------------
# Tool: list_device_vdoms
# ---------------------------------------------------------------------------

@mcp.tool()
def list_device_vdoms(adom: str, device: str) -> list[dict[str, Any]]:
    """
    List VDOMs (virtual domains) configured on a FortiGate device.

    Parameters
    ----------
    adom   : str  — ADOM name
    device : str  — FortiGate device name (from get_devices)

    Returns each VDOM's name, type, operating mode, and status. Most
    fw-analyst flows target "root" implicitly (see get_interface_map /
    get_routing_table), but multi-VDOM devices route traffic per-VDOM —
    use this to confirm which VDOM a flow actually traverses.
    """
    if err := _require_adom(adom):
        return err
    with _fortimanager_client() as c:
        return _query.list_device_vdoms(c, adom, device)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
