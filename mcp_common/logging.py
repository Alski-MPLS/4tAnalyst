"""Mask sensitive fields before logging request/response data."""

from __future__ import annotations

from typing import Any

_SENSITIVE_FIELDS = {
    "password", "passwd", "pass", "adm_pass", "adm_passwd",
    "api_token", "apikey", "api_key", "token", "session", "sid",
    "authorization", "auth", "secret", "key", "credential",
}
_MASK = "***REDACTED***"
_MAX_DEPTH = 10


def sanitize_for_logging(data: Any, depth: int = 0) -> Any:
    """Recursively mask sensitive-looking fields in a dict/list before logging.

    Depth-limited defensively (structures passed to this come from external
    API responses, not trusted call sites).
    """
    if depth > _MAX_DEPTH:
        return "<MAX_DEPTH>"

    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            key_norm = str(key).lower().replace("-", "_").replace(" ", "_")
            if any(sensitive in key_norm for sensitive in _SENSITIVE_FIELDS):
                # For sensitive keys: mask scalars, but recurse into containers
                if isinstance(value, (dict, list)):
                    result[key] = sanitize_for_logging(value, depth + 1)
                else:
                    result[key] = _MASK
            else:
                result[key] = sanitize_for_logging(value, depth + 1)
        return result

    if isinstance(data, list):
        return [sanitize_for_logging(item, depth + 1) for item in data]

    return data
