"""
Device-to-zone mapping loader for FortiManager MCP.

Maps FortiGate interface names (per-device) to 4THealth policy zone names.
The map file is optional — if absent, all lookups return None gracefully.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml

_REPO_ROOT = Path(__file__).parent.parent
_DEFAULT_MAP_FILE = _REPO_ROOT / "device_zone_map.yaml"


@lru_cache(maxsize=1)
def load_zone_map(map_path: Optional[Path] = None) -> dict:
    resolved = Path(os.environ.get("ZONE_MAP_FILE", "")) if os.environ.get("ZONE_MAP_FILE") else (map_path or _DEFAULT_MAP_FILE)
    if not resolved.exists():
        return {}
    with resolved.open() as fh:
        data = yaml.safe_load(fh) or {}
    return data.get("devices", {})


def lookup_policy_zone(zone_map: dict, device: str, interface_name: str) -> Optional[str]:
    device_entry = zone_map.get(device, {})
    iface_entry = device_entry.get(interface_name, {})
    return iface_entry.get("policy_zone") if isinstance(iface_entry, dict) else None


def missing_entries(zone_map: dict, device: str, interfaces: list[str]) -> list[str]:
    device_entry = zone_map.get(device, {})
    return [
        iface for iface in interfaces
        if iface not in device_entry
        or not isinstance(device_entry[iface], dict)
        or device_entry[iface].get("policy_zone") is None
    ]


def zone_map_file_exists(map_path: Optional[Path] = None) -> bool:
    resolved = Path(os.environ.get("ZONE_MAP_FILE", "")) if os.environ.get("ZONE_MAP_FILE") else (map_path or _DEFAULT_MAP_FILE)
    return resolved.exists()
