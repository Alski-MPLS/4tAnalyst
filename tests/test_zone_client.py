from zone_mcp.client import ZonePolicyClient


def test_query_monkeypatch():
    c = ZonePolicyClient('https://example.com', 'token', verify_ssl=True, timeout=1)

    # Monkeypatch internal _post to return a predictable result
    def fake_post(path, body):
        return [{'src': body['src'], 'dst': body['dst'], 'verdict': 'ALLOWED', 'src_zones': ['Users'], 'dst_zones': ['Servers'], 'governing': [], 'all_policies': []}]

    c._post = fake_post
    res = c.query('10.1.1.1', '10.2.2.2', service='ssh')
    assert isinstance(res, list)
    assert res[0]['verdict'] == 'ALLOWED'


def test_zones_monkeypatch():
    c = ZonePolicyClient('https://example.com', 'token')

    def fake_get(path):
        return {'zones': [], 'total_subnets': 0}

    c._get = fake_get
    z = c.zones()
    assert 'zones' in z


def test_verify_ssl_accepts_ca_bundle_path():
    # requests' `verify` accepts a str path to a CA bundle as well as a bool;
    # the client must pass a string through unchanged, not coerce it to a bool.
    ca_path = '/etc/4tanalyst/tls/internal-ca.pem'
    c = ZonePolicyClient('https://example.com', 'token', verify_ssl=ca_path)
    assert c._session.verify == ca_path


def test_verify_ssl_accepts_bool():
    c = ZonePolicyClient('https://example.com', 'token', verify_ssl=False)
    assert c._session.verify is False
