from fortimanager_mcp import query


class _StubClient:
    def __init__(self, interfaces):
        self._interfaces = interfaces

    def get_device_interface_config(self, device, vlanids=None, name=None):
        return self._interfaces


def test_get_device_interface_config_summary():
    stub = _StubClient([
        {"name": "port1", "vlanid": 20, "ip": "10.1.1.1 255.255.255.0", "alias": "OT-VLAN20"},
        "not-a-dict",
    ])
    result = query.get_device_interface_config(stub, "FW01", vlanids=[20])
    assert result["device"] == "FW01"
    assert result["interface_count"] == 1
    assert result["summary"][0]["name"] == "port1"
    assert result["summary"][0]["vlanid"] == 20


class _StubProxyClient:
    def __init__(self, records):
        self._records = records

    def get_device_client_location(self, adom, device):
        return [{"response": {"results": self._records}}]


def test_get_device_client_location_filters_by_ip():
    stub = _StubProxyClient([
        {"ipv4_address": "10.1.1.5", "hostname": "hmi-01", "mac": "AA:BB:CC:DD:EE:FF",
         "fortiswitch_port_name": "port3", "fortiswitch_vlan_id": 20},
        {"ipv4_address": "10.1.1.9", "hostname": "hmi-02"},
    ])
    result = query.get_device_client_location(stub, "OT-ADOM", "FW01", ip="10.1.1.5")
    assert result["match_count"] == 1
    assert result["clients"][0]["hostname"] == "hmi-01"
    assert result["clients"][0]["vlan_id"] == 20


def test_get_device_client_location_no_filter_returns_all():
    stub = _StubProxyClient([{"ipv4_address": "10.1.1.5"}, {"ipv4_address": "10.1.1.9"}])
    result = query.get_device_client_location(stub, "OT-ADOM", "FW01")
    assert result["match_count"] == 2
    assert result["query"] is None


class _StubSdwanClient:
    def get_device_sdwan(self, device, vdom="root"):
        return {
            "zone": [{"name": "virtual-wan-link"}],
            "members": {"member": [{"seq-num": 1, "interface": "wan1"}]},
            "health-check": {"health-check": [{"name": "gcp-ping"}]},
        }


def test_get_device_sdwan_summary():
    result = query.get_device_sdwan(_StubSdwanClient(), "FW01")
    assert result["device"] == "FW01"
    assert result["summary"]["zone_count"] == 1
    assert result["summary"]["member_count"] == 1
    assert result["summary"]["health_check_count"] == 1


class _StubSdwanMonitorClient:
    def get_device_sdwan_monitor(self, adom, device):
        members = [{"response": {"results": [
            {"interface": "wan1", "link": "up", "tx_bandwidth": 100, "rx_bandwidth": 90},
        ]}}]
        health = [{"response": {"results": {
            "gcp-ping": {"wan1": {"status": "up", "latency": 12, "packet_loss": 0}}
        }}}]
        return members, health


def test_get_device_sdwan_monitor_summary():
    result = query.get_device_sdwan_monitor(_StubSdwanMonitorClient(), "OT-ADOM", "FW01")
    assert result["summary"]["member_count"] == 1
    assert result["summary"]["members_up"] == 1
    assert result["summary"]["sla"][0]["health_check"] == "gcp-ping"
    assert result["summary"]["sla"][0]["interface"] == "wan1"
    assert result["summary"]["sla"][0]["status"] == "up"
