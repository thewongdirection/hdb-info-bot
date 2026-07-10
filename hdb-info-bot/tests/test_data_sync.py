import httpx
import pytest
import respx

from hdb_bot import data_sync
from hdb_bot.data_sync import DataSyncer
from hdb_bot.datasets import DatasetInfo

RID = "d_test_dataset"
DATASET = DatasetInfo(resource_id=RID, label="Test Dataset", group="resale",
                       price_field="resale_price", month_field="month")

METADATA_URL = f"{data_sync.METADATA_BASE}/{RID}/metadata"
INITIATE_URL = f"{data_sync.DOWNLOAD_BASE}/{RID}/initiate-download"
POLL_URL = f"{data_sync.DOWNLOAD_BASE}/{RID}/poll-download"
CSV_URL = "https://fake-s3.example.com/dataset.csv"
CSV_BODY = b"month,town,flat_type,resale_price\n2026-01,BISHAN,4 ROOM,500000\n"


def _metadata_response(last_updated: str) -> httpx.Response:
    return httpx.Response(200, json={"code": 0, "data": {"lastUpdatedAt": last_updated}})


def _download_flow(monkeypatch=None):
    respx.get(INITIATE_URL).mock(return_value=httpx.Response(201, json={"code": 0, "data": {}}))
    respx.get(POLL_URL).mock(
        return_value=httpx.Response(201, json={"code": 0, "data": {"status": "DOWNLOAD_SUCCESS", "url": CSV_URL}})
    )
    respx.get(CSV_URL).mock(return_value=httpx.Response(200, content=CSV_BODY))


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    async def _instant_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setattr(data_sync.asyncio, "sleep", _instant_sleep)


@respx.mock
async def test_first_sync_downloads_and_writes_manifest(tmp_path):
    respx.get(METADATA_URL).mock(return_value=_metadata_response("2026-01-01T00:00:00+08:00"))
    _download_flow()

    syncer = DataSyncer(data_dir=tmp_path)
    result = await syncer.sync_dataset(DATASET)

    assert result.changed is True
    assert result.error is None
    assert result.row_count == 1
    assert syncer.csv_path(RID).read_bytes() == CSV_BODY
    assert syncer.manifest_path.exists()


@respx.mock
async def test_second_sync_with_unchanged_metadata_skips_download(tmp_path):
    respx.get(METADATA_URL).mock(return_value=_metadata_response("2026-01-01T00:00:00+08:00"))
    _download_flow()

    syncer = DataSyncer(data_dir=tmp_path)
    await syncer.sync_dataset(DATASET)
    csv_route = respx.get(CSV_URL)
    calls_before = csv_route.call_count

    result = await syncer.sync_dataset(DATASET)

    assert result.changed is False
    assert csv_route.call_count == calls_before  # no re-download


@respx.mock
async def test_metadata_change_triggers_redownload(tmp_path):
    metadata_route = respx.get(METADATA_URL).mock(return_value=_metadata_response("2026-01-01T00:00:00+08:00"))
    _download_flow()

    syncer = DataSyncer(data_dir=tmp_path)
    await syncer.sync_dataset(DATASET)

    metadata_route.mock(return_value=_metadata_response("2026-02-01T00:00:00+08:00"))
    result = await syncer.sync_dataset(DATASET)

    assert result.changed is True


@respx.mock
async def test_force_redownloads_even_if_unchanged(tmp_path):
    respx.get(METADATA_URL).mock(return_value=_metadata_response("2026-01-01T00:00:00+08:00"))
    _download_flow()

    syncer = DataSyncer(data_dir=tmp_path)
    await syncer.sync_dataset(DATASET)
    result = await syncer.sync_dataset(DATASET, force=True)

    assert result.changed is True


@respx.mock
async def test_metadata_failure_still_attempts_download(tmp_path):
    respx.get(METADATA_URL).mock(return_value=httpx.Response(500))
    _download_flow()

    syncer = DataSyncer(data_dir=tmp_path)
    result = await syncer.sync_dataset(DATASET)

    assert result.error is None
    assert result.changed is True  # couldn't confirm freshness, so it downloaded


@respx.mock
async def test_download_failure_returns_error_without_crashing(tmp_path):
    respx.get(METADATA_URL).mock(return_value=_metadata_response("2026-01-01T00:00:00+08:00"))
    respx.get(INITIATE_URL).mock(return_value=httpx.Response(500))

    syncer = DataSyncer(data_dir=tmp_path)
    result = await syncer.sync_dataset(DATASET)

    assert result.error is not None
    assert result.changed is False


@respx.mock
async def test_sync_all_iterates_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(data_sync, "ALL_DATASETS", [DATASET])
    respx.get(METADATA_URL).mock(return_value=_metadata_response("2026-01-01T00:00:00+08:00"))
    _download_flow()

    syncer = DataSyncer(data_dir=tmp_path)
    results = await syncer.sync_all()

    assert len(results) == 1
    assert results[0].resource_id == RID
