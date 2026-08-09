"""Sanitized error surfacing for tool functions.

Tool functions log the full exception server-side (with call context) but
must not echo raw internal details — API URL paths, endpoint structure —
back to the caller. ``safe_error`` returns a (message, category) pair safe
to put directly into a tool's JSON response.
"""

from __future__ import annotations

import re

_PATH_PATTERN = re.compile(r"/[A-Za-z0-9_./-]*/[A-Za-z0-9_-]+")
_IPV4_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_HOSTNAME_PATTERN = re.compile(
    r"\b(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,}\b"
)
_FALLBACK_MESSAGE = "An internal error occurred."


def sanitize_message(text: str) -> str:
    """Strip URL-path-shaped substrings, IPv4 addresses, and dotted hostnames
    (internal endpoint/object hierarchy and host identifiers) from text."""
    if not text:
        return text
    text = _PATH_PATTERN.sub("<path>", text)
    text = _IPV4_PATTERN.sub("<host>", text)
    text = _HOSTNAME_PATTERN.sub("<host>", text)
    return text.strip()


def safe_error(exc: Exception) -> tuple[str, str]:
    """Convert an exception into a caller-safe (message, category_code) pair.

    ValueError (and subclasses, e.g. mcp_common.validation.ValidationError)
    describes bad input the caller supplied — safe to surface close to
    verbatim, still path-scrubbed defensively. Everything else is treated as
    an internal error: scrubbed, and replaced with a generic fallback if
    scrubbing empties it out.
    """
    if isinstance(exc, ValueError):
        message = sanitize_message(str(exc)) or "Invalid input parameter."
        return message, "validation_error"

    message = sanitize_message(str(exc)) or _FALLBACK_MESSAGE
    return message, "internal_error"
