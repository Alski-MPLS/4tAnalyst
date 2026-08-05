import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import fortimanager_mcp.query as _fmq


@pytest.fixture(autouse=True)
def clear_catalog_cache():
    """Clear the FortiManager catalog cache before every test.

    The cache is keyed on id(client) as a fallback for non-real clients.
    CPython may recycle object ids after garbage collection, causing a
    fresh fake-client instance to hit a cached catalog from a prior test.
    """
    _fmq._catalog_cache.clear()
    yield
    _fmq._catalog_cache.clear()
