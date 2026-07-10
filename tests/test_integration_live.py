"""Live checks against the real data.gov.sg / Google Maps APIs.

Excluded from the default `pytest` run (see pytest.ini) since they need
network access and can be affected by upstream rate limits or schema
changes. Run explicitly with: pytest -m live
"""
import os

import httpx
import pytest

from hdb_bot.datagov_client import DataGovClient, RESALE_DATASET

pytestmark = pytest.mark.live


async def test_live_datagov_resale_query_for_known_town():
    client = DataGovClient(api_key=os.environ.get("DATA_GOV_SG_API_KEY"))
    records = await client.fetch_town_records(RESALE_DATASET.resource_id, "BISHAN", max_rows=50)
    assert records, "expected at least some resale records for BISHAN"
    sample = records[0]
    for field in ("month", "town", "flat_type", "resale_price"):
        assert field in sample, f"upstream schema may have changed, missing {field!r}"


async def test_live_static_maps_url_is_reachable():
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        pytest.skip("GOOGLE_MAPS_API_KEY not set")
    from hdb_bot.maps import build_static_map_url

    url, _ = build_static_map_url(["BISHAN"], api_key=api_key)
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/")
