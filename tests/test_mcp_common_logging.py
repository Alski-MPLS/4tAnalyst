from mcp_common.logging import sanitize_for_logging


def test_masks_password_field():
    out = sanitize_for_logging({"user": "admin", "password": "secret123"})
    assert out == {"user": "admin", "password": "***REDACTED***"}


def test_masks_nested_token_field():
    out = sanitize_for_logging({"auth": {"api_token": "abc123"}})
    assert out["auth"]["api_token"] == "***REDACTED***"


def test_masks_within_lists():
    out = sanitize_for_logging([{"secret": "x"}, {"name": "ok"}])
    assert out[0]["secret"] == "***REDACTED***"
    assert out[1]["name"] == "ok"


def test_leaves_non_sensitive_data_untouched():
    out = sanitize_for_logging({"device": "FW01", "count": 3})
    assert out == {"device": "FW01", "count": 3}


def test_depth_limit_prevents_infinite_recursion():
    data = {}
    node = data
    for _ in range(20):
        node["child"] = {}
        node = node["child"]
    out = sanitize_for_logging(data)
    assert out is not None  # completes without recursion error


def test_passes_through_primitives():
    assert sanitize_for_logging("plain string") == "plain string"
    assert sanitize_for_logging(42) == 42
    assert sanitize_for_logging(None) is None


def test_masks_scalar_auth_value():
    out = sanitize_for_logging({"auth": "Bearer xyz789"})
    assert out["auth"] == "***REDACTED***"
