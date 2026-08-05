"""
High-level query helpers for the FortiManager MCP server.

Translates raw JSON-RPC responses into structured, Claude-readable dicts.
Implements cross-ADOM logic: when searching for object reuse candidates,
queries both the per-ADOM object database AND the global ADOM.
"""

from __future__ import annotations

import ipaddress
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from fortimanager_mcp.client import FortiManagerClient, FortiManagerAPIError
from fortimanager_mcp.matching import (
    AddressCatalog,
    PolicyMatcher,
    ServiceCatalog,
    parse_service_request,
)
from fortimanager_mcp.zone_map import load_zone_map, lookup_policy_zone, missing_entries, zone_map_file_exists

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# System status
# ---------------------------------------------------------------------------

def get_system_status(client: FortiManagerClient) -> dict[str, Any]:
    """
    Return FortiManager system status. Field names on the raw FMG response
    vary slightly by version, so common fields are normalised and the full
    raw payload is preserved under 'raw' so nothing is lost either way.
    """
    raw = client.get_system_status()
    return {
        "version": raw.get("Version", raw.get("version", "")),
        "hostname": raw.get("Host Name", raw.get("hostname", "")),
        "serial_number": raw.get("Serial Number", raw.get("serial", "")),
        "platform": raw.get("Platform Type", raw.get("platform", "")),
        "raw": raw,
    }


def get_ha_status(client: FortiManagerClient) -> dict[str, Any]:
    """
    Return FortiManager HA cluster status. Response shape varies by HA
    topology (standalone vs cluster), so the raw payload is returned as-is.
    """
    return client.get_ha_status()


# ---------------------------------------------------------------------------
# ADOM / device helpers
# ---------------------------------------------------------------------------

def list_adoms(client: FortiManagerClient) -> list[dict]:
    """Return a summarised list of all ADOMs."""
    adoms = client.get_adoms()
    return [
        {
            "name": a.get("name", ""),
            "status": a.get("status", ""),
            "os_type": a.get("os_type", ""),
            "desc": a.get("desc", ""),
        }
        for a in adoms
        if isinstance(a, dict)
    ]


def list_devices(client: FortiManagerClient, adom: str) -> list[dict]:
    """Return a summarised list of FortiGates in an ADOM."""
    devices = client.get_devices(adom)
    result = []
    for d in devices:
        if not isinstance(d, dict):
            continue
        meta = {
            "name": d.get("name", ""),
            "ip": d.get("ip", ""),
            "os_ver": d.get("os_ver", ""),
            "mr": d.get("mr", ""),
            "patch": d.get("patch", ""),
            "ha_mode": d.get("ha_mode", 0),
            "conn_status": d.get("conn_status", ""),
            "db_status": d.get("db_status", ""),
        }
        result.append(meta)
    return result


def list_device_vdoms(client: FortiManagerClient, adom: str, device: str) -> list[dict]:
    """Return VDOMs configured on a device."""
    vdoms = client.get_device_vdoms(adom, device)
    result = []
    for v in vdoms:
        if not isinstance(v, dict):
            continue
        result.append({
            "name": v.get("name", ""),
            "vdom_type": v.get("vdom_type", v.get("type", "")),
            "opmode": v.get("opmode", ""),
            "status": v.get("status", ""),
        })
    return result


_CONN_STATUS_LABELS = {1: "up", 2: "down"}


def search_devices(
    client: FortiManagerClient,
    adom: str,
    name_filter: str = "",
    platform_filter: str = "",
    os_version_filter: str = "",
    connection_status: str = "",
) -> dict[str, Any]:
    """
    Filter devices in an ADOM by name substring, platform substring, OS
    version substring, and/or connection status. All filters are optional
    and combine with AND. Filtering is client-side over get_devices — no
    additional FortiManager query is issued.
    """
    conn_filter = ""
    if connection_status:
        conn_filter = connection_status.strip().lower()
        if conn_filter not in ("up", "down"):
            return {"error": f"connection_status must be 'up' or 'down', got {connection_status!r}"}

    devices = client.get_devices(adom)
    matches = []
    for d in devices:
        if not isinstance(d, dict):
            continue
        if name_filter and name_filter.lower() not in str(d.get("name", "")).lower():
            continue
        platform = str(d.get("platform_str", d.get("platform", "")))
        if platform_filter and platform_filter.lower() not in platform.lower():
            continue
        if os_version_filter and os_version_filter not in str(d.get("os_ver", "")):
            continue
        conn_label = _CONN_STATUS_LABELS.get(d.get("conn_status", 0), "unknown")
        if conn_filter and conn_filter != conn_label:
            continue
        matches.append({
            "name": d.get("name", ""),
            "ip": d.get("ip", ""),
            "platform": platform,
            "os_ver": d.get("os_ver", ""),
            "conn_status": conn_label,
            "db_status": d.get("db_status", ""),
        })

    return {"count": len(matches), "devices": matches}


# ---------------------------------------------------------------------------
# Catalog cache — avoids re-fetching thousands of address/service objects on
# every plan_change call. TTL defaults to 10 minutes; stale entries are
# refreshed on next access. Cache is per (host, adom) key.
#
# Policy cache — same TTL, caches (packages list, policies-by-package dict)
# per (host, adom) key. Eliminates the dominant cold-start cost of plan_change:
# iterating all policy packages for two firewalls in ENTERPRISE-SERVICES was
# the 2–3 minute fetch that caused the SSE stream to drop before results arrived.
# ---------------------------------------------------------------------------

_catalog_cache: dict[str, tuple[float, AddressCatalog, ServiceCatalog]] = {}
_catalog_lock = threading.Lock()
_catalog_inflight: dict[str, threading.Event] = {}
_CATALOG_TTL = 3600  # seconds (1 hour)

_policy_cache: dict[str, tuple[float, list[dict], dict[str, list[dict] | None]]] = {}
_policy_lock = threading.Lock()
_policy_inflight: dict[str, threading.Event] = {}
_POLICY_TTL = 3600  # seconds (1 hour)

# Global address objects are the same regardless of ADOM — cache them once
# per FortiManager host to avoid re-fetching on every per-ADOM catalog build.
_global_addr_cache: dict[str, tuple[float, list[dict], list[dict]]] = {}
_global_addr_lock = threading.Lock()
_global_addr_inflight: dict[str, threading.Event] = {}
_GLOBAL_ADDR_TTL = 3600  # seconds (1 hour)


def _cache_key(client: FortiManagerClient, adom: str) -> str:
    return f"{getattr(client, '_active_host', id(client))}:{adom}"


def _host_key(client: FortiManagerClient) -> str:
    return str(getattr(client, "_active_host", id(client)))


def _get_global_addresses(
    client: FortiManagerClient,
) -> tuple[list[dict], list[dict]]:
    """Fetch global address objects and groups, cached per FMG host.

    Global objects are ADOM-independent — fetching them once per host and
    reusing the result for all per-ADOM catalog builds avoids downloading the
    same large list 25 times during the startup warm-up.
    """
    key = _host_key(client)

    while True:
        now = time.monotonic()
        with _global_addr_lock:
            entry = _global_addr_cache.get(key)
            if entry and (now - entry[0]) < _GLOBAL_ADDR_TTL:
                logger.debug("Global addr cache HIT for %s", key)
                return entry[1], entry[2]
            if key in _global_addr_inflight:
                event = _global_addr_inflight[key]
            else:
                event = threading.Event()
                _global_addr_inflight[key] = event
                break

        logger.debug("Global addr cache: waiting for in-flight fetch of %s", key)
        event.wait()

    logger.info("Global addr cache MISS for %s — fetching from FortiManager", key)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            f_obj = pool.submit(client.get_global_address_objects)
            f_grp = pool.submit(client.get_global_address_groups)
            global_objs = f_obj.result()
            global_grps = f_grp.result()

        with _global_addr_lock:
            _global_addr_cache[key] = (time.monotonic(), global_objs, global_grps)
            _global_addr_inflight.pop(key, None)
        event.set()
        return global_objs, global_grps
    except Exception:
        with _global_addr_lock:
            _global_addr_inflight.pop(key, None)
        event.set()
        raise


def build_catalogs(
    client: FortiManagerClient, adom: str
) -> tuple[AddressCatalog, ServiceCatalog]:
    """Fetch and index all address/service objects for an ADOM (incl. global).

    Results are cached for _CATALOG_TTL seconds. Concurrent callers for the
    same key block until the first fetch completes rather than each issuing
    their own redundant FortiManager calls.
    """
    key = _cache_key(client, adom)

    while True:
        now = time.monotonic()
        with _catalog_lock:
            entry = _catalog_cache.get(key)
            if entry and (now - entry[0]) < _CATALOG_TTL:
                logger.debug("Catalog cache HIT for %s (age %.0fs)", key, now - entry[0])
                return entry[1], entry[2]
            # Another thread is already fetching — wait for it
            if key in _catalog_inflight:
                event = _catalog_inflight[key]
            else:
                event = threading.Event()
                _catalog_inflight[key] = event
                break  # this thread owns the fetch

        logger.debug("Catalog cache: waiting for in-flight fetch of %s", key)
        event.wait()
        # After the fetching thread signals, loop back and read from cache

    logger.info("Catalog cache MISS for %s — fetching from FortiManager", key)
    try:
        # Global objects are host-wide — fetched once and shared across all ADOMs.
        # Per-ADOM addr/svc objects and global objects are fetched concurrently.
        fetches = {
            "addr":    lambda: client.get_address_objects(adom),
            "addr_grp": lambda: client.get_address_groups(adom),
            "svc":     lambda: client.get_service_objects(adom),
            "svc_grp": lambda: client.get_service_groups(adom),
        }
        results: dict[str, list] = {}
        with ThreadPoolExecutor(max_workers=5) as pool:
            f_global = pool.submit(_get_global_addresses, client)
            futures = {pool.submit(fn): k for k, fn in fetches.items()}
            global_objs, global_grps = f_global.result()
            for future in as_completed(futures):
                results[futures[future]] = future.result()

        addr_catalog = AddressCatalog(
            results["addr"],
            results["addr_grp"],
            global_objs,
            global_grps,
        )
        svc_catalog = ServiceCatalog(
            results["svc"],
            results["svc_grp"],
        )

        with _catalog_lock:
            _catalog_cache[key] = (time.monotonic(), addr_catalog, svc_catalog)
            _catalog_inflight.pop(key, None)
        event.set()
        return addr_catalog, svc_catalog
    except Exception:
        with _catalog_lock:
            _catalog_inflight.pop(key, None)
        event.set()
        raise


def build_policy_snapshot(
    client: FortiManagerClient, adom: str
) -> tuple[list[dict], dict[str, list[dict] | None]]:
    """Fetch and cache all policy packages and their policies for an ADOM.

    Returns (packages, policies_by_package). A None value for a package means
    the fetch failed (callers must treat that as degraded, not empty). Results
    are cached for _POLICY_TTL seconds (1 hour). Concurrent callers for the
    same key block until the first fetch completes — no redundant parallel
    FortiManager fetches.
    """
    key = _cache_key(client, adom)

    while True:
        now = time.monotonic()
        with _policy_lock:
            entry = _policy_cache.get(key)
            if entry and (now - entry[0]) < _POLICY_TTL:
                logger.debug("Policy cache HIT for %s (age %.0fs)", key, now - entry[0])
                return entry[1], entry[2]
            if key in _policy_inflight:
                event = _policy_inflight[key]
            else:
                event = threading.Event()
                _policy_inflight[key] = event
                break

        logger.debug("Policy cache: waiting for in-flight fetch of %s", key)
        event.wait()

    logger.info("Policy cache MISS for %s — fetching from FortiManager", key)
    try:
        packages = client.get_policy_packages(adom)

        def _fetch_pkg(pkg: dict) -> tuple[str, list[dict] | None]:
            pkg_name = pkg.get("name", "")
            try:
                return pkg_name, [p for p in client.get_policies(adom, pkg_name) if isinstance(p, dict)]
            except FortiManagerAPIError as exc:
                logger.warning("Policy cache: failed to fetch %s/%s: %s", adom, pkg_name, exc)
                return pkg_name, None  # None = fetch failed; [] = successfully empty

        policies_by_package: dict[str, list[dict] | None] = {}
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(_fetch_pkg, pkg): pkg for pkg in packages}
            for future in as_completed(futures):
                pkg_name, policies = future.result()
                if pkg_name:
                    policies_by_package[pkg_name] = policies

        with _policy_lock:
            _policy_cache[key] = (time.monotonic(), packages, policies_by_package)
            _policy_inflight.pop(key, None)
        event.set()
        return packages, policies_by_package
    except Exception:
        with _policy_lock:
            _policy_inflight.pop(key, None)
        event.set()
        raise


def get_device_policies(
    client: FortiManagerClient, adom: str, device_pkgs: list[str]
) -> dict[str, list[dict] | None]:
    """Return policies for only the specified package names.

    Uses the full ADOM policy cache if warm. On a cold cache, fetches only
    the requested packages in parallel — dramatically faster than a full-ADOM
    scan when only 2-3 packages are needed for a specific device.

    A None value for a package means the fetch failed (caller should degrade).
    """
    key = _cache_key(client, adom)
    now = time.monotonic()

    with _policy_lock:
        entry = _policy_cache.get(key)
        if entry and (now - entry[0]) < _POLICY_TTL:
            logger.debug("Policy cache HIT (device path) for %s", key)
            all_policies = entry[2]
            return {pkg: all_policies.get(pkg) for pkg in device_pkgs}

    logger.info(
        "Policy cache MISS (device path) for %s — fetching %d package(s) directly: %s",
        key, len(device_pkgs), device_pkgs,
    )

    def _fetch(pkg_name: str) -> tuple[str, list[dict] | None]:
        try:
            return pkg_name, [
                p for p in client.get_policies(adom, pkg_name) if isinstance(p, dict)
            ]
        except FortiManagerAPIError as exc:
            logger.warning("get_device_policies: failed %s/%s: %s", adom, pkg_name, exc)
            return pkg_name, None

    result: dict[str, list[dict] | None] = {}
    workers = max(1, min(len(device_pkgs), 4))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for pkg_name, policies in pool.map(_fetch, device_pkgs):
            result[pkg_name] = policies
    return result


def search_policies(
    client: FortiManagerClient,
    adom: str,
    device: str,
    src_ip: str = "",
    dst_ip: str = "",
    service: str = "",
) -> dict[str, Any]:
    """
    Find policies in all packages assigned to a device that could match the
    given traffic parameters, using set-semantics matching (service objects
    resolved to numeric port ranges, address groups recursed).

    Returns a structured result:
      policies          : matching policies (summary + full_cover/disabled/
                          conditional_schedule/unknown_refs flags)
      packages_searched : packages successfully queried
      packages_failed   : [{package, error}] — fetch failures
      degraded          : True if any package failed or the service string was
                          unparseable. When degraded, an empty `policies` list
                          must NOT be read as "no existing rule".
    """
    result: dict[str, Any] = {
        "policies": [],
        "packages_searched": [],
        "packages_failed": [],
        "degraded": False,
    }

    try:
        service_ranges = parse_service_request(service)
    except ValueError as exc:
        result["degraded"] = True
        result["error"] = str(exc)
        return result

    packages = client.get_policy_packages(adom)
    device_pkgs = [
        p for p in packages
        if isinstance(p, dict) and _package_targets_device(p, device)
    ]

    addr_catalog, svc_catalog = build_catalogs(client, adom)
    matcher = PolicyMatcher(addr_catalog, svc_catalog)

    for pkg in device_pkgs:
        pkg_name = pkg.get("name", "")
        try:
            policies = client.get_policies(adom, pkg_name)
        except FortiManagerAPIError as exc:
            logger.warning("Could not fetch policies from %s/%s: %s", adom, pkg_name, exc)
            result["packages_failed"].append({"package": pkg_name, "error": str(exc)})
            result["degraded"] = True
            continue

        result["packages_searched"].append(pkg_name)
        for pol in policies:
            if not isinstance(pol, dict):
                continue
            match = matcher.evaluate(pol, src_ip, dst_ip, service_ranges)
            if match.matched:
                summary = _summarise_policy(pol, pkg_name)
                summary["full_cover"] = match.full_cover
                summary["disabled"] = match.disabled
                summary["conditional_schedule"] = match.conditional_schedule
                summary["unknown_refs"] = match.unknown_refs
                result["policies"].append(summary)

    result["policies"].sort(key=lambda p: (p["package"], p["policy_id"]))
    return result


def _package_targets_device(pkg: dict, device: str) -> bool:
    """Return True if the package's installation scope includes the device."""
    scope = pkg.get("scope member", pkg.get("scope_member", []))
    if not scope:
        return True  # global/unscoped packages apply to all
    return any(
        s.get("name", "") == device
        for s in scope
        if isinstance(s, dict)
    )


def _object_covers_target(target, obj: dict) -> bool:
    """True if an address object's resolved networks overlap the target."""
    nets = AddressCatalog._networks_for_object(obj)
    if not nets:
        return False
    return any(target.overlaps(n) for n in nets)


def _summarise_policy(pol: dict, package_name: str) -> dict[str, Any]:
    def _names(field) -> list[str]:
        if isinstance(field, list):
            return [x if isinstance(x, str) else x.get("name", str(x)) for x in field]
        if isinstance(field, str):
            return [field]
        return []

    action_map = {0: "deny", 1: "accept", 2: "ipsec", 3: "ssl-vpn"}
    action_raw = pol.get("action", 0)
    action = action_map.get(action_raw, str(action_raw))

    log_map = {0: "disable", 1: "utm", 2: "all"}
    log_raw = pol.get("logtraffic", 0)
    log = log_map.get(log_raw, str(log_raw))

    return {
        "package": package_name,
        "policy_id": pol.get("policyid", 0),
        "name": pol.get("name", ""),
        "status": pol.get("status", "enable"),
        "source": _names(pol.get("srcaddr", [])),
        "source_interface": _names(pol.get("srcintf", [])),
        "destination": _names(pol.get("dstaddr", [])),
        "destination_interface": _names(pol.get("dstintf", [])),
        "service": _names(pol.get("service", [])),
        "action": action,
        "log": log,
        "nat": pol.get("nat", "disable"),
        "schedule": _names(pol.get("schedule", ["always"])),
        "srcaddr_negate": pol.get("srcaddr-negate", "disable") in ("enable", 1, True),
        "dstaddr_negate": pol.get("dstaddr-negate", "disable") in ("enable", 1, True),
        "comments": pol.get("comments", ""),
        "uuid": pol.get("uuid", ""),
    }


# ---------------------------------------------------------------------------
# Address object search
# ---------------------------------------------------------------------------

def get_address_object(
    client: FortiManagerClient, adom: str, name_or_ip: str
) -> dict:
    """
    Look up by exact name, or fall back to IP search if name not found.
    Also checks the global ADOM for inherited objects.
    """
    # Try exact name first
    try:
        obj = client.get_address_object(adom, name_or_ip)
        if obj:
            return _summarise_address_object(obj, adom)
    except FortiManagerAPIError as exc:
        if exc.code != -9:  # -9 = not found, anything else is unexpected
            raise

    # Fall back to IP search
    matches = search_address_objects(client, adom, name_or_ip)
    if not matches:
        return {"error": f"No address object found for '{name_or_ip}' in ADOM '{adom}'"}
    return matches[0]


def search_address_objects(
    client: FortiManagerClient, adom: str, ip: str
) -> list[dict]:
    """
    Find all address objects containing the given IP.
    Searches both per-ADOM and global ADOM object databases.
    """
    try:
        target_net = ipaddress.ip_network(ip, strict=False)
    except ValueError:
        return [{"error": f"Invalid IP or CIDR: '{ip}'"}]

    results = []

    for scope, objects in (
        (adom, client.get_address_objects(adom)),
        ("global", client.get_global_address_objects()),
    ):
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            if _object_covers_target(target_net, obj):
                results.append(_summarise_address_object(obj, scope))

    return results


def _summarise_address_object(obj: dict, scope: str) -> dict[str, Any]:
    subnet_raw = obj.get("subnet", "")
    if isinstance(subnet_raw, list) and len(subnet_raw) == 2:
        subnet = f"{subnet_raw[0]}/{subnet_raw[1]}"
    else:
        subnet = str(subnet_raw)

    return {
        "name": obj.get("name", ""),
        "type": obj.get("type", "ipmask"),
        "subnet": subnet,
        "fqdn": obj.get("fqdn", ""),
        "comment": obj.get("comment", ""),
        "adom_scope": scope,
        "uuid": obj.get("uuid", ""),
    }


# ---------------------------------------------------------------------------
# Service object search
# ---------------------------------------------------------------------------

def get_service_object(
    client: FortiManagerClient, adom: str, name_or_port: str
) -> dict:
    """Look up a service by name, falling back to port-substring search."""
    try:
        obj = client.get_service_object(adom, name_or_port)
        if obj:
            return _summarise_service_object(obj)
    except FortiManagerAPIError as exc:
        if exc.code != -9:
            raise

    # Fall back to substring search across all service objects
    all_svcs = client.get_service_objects(adom)
    for svc in all_svcs:
        if not isinstance(svc, dict):
            continue
        tcp_range = svc.get("tcp-portrange", "")
        udp_range = svc.get("udp-portrange", "")
        if (
            name_or_port in svc.get("name", "")
            or name_or_port in tcp_range
            or name_or_port in udp_range
        ):
            return _summarise_service_object(svc)

    return {"error": f"No service object found for '{name_or_port}' in ADOM '{adom}'"}


def _summarise_service_object(obj: dict) -> dict[str, Any]:
    return {
        "name": obj.get("name", ""),
        "protocol": obj.get("protocol", "TCP/UDP/SCTP"),
        "tcp_portrange": obj.get("tcp-portrange", ""),
        "udp_portrange": obj.get("udp-portrange", ""),
        "comment": obj.get("comment", ""),
        "uuid": obj.get("uuid", ""),
    }


# ---------------------------------------------------------------------------
# Individual policy detail
# ---------------------------------------------------------------------------

def get_policy(
    client: FortiManagerClient, adom: str, pkg: str, policy_id: int
) -> dict:
    """Return full detail for a single policy."""
    raw = client.get_policy(adom, pkg, policy_id)
    return _summarise_policy(raw, pkg)


# ---------------------------------------------------------------------------
# Interface / zone map
# ---------------------------------------------------------------------------

def get_interface_map(
    client: FortiManagerClient, adom: str, device: str
) -> dict[str, Any]:
    """
    Return interface-to-zone assignments for a device.
    Includes IP, zone membership, and VLAN info.
    """
    interfaces = client.get_device_interfaces(adom, device)
    zone_map = load_zone_map()
    map_file_missing = not zone_map_file_exists()
    iface_list = []
    for iface in interfaces:
        if not isinstance(iface, dict):
            continue
        name = iface.get("name", "")
        alias = iface.get("alias", "")
        policy_zone = lookup_policy_zone(zone_map, device, name)
        iface_list.append({
            "name": name,
            "ip": iface.get("ip", ""),
            "type": iface.get("type", ""),
            "zone": iface.get("zone", ""),
            "vlanid": iface.get("vlanid", 0),
            "alias": alias,
            "description": iface.get("description", ""),
            "status": iface.get("status", "up"),
            "policy_zone": policy_zone,
            "zone_map_missing": policy_zone is None,
        })

    zone_map_warnings: list[str] = []
    if map_file_missing:
        zone_map_warnings.append(
            "device_zone_map.yaml not found — interface-to-policy-zone mapping unavailable."
            " Run scripts/import_zone_map.py to generate it."
        )
    else:
        for entry in iface_list:
            if entry["zone_map_missing"]:
                alias_part = f" (alias: {entry['alias']})" if entry["alias"] else ""
                zone_map_warnings.append(
                    f"{entry['name']}{alias_part} has no policy_zone mapping"
                    " — add it to device_zone_map.yaml"
                )

    meta = client.get_device_meta(adom, device)
    return {
        "device": device,
        "adom": adom,
        "firmware": f"{meta.get('os_ver', '')}.{meta.get('mr', '')}.{meta.get('patch', '')}",
        "ha_mode": meta.get("ha_mode", 0),
        "interfaces": iface_list,
        "zone_map_warnings": zone_map_warnings,
    }


# ---------------------------------------------------------------------------
# Routing table
# ---------------------------------------------------------------------------

def get_routing_table(
    client: FortiManagerClient, adom: str, device: str
) -> list[dict]:
    """Return static routes configured on a device."""
    routes = client.get_routing_table(adom, device)
    result = []
    for r in routes:
        if not isinstance(r, dict):
            continue
        result.append({
            "seq_num": r.get("seq-num", 0),
            "dst": r.get("dst", ""),
            "gateway": r.get("gateway", ""),
            "device": r.get("device", ""),
            "distance": r.get("distance", 10),
            "priority": r.get("priority", 0),
            "comment": r.get("comment", ""),
            "status": r.get("status", "enable"),
        })
    result.sort(key=lambda r: r["seq_num"])
    return result
