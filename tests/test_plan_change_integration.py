"""
Integration test for fwanalyst_server.server.plan_change()'s fgplanner client
wiring.

fgplanner (the external `fortigate-change-planner` package) ships no default
FortiManager/zone-policy clients and reads no credentials file by design —
callers must register client factories via
``fgplanner.clients.register_fmg_client_factory`` /
``register_zone_client_factory`` before calling ``plan_change``. Without that
wiring, every call fails with
``{"error": "no FortiManager client configured...", "error_source": "client"}``.

This test imports the REAL fgplanner package (not a mock of it), stubs out
fwanalyst_server's own client *builders* (``_build_fmg_client`` /
``_build_zone_client`` — the functions that would otherwise construct real
FortiManagerClient/ZonePolicyClient instances from credentials.yaml) with
fully synthetic fakes satisfying fgplanner's documented client protocols, and
then calls ``fwanalyst_server.server.plan_change(...)`` end to end exactly as
an MCP client would. It asserts the real fgplanner engine ran to completion
via our registered factories — i.e. the result is NOT
``{"error_source": "client"}``.

All addresses are RFC 5737 documentation-range space; all names are
synthetic.
"""

from __future__ import annotations

import pytest

fgplanner = pytest.importorskip("fgplanner")

from fgplanner import clients as fgplanner_clients  # noqa: E402

import fwanalyst_server.server as server  # noqa: E402

FW = "FW-EXAMPLE-01"
ADOM = "root"


@pytest.fixture(autouse=True)
def _reset_client_registry():
    """fgplanner's client factories are module-global — keep tests isolated."""
    fgplanner_clients.register_fmg_client_factory(None)
    fgplanner_clients.register_zone_client_factory(None)
    yield
    fgplanner_clients.register_fmg_client_factory(None)
    fgplanner_clients.register_zone_client_factory(None)


class FakeFMGClient:
    """Satisfies fgplanner.protocols.FirewallManagerClient with a single
    device, a single policy package, and one enabled any/any/any rule."""

    def get_devices(self, adom):
        return [{"name": FW}]

    def get_policy_packages(self, adom):
        return [{"name": "pkgA", "scope member": [{"name": FW}]}]

    def get_policies(self, adom, pkg):
        return [{
            "policyid": 1, "name": "pkgA-p1", "status": "enable",
            "action": 1, "srcaddr": ["all"], "dstaddr": ["all"],
            "service": ["ALL"], "srcintf": ["any"], "dstintf": ["any"],
            "schedule": ["always"],
        }]

    def get_address_objects(self, adom):
        return []

    def get_address_groups(self, adom):
        return []

    def get_service_objects(self, adom):
        return []

    def get_service_groups(self, adom):
        return []

    def get_device_interfaces(self, adom, device):
        return [
            {"name": "port1", "ip": "10.1.0.1 255.255.0.0",
             "type": "physical", "status": "up"},
            {"name": "port2", "ip": ["10.9.8.1", "255.255.255.0"],
             "type": "physical", "status": "up"},
        ]


class FakeZoneClient:
    """Satisfies fgplanner.protocols.ZoneClient with an ALLOWED verdict."""

    def query(self, src, dst, service="", verbose=True):
        return [{
            "src": src, "dst": dst, "service": service,
            "verdict": "ALLOWED", "src_zones": ["ZONE-OT-CORE"],
            "dst_zones": ["ZONE-IT-CORE"], "governing": [],
            "all_policies": [],
        }]

    def zones(self):
        return {"zones": [
            {"name": "ZONE-OT-CORE", "domain": "OT"},
            {"name": "ZONE-IT-CORE", "domain": "IT"},
        ]}

    def policies(self):
        return []


def test_plan_change_registers_working_client_factories(monkeypatch):
    """Reproduces the reported bug: plan_change() must register fgplanner
    client factories before calling into the engine. Prior to the fix,
    nothing called register_fmg_client_factory/register_zone_client_factory
    anywhere in fwanalyst_server, so this call would fail with
    error_source == "client" regardless of how good the credentials were.
    """
    # Stand in for fwanalyst_server's real credentials-backed builders —
    # this isolates the test from needing a real credentials.yaml while
    # still exercising the real registration call inside plan_change().
    monkeypatch.setattr(server, "_build_fmg_client", lambda: FakeFMGClient())
    monkeypatch.setattr(server, "_build_zone_client", lambda: FakeZoneClient())

    # Sanity check: nothing registered yet in this test.
    assert fgplanner_clients._fmg_factory is None
    assert fgplanner_clients._zone_factory is None

    result = server.plan_change(
        src="10.1.2.3",
        dst="10.9.8.7",
        service="443",
        firewalls=[f"{FW}:{ADOM}"],
        justification="integration test flow",
        ticket_id="CHG0000099",
    )

    assert result.get("error_source") != "client", result
    assert "error" not in result, result

    # The factories should now be registered (idempotent — calling
    # plan_change again must not error either).
    assert fgplanner_clients._fmg_factory is not None
    assert fgplanner_clients._zone_factory is not None

    result2 = server.plan_change(
        src="10.1.2.3",
        dst="10.9.8.7",
        service="443",
        firewalls=[f"{FW}:{ADOM}"],
        justification="integration test flow, second call",
        ticket_id="CHG0000100",
    )
    assert result2.get("error_source") != "client", result2
