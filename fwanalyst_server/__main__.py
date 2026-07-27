"""
Entry point for the unified server.

  MCP_TRANSPORT=stdio (default)  — local development
  MCP_TRANSPORT=http             — streamable-HTTP behind static-bearer auth
                                   (FASTMCP_HOST/FASTMCP_PORT, token from
                                   FW_ANALYST_TOKEN or credentials.yaml
                                   server.auth_token; env wins)
"""

import os
from pathlib import Path

import yaml
from mcp.server.transport_security import TransportSecuritySettings

from fwanalyst_server.auth import require_bearer
from fwanalyst_server.rate_limit import rate_limit
from fwanalyst_server.server import mcp

_REPO_ROOT = Path(__file__).parent.parent
_DEFAULT_RATE_LIMIT_MAX = 300
_DEFAULT_RATE_LIMIT_WINDOW = 60.0


def _auth_token() -> str:
    env = os.getenv("FW_ANALYST_TOKEN", "")
    if env.strip():
        return env.strip()
    creds_path = Path(os.getenv("CREDENTIALS_FILE", str(_REPO_ROOT / "credentials.yaml")))
    if creds_path.exists():
        with open(creds_path, encoding="utf-8") as fh:
            creds = yaml.safe_load(fh) or {}
        return str(creds.get("server", {}).get("auth_token", "")).strip()
    return ""


def _load_creds() -> dict:
    """Load the full credentials dict (for ADOM restriction config)."""
    creds_path = Path(os.getenv("CREDENTIALS_FILE", str(_REPO_ROOT / "credentials.yaml")))
    if creds_path.exists():
        with open(creds_path, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    return {}


def _allowed_hosts() -> list[str]:
    """Host-header values (for DNS-rebinding protection) accepted on the
    engineers' connection URL — e.g. "central-server:8000" or a wildcard
    port "central-server:*". Comma-separated; env wins over credentials.yaml.

    The MCP SDK's default (localhost/127.0.0.1/[::1] only) rejects every
    real engineer connecting via the deployed hostname, so this must be set
    before the server is reachable from anywhere but localhost.
    """
    env = os.getenv("FW_ANALYST_ALLOWED_HOSTS", "")
    if env.strip():
        return [h.strip() for h in env.split(",") if h.strip()]
    creds_path = Path(os.getenv("CREDENTIALS_FILE", str(_REPO_ROOT / "credentials.yaml")))
    if creds_path.exists():
        with open(creds_path, encoding="utf-8") as fh:
            creds = yaml.safe_load(fh) or {}
        hosts = creds.get("server", {}).get("allowed_hosts", [])
        if isinstance(hosts, list):
            return [str(h).strip() for h in hosts if str(h).strip()]
    return []


def main() -> None:
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    if transport == "stdio":
        mcp.run()
        return

    if transport not in ("http", "streamable-http"):
        raise SystemExit(f"Unsupported MCP_TRANSPORT {transport!r} (use stdio or http)")

    import uvicorn

    host = os.getenv("FASTMCP_HOST", "0.0.0.0")
    port = int(os.getenv("FASTMCP_PORT", "8000"))
    mcp.settings.host = host
    mcp.settings.port = port

    allowed_hosts = _allowed_hosts()
    if allowed_hosts:
        mcp.settings.transport_security = TransportSecuritySettings(allowed_hosts=allowed_hosts)
    # Else: keep the SDK default (enable_dns_rebinding_protection=True,
    # allowed_hosts restricted to localhost/127.0.0.1/[::1]) — fail-closed
    # rather than silently accepting any Host header.

    app = mcp.streamable_http_app()

    max_requests = int(os.getenv("FW_ANALYST_RATE_LIMIT_MAX", str(_DEFAULT_RATE_LIMIT_MAX)))
    if max_requests > 0:
        window = float(os.getenv("FW_ANALYST_RATE_LIMIT_WINDOW_SECONDS",
                                  str(_DEFAULT_RATE_LIMIT_WINDOW)))
        app = rate_limit(app, max_requests, window)

    creds = _load_creds()
    app = require_bearer(app, _auth_token(), creds)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
