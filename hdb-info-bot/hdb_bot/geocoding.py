"""Geocodes HDB block addresses to lat/lng using the Google Geocoding API.

HDB blocks don't move, so results are cached to disk forever — a given
block only ever needs to be geocoded once across the bot's whole lifetime,
which keeps the (small, cache-backed) Geocoding API cost negligible.

Uses the same GOOGLE_MAPS_API_KEY as maps.py — just needs the "Geocoding
API" enabled alongside "Maps Static API" on that key's GCP project.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import httpx

from .data_sync import default_data_dir

logger = logging.getLogger(__name__)

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
DEFAULT_CONCURRENCY = 5
REQUEST_TIMEOUT = 10.0


def default_cache_path() -> Path:
    return default_data_dir() / "geocode_cache.json"


class GeocodeCache:
    """address -> [lat, lng] or None (a confirmed non-geocodable address)."""

    def __init__(self, path: Path | None = None):
        self.path = path or default_cache_path()
        self._store: dict[str, list[float] | None] = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text())
            except (json.JSONDecodeError, OSError):
                logger.warning("Could not parse geocode cache at %s, starting fresh", self.path)
        return {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._store, indent=2))

    def get(self, address: str) -> tuple[float, float] | None | Ellipsis:
        """Returns coords, None (known unresolvable), or Ellipsis (not cached)."""
        if address not in self._store:
            return Ellipsis
        value = self._store[address]
        return tuple(value) if value is not None else None

    def set(self, address: str, coords: tuple[float, float] | None) -> None:
        self._store[address] = list(coords) if coords is not None else None


async def _geocode_one(
    client: httpx.AsyncClient, address: str, api_key: str
) -> tuple[float, float] | None:
    resp = await client.get(
        GEOCODE_URL, params={"address": f"{address}, Singapore", "key": api_key}
    )
    resp.raise_for_status()
    payload = resp.json()
    status = payload.get("status")

    if status == "OK" and payload.get("results"):
        location = payload["results"][0]["geometry"]["location"]
        return location["lat"], location["lng"]
    if status == "ZERO_RESULTS":
        return None
    # Anything else (rate limit, invalid key, server error) is transient/
    # config trouble, not "this address doesn't exist" — don't cache it.
    raise RuntimeError(f"Geocoding API returned {status} for {address!r}")


async def geocode_many(
    addresses: list[str],
    api_key: str,
    cache: GeocodeCache,
    *,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> dict[str, tuple[float, float]]:
    """Geocode a batch of addresses, using and updating the disk cache.

    Returns only the addresses that resolved to coordinates; unresolvable
    or failed addresses are simply omitted (never raises for individual
    address failures — a bad block shouldn't take down the whole map).
    """
    results: dict[str, tuple[float, float]] = {}
    to_fetch: list[str] = []

    for address in addresses:
        cached = cache.get(address)
        if cached is Ellipsis:
            to_fetch.append(address)
        elif cached is not None:
            results[address] = cached

    if to_fetch:
        semaphore = asyncio.Semaphore(concurrency)

        async def _fetch(address: str, client: httpx.AsyncClient) -> None:
            async with semaphore:
                try:
                    coords = await _geocode_one(client, address, api_key)
                except Exception as exc:
                    logger.warning("Geocoding failed for %r: %s", address, exc)
                    return
                cache.set(address, coords)
                if coords is not None:
                    results[address] = coords

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            await asyncio.gather(*(_fetch(a, client) for a in to_fetch))
        cache.save()

    return results
