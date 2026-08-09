import pytest

from mcp_common.validation import (
    ValidationError,
    validate_adom,
    validate_device_name,
    validate_object_name,
)


def test_validate_adom_accepts_normal_name():
    assert validate_adom("OT-ADOM") == "OT-ADOM"


def test_validate_adom_strips_whitespace():
    assert validate_adom("  root  ") == "root"


def test_validate_adom_rejects_empty():
    with pytest.raises(ValidationError):
        validate_adom("")


def test_validate_adom_rejects_path_traversal_chars():
    with pytest.raises(ValidationError):
        validate_adom("../etc/passwd")


def test_validate_adom_rejects_oversized():
    with pytest.raises(ValidationError):
        validate_adom("a" * 200)


def test_validate_device_name_accepts_normal_name():
    assert validate_device_name("SITE01-FW01") == "SITE01-FW01"


def test_validate_device_name_rejects_slash():
    with pytest.raises(ValidationError):
        validate_device_name("FW/../other")


def test_validate_object_name_accepts_normal_name():
    assert validate_object_name("H_10.1.2.3", kind="address") == "H_10.1.2.3"


def test_validate_object_name_error_mentions_kind():
    with pytest.raises(ValidationError, match="interface"):
        validate_object_name("bad name!", kind="interface")
