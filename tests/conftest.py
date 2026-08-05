import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import fortimanager_mcp.query as _fmq


@pytest.fixture(autouse=True)
def clear_catalog_cache():
    """Clear FortiManager catalog and policy caches before every test.

    Both caches are keyed on id(client) as a fallback for non-real clients.
    CPython may recycle object ids after garbage collection, causing a
    fresh fake-client instance to hit a stale cache entry from a prior test.
    """
    _fmq._catalog_cache.clear()
    _fmq._policy_cache.clear()
    _fmq._catalog_inflight.clear()
    _fmq._policy_inflight.clear()
    yield
    _fmq._catalog_cache.clear()
    _fmq._policy_cache.clear()
    _fmq._catalog_inflight.clear()
    _fmq._policy_inflight.clear()
