"""Shared input validation for identifiers passed to external APIs.

These check shape (charset, length, non-empty), not business meaning —
callers still handle "not found" / "not permitted" themselves. The goal is
rejecting inputs that could be path-traversal or injection attempts before
they reach a URL path segment.
"""

from __future__ import annotations

import re

_MAX_LEN = 128
_SAFE_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


class ValidationError(ValueError):
    """Raised when an identifier fails shape validation."""


def _validate_identifier(value: str, label: str) -> str:
    stripped = value.strip() if isinstance(value, str) else ""
    if not stripped:
        raise ValidationError(f"{label} must not be empty")
    if len(stripped) > _MAX_LEN:
        raise ValidationError(f"{label} exceeds max length of {_MAX_LEN}")
    if not _SAFE_PATTERN.match(stripped):
        raise ValidationError(
            f"{label} contains invalid characters (allowed: letters, digits, '.', '_', '-')"
        )
    return stripped


def validate_adom(name: str) -> str:
    """Validate an ADOM name. Raises ValidationError on failure."""
    return _validate_identifier(name, "ADOM name")


def validate_device_name(name: str) -> str:
    """Validate a FortiGate device name. Raises ValidationError on failure."""
    return _validate_identifier(name, "Device name")


def validate_object_name(name: str, kind: str = "object") -> str:
    """Validate a generic FortiManager object name (address, service, interface, ...).

    ``kind`` is folded into the error message so a caller-visible failure
    says e.g. "interface name contains invalid characters" rather than a
    generic "object name".
    """
    return _validate_identifier(name, f"{kind} name")
