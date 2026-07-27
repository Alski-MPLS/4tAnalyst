"""Shared request-scoped context for the unified server.

Lives here (not in auth.py) so fortimanager_mcp can import allowed_adoms_var
without creating a circular dependency through fwanalyst_server.
"""

from contextvars import ContextVar

allowed_adoms_var: ContextVar[set[str]] = ContextVar("allowed_adoms")
