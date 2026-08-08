"""Shared request-scoped context for the unified server.

Lives here (not in auth.py) so fortimanager_mcp can import allowed_adoms_var
without creating a circular dependency through fwanalyst_server.
"""

from contextvars import ContextVar

allowed_adoms_var: ContextVar[set[str]] = ContextVar("allowed_adoms")

# Human-readable label for the caller's token ("admin" for the primary token,
# the server.tokens `label` field for named ones). Access logging only — never
# a privilege source. Defaults to "-" so stdio mode, where no HTTP middleware
# ever sets it, logs cleanly instead of raising LookupError.
token_label_var: ContextVar[str] = ContextVar("token_label", default="-")
