"""
4THealth Zone Policy API client.

Wraps the external read-only REST API exposed by the 4THealth application:
  POST /external/api/zone/query    — traffic policy query (src×dst verdict)
  GET  /external/api/zone/zones    — full zone catalogue
  GET  /external/api/zone/policies — raw policy table

Authentication is a static Bearer token.  SSL verification is off by default
because the server uses a self-signed certificate.

All methods raise ZonePolicyError on HTTP 4xx/5xx or on known API-level
error responses (503 disabled, 503 no DB, 401 bad token).
"""

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)


class ZonePolicyError(Exception):
    """Raised for HTTP errors or API-level errors from the 4THealth zone API."""


class ZonePolicyClient:
    """
    Thin HTTP client for the 4THealth external zone policy API.

    Parameters
    ----------
    base_url   : Base URL including scheme and host, e.g. "https://4thealth.internal.example.com"
    token      : Bearer token (the 4th_... value)
    verify_ssl : Whether to verify the server's TLS certificate (False for self-signed)
    timeout    : Per-request timeout in seconds
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        verify_ssl: bool = False,
        timeout: float = 30.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Bearer {token}"
        self._session.verify = verify_ssl

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, path: str) -> Any:
        url = f"{self._base}{path}"
        resp = self._session.get(url, timeout=self._timeout)
        self._raise_for_status(resp)
        return resp.json()

    def _post(self, path: str, body: dict) -> Any:
        url = f"{self._base}{path}"
        resp = self._session.post(url, json=body, timeout=self._timeout)
        self._raise_for_status(resp)
        return resp.json()

    @staticmethod
    def _raise_for_status(resp: requests.Response) -> None:
        if resp.status_code == 401:
            raise ZonePolicyError("Unauthorized — check the 4THealth Bearer token.")
        if resp.status_code == 503:
            try:
                msg = resp.json().get("error", resp.text)
            except Exception:
                msg = resp.text
            raise ZonePolicyError(f"4THealth API unavailable: {msg}")
        if resp.status_code >= 400:
            raise ZonePolicyError(
                f"HTTP {resp.status_code} from 4THealth API: {resp.text[:500]}"
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def query(
        self,
        src: str,
        dst: str,
        service: str = "",
        verbose: bool = True,
    ) -> list[dict]:
        """
        Query zone policy for one or more src×dst pairs.

        Parameters
        ----------
        src     : Single IP, CIDR, or newline/comma-separated list of either.
        dst     : Single IP, CIDR, or newline/comma-separated list of either.
        service : Optional port, port name, or proto/port (e.g. "443", "ssh", "tcp/8443").
        verbose : When True the response includes ``all_policies`` for each pair.

        Returns a list of result objects, one per src×dst combination.
        Each object contains: src, dst, service, verdict, src_zones, dst_zones,
        governing (rules that determined the verdict), and all_policies (if verbose).
        """
        body: dict[str, Any] = {"src": src, "dst": dst, "verbose": verbose}
        if service:
            body["service"] = service
        return self._post("/external/api/zone/query", body)

    def zones(self) -> dict:
        """
        Return the full zone catalogue.

        Returns a dict with:
          zones         : list of zone objects (name, domain, is_shared, description,
                          subnets, children, parents)
          total_subnets : total number of subnets across all zones
        """
        return self._get("/external/api/zone/zones")

    def policies(self) -> list[dict]:
        """
        Return the raw policy table.

        Each entry: index, policy_set, from_zone, to_zone, access_type,
        severity, services, description.
        access_type is one of: "allow all", "block all", "block only".
        """
        return self._get("/external/api/zone/policies")

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "ZonePolicyClient":
        return self

    def __exit__(self, *_) -> None:
        self.close()
