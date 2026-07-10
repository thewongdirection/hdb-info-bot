import httpx
import pytest
import respx

from hdb_bot.geocoding import GeocodeCache, geocode_many

API_KEY = "fake-key"


def _ok_response(lat: float, lng: float) -> httpx.Response:
    return httpx.Response(
        200,
        json={"status": "OK", "results": [{"geometry": {"location": {"lat": lat, "lng": lng}}}]},
    )


def _zero_results_response() -> httpx.Response:
    return httpx.Response(200, json={"status": "ZERO_RESULTS", "results": []})


@respx.mock
async def test_geocode_many_resolves_and_caches(tmp_path):
    route = respx.get("https://maps.googleapis.com/maps/api/geocode/json").mock(
        return_value=_ok_response(1.35, 103.85)
    )
    cache = GeocodeCache(tmp_path / "cache.json")

    result = await geocode_many(["123 Bishan St 11"], API_KEY, cache)

    assert result == {"123 Bishan St 11": (1.35, 103.85)}
    assert route.call_count == 1

    # Second call for the same address should be served from the persisted cache.
    cache2 = GeocodeCache(tmp_path / "cache.json")
    result2 = await geocode_many(["123 Bishan St 11"], API_KEY, cache2)
    assert result2 == {"123 Bishan St 11": (1.35, 103.85)}
    assert route.call_count == 1  # no new HTTP request


@respx.mock
async def test_zero_results_is_cached_as_unresolvable(tmp_path):
    route = respx.get("https://maps.googleapis.com/maps/api/geocode/json").mock(
        return_value=_zero_results_response()
    )
    cache = GeocodeCache(tmp_path / "cache.json")

    result = await geocode_many(["nonsense address"], API_KEY, cache)
    assert result == {}
    assert route.call_count == 1

    # Repeat: still cached as unresolvable, no second HTTP call.
    result2 = await geocode_many(["nonsense address"], API_KEY, cache)
    assert result2 == {}
    assert route.call_count == 1


@respx.mock
async def test_transient_api_error_is_not_cached(tmp_path):
    route = respx.get("https://maps.googleapis.com/maps/api/geocode/json").mock(
        side_effect=[
            httpx.Response(200, json={"status": "OVER_QUERY_LIMIT", "results": []}),
            _ok_response(1.3, 103.8),
        ]
    )
    cache = GeocodeCache(tmp_path / "cache.json")

    first = await geocode_many(["some address"], API_KEY, cache)
    assert first == {}  # failed, not cached

    second = await geocode_many(["some address"], API_KEY, cache)
    assert second == {"some address": (1.3, 103.8)}
    assert route.call_count == 2


@respx.mock
async def test_geocode_many_handles_mixed_batch(tmp_path):
    def _router(request: httpx.Request) -> httpx.Response:
        address = request.url.params["address"]
        if "good" in address:
            return _ok_response(1.3, 103.8)
        return _zero_results_response()

    respx.get("https://maps.googleapis.com/maps/api/geocode/json").mock(side_effect=_router)
    cache = GeocodeCache(tmp_path / "cache.json")

    result = await geocode_many(["good address", "bad address"], API_KEY, cache)
    assert result == {"good address": (1.3, 103.8)}


async def test_geocode_many_skips_network_when_all_cached(tmp_path):
    cache = GeocodeCache(tmp_path / "cache.json")
    cache.set("known address", (1.1, 103.1))
    cache.save()

    with respx.mock:
        # No routes registered — any HTTP call would raise.
        result = await geocode_many(["known address"], API_KEY, cache)

    assert result == {"known address": (1.1, 103.1)}
