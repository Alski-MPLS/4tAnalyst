from mcp_common.errors import safe_error, sanitize_message


def test_sanitize_message_strips_url_paths():
    msg = "FortiManager API error on /pm/config/adom/OT-ADOM/pkg/foo: [-9] Object not found"
    result = sanitize_message(msg)
    assert "/pm/config" not in result
    assert "Object not found" in result


def test_sanitize_message_passes_through_plain_text():
    assert sanitize_message("Invalid input parameter.") == "Invalid input parameter."


def test_sanitize_message_handles_empty_string():
    assert sanitize_message("") == ""


def test_safe_error_value_error_returns_validation_category():
    msg, code = safe_error(ValueError("device name too long"))
    assert code == "validation_error"
    assert "too long" in msg


def test_safe_error_generic_exception_strips_paths():
    exc = RuntimeError("Failed calling /pm/config/adom/OT-ADOM/pkg/x: connection reset")
    msg, code = safe_error(exc)
    assert "/pm/config" not in msg
    assert code == "internal_error"


def test_safe_error_never_raises_on_empty_message():
    msg, code = safe_error(RuntimeError(""))
    assert msg
    assert code == "internal_error"


def test_sanitize_message_strips_ipv4_address():
    msg = "Connection to FortiManager 10.0.0.101 failed: timed out"
    result = sanitize_message(msg)
    assert "10.0.0.101" not in result
    assert "<host>" in result
    assert "timed out" in result


def test_sanitize_message_strips_dotted_hostname():
    msg = "Connection to FortiManager fmg-prod-01.corp.internal failed: timed out"
    result = sanitize_message(msg)
    assert "fmg-prod-01.corp.internal" not in result
    assert "<host>" in result
    assert "timed out" in result
