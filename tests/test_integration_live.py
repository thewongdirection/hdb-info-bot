"""Live checks against the real data.gov.sg / Google Maps APIs.

Excluded from the default `pytest` run (see pytest.ini) since they need
network access, take a while (real dataset downloads), and can be affected
by upstream rate limits or schema changes. Run explicitly with: pytest -m live
"""
import os
import tempfile
from pathlib import Path

import httpx
import pytest

from hdb_bot.data_sync import DataSyncer
from hdb_bot.datasets import RESALE_DATASETS, RENTAL_DATASETS

pytestmark = pytest.mark.live


async def test_live_metadata_and_download_for_latest_resale_dataset():
    dataset = RESALE_DATASETS[-1]
    with tempfile.TemporaryDirectory() as tmp:
        syncer = DataSyncer(data_dir=Path(tmp), api_key=os.environ.get("DATA_GOV_SG_API_KEY"))
        result = await syncer.sync_dataset(dataset)
        assert result.error is None, f"sync failed: {result.error}"
        assert result.row_count and result.row_count > 0

        csv_text = syncer.csv_path(dataset.resource_id).read_text(encoding="utf-8")
        header = csv_text.splitlines()[0]
        for field in ("month", "town", "flat_type", "resale_price"):
            assert field in header, f"upstream schema may have changed, missing {field!r}"


async def test_live_metadata_for_rental_dataset():
    dataset = RENTAL_DATASETS[0]
    with tempfile.TemporaryDirectory() as tmp:
        syncer = DataSyncer(data_dir=Path(tmp), api_key=os.environ.get("DATA_GOV_SG_API_KEY"))
        result = await syncer.sync_dataset(dataset)
        assert result.error is None, f"sync failed: {result.error}"
        assert result.row_count and result.row_count > 0


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
