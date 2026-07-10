import httpx
import pytest
import respx

from hdb_bot import datagov_client
from hdb_bot.datagov_client import DataGovClient, DataGovError

RESOURCE_ID = "d_test_resource"


def _payload(records: list[dict]) -> dict:
    return {"success": True, "result": {"resource_id": RESOURCE_ID, "records": records, "total": len(records)}}


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    async def _instant_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setattr(datagov_client.asyncio, "sleep", _instant_sleep)


@respx.mock
async def test_fetch_single_page_and_cache_hits():
    route = respx.get(datagov_client.BASE_URL).mock(
        return_value=httpx.Response(200, json=_payload([{"town": "BISHAN"}, {"town": "BISHAN"}]))
    )
    client = DataGovClient()

    records = await client.fetch_town_records(RESOURCE_ID, "bishan")
    assert len(records) == 2
    assert route.call_count == 1

    # Second call for the same (resource_id, town) should be served from cache.
    again = await client.fetch_town_records(RESOURCE_ID, "BISHAN")
    assert again == records
    assert route.call_count == 1


@respx.mock
async def test_pagination_across_multiple_pages(monkeypatch):
    monkeypatch.setattr(datagov_client, "PAGE_SIZE", 2)
    page1 = _payload([{"i": 1}, {"i": 2}])
    page2 = _payload([{"i": 3}])  # shorter than PAGE_SIZE -> last page
    respx.get(datagov_client.BASE_URL).mock(
        side_effect=[httpx.Response(200, json=page1), httpx.Response(200, json=page2)]
    )
    client = DataGovClient()

    records = await client.fetch_town_records(RESOURCE_ID, "bedok")
    assert [r["i"] for r in records] == [1, 2, 3]


@respx.mock
async def test_retries_on_500_then_succeeds():
    respx.get(datagov_client.BASE_URL).mock(
        side_effect=[httpx.Response(500), httpx.Response(200, json=_payload([{"town": "YISHUN"}]))]
    )
    client = DataGovClient()
    records = await client.fetch_town_records(RESOURCE_ID, "yishun")
    assert len(records) == 1


@respx.mock
async def test_retries_exhausted_raises():
    respx.get(datagov_client.BASE_URL).mock(return_value=httpx.Response(500))
    client = DataGovClient()
    with pytest.raises(DataGovError):
        await client.fetch_town_records(RESOURCE_ID, "yishun")


@respx.mock
async def test_success_false_payload_raises():
    respx.get(datagov_client.BASE_URL).mock(
        return_value=httpx.Response(200, json={"success": False, "error": "bad resource_id"})
    )
    client = DataGovClient()
    with pytest.raises(DataGovError):
        await client.fetch_town_records(RESOURCE_ID, "yishun")


@respx.mock
async def test_api_key_header_sent_when_configured():
    route = respx.get(datagov_client.BASE_URL).mock(return_value=httpx.Response(200, json=_payload([])))
    client = DataGovClient(api_key="secret123")
    await client.fetch_town_records(RESOURCE_ID, "yishun")
    assert route.calls[0].request.headers["x-api-key"] == "secret123"


@respx.mock
async def test_no_api_key_header_when_not_configured():
    route = respx.get(datagov_client.BASE_URL).mock(return_value=httpx.Response(200, json=_payload([])))
    client = DataGovClient()
    await client.fetch_town_records(RESOURCE_ID, "yishun")
    assert "x-api-key" not in route.calls[0].request.headers


@respx.mock
async def test_empty_result_set():
    respx.get(datagov_client.BASE_URL).mock(return_value=httpx.Response(200, json=_payload([])))
    client = DataGovClient()
    records = await client.fetch_town_records(RESOURCE_ID, "sembawang")
    assert records == []
