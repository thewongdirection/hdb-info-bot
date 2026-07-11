"""HDB carpark facility info + live availability.

Combines data.gov.sg's static "HDB Carpark Information" dataset (synced
locally like every other dataset — see data_sync.py / datasets.py) with its
real-time "Carpark Availability" API (queried live, since lots-available
changes minute to minute and can't be cached the same way as everything
else). Carpark locations come as SVY21 coordinates in the static dataset;
svy21.py converts them to lat/lng for free, with no geocoding API call.
"""
from __future__ import annotations

import csv
import logging
from pathlib import Path

import httpx

from .data_sync import default_data_dir
from .datasets import CARPARK_INFO_DATASET
from .maps import TOWN_CENTROIDS
from .svy21 import svy21_to_wgs84

logger = logging.getLogger(__name__)

AVAILABILITY_URL = "https://api.data.gov.sg/v1/transport/carpark-availability"
REQUEST_TIMEOUT = 15.0

_carpark_cache: list[dict] | None = None


def invalidate_cache() -> None:
    """Drop the in-memory carpark list so the next read re-parses from disk."""
    global _carpark_cache
    _carpark_cache = None


def _nearest_town(lat: float, lng: float) -> str:
    """Carparks have no `town` field, only coordinates — approximate by
    whichever HDB town centroid is closest. Singapore is small/flat enough
    that plain squared-degree distance is fine for "nearest of 26", no need
    for a real haversine calculation."""
    return min(
        TOWN_CENTROIDS,
        key=lambda town: (TOWN_CENTROIDS[town][0] - lat) ** 2 + (TOWN_CENTROIDS[town][1] - lng) ** 2,
    )


def _load_all_carparks(data_dir: Path) -> list[dict]:
    path = data_dir / f"{CARPARK_INFO_DATASET.resource_id}.csv"
    if not path.exists():
        logger.warning("No local cache file for HDB Carpark Information yet (%s)", path)
        return []

    carparks = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                x, y = float(row["x_coord"]), float(row["y_coord"])
            except (KeyError, ValueError, TypeError):
                continue
            lat, lng = svy21_to_wgs84(x, y)
            carparks.append(
                {
                    "car_park_no": (row.get("car_park_no") or "").strip(),
                    "address": (row.get("address") or "").strip(),
                    "lat": lat,
                    "lng": lng,
                    "car_park_type": (row.get("car_park_type") or "").strip(),
                    "type_of_parking_system": (row.get("type_of_parking_system") or "").strip(),
                    "short_term_parking": (row.get("short_term_parking") or "").strip(),
                    "free_parking": (row.get("free_parking") or "").strip(),
                    "night_parking": (row.get("night_parking") or "").strip(),
                    "nearest_town": _nearest_town(lat, lng),
                }
            )
    return carparks


def get_carparks_for_towns(towns: list[str], *, data_dir: Path | None = None) -> list[dict]:
    global _carpark_cache
    if _carpark_cache is None:
        _carpark_cache = _load_all_carparks(data_dir or default_data_dir())

    town_keys = {t.strip().upper() for t in towns}
    return [c for c in _carpark_cache if c["nearest_town"] in town_keys]


def _parse_lot(entry: dict) -> dict:
    try:
        lots_available: int | None = int(entry.get("lots_available"))
        total_lots: int | None = int(entry.get("total_lots"))
    except (TypeError, ValueError):
        lots_available = total_lots = None
    return {"lot_type": entry.get("lot_type"), "lots_available": lots_available, "total_lots": total_lots}


async def fetch_availability(
    api_key: str | None = None,
    *,
    timeout: float = REQUEST_TIMEOUT,
    client: httpx.AsyncClient | None = None,
) -> dict[str, dict]:
    """Live lots-available lookup, keyed by car_park_no.

    Each entry carries the *full* per-lot-type breakdown (a carpark can
    report separate counts for cars, heavy vehicles, etc. — see
    `join_availability`/formatting for how the "primary" figure and the
    full breakdown are both surfaced) plus when it was last updated.

    Never raises — returns {} on any failure so a flaky real-time API can't
    break the carpark listing; facility info still shows without live counts.
    Pass `client` to reuse an existing connection pool instead of paying a
    fresh TCP+TLS handshake for every carpark query.
    """
    headers = {"x-api-key": api_key} if api_key else {}
    try:
        if client is not None:
            resp = await client.get(AVAILABILITY_URL, headers=headers, timeout=timeout)
            resp.raise_for_status()
            payload = resp.json()
        else:
            async with httpx.AsyncClient(timeout=timeout) as new_client:
                resp = await new_client.get(AVAILABILITY_URL, headers=headers)
                resp.raise_for_status()
                payload = resp.json()
    except Exception as exc:
        logger.warning("Carpark availability API call failed: %s", exc)
        return {}

    items = payload.get("items") or []
    if not items:
        return {}

    result: dict[str, dict] = {}
    for entry in items[0].get("carpark_data", []):
        car_park_no = entry.get("carpark_number")
        if not car_park_no:
            continue
        lots = [_parse_lot(i) for i in entry.get("carpark_info", [])]
        if not lots:
            continue
        result[car_park_no] = {"lots": lots, "update_datetime": entry.get("update_datetime")}
    return result


def _primary_lot(lots: list[dict]) -> dict | None:
    """The lot-type entry to headline with — prefers "C" (car), the type
    present at almost every carpark, falling back to whatever's reported."""
    if not lots:
        return None
    return next((lot for lot in lots if lot.get("lot_type") == "C"), lots[0])


def join_availability(carparks: list[dict], availability: dict[str, dict]) -> list[dict]:
    """Merge live availability into carpark info dicts.

    Adds `lots` (the full per-lot-type breakdown), `update_datetime`, and
    `lots_available`/`total_lots`/`lot_type` (the "primary" figure, for the
    summary listing and sort order — see `_primary_lot`). Sorted with the
    most-available carparks first (most useful for a "where can I actually
    park" listing); carparks with no live data right now (not currently
    reporting) sort last, still shown with facility info.
    """
    enriched = []
    for c in carparks:
        avail = availability.get(c["car_park_no"], {})
        lots = avail.get("lots", [])
        primary = _primary_lot(lots) or {}
        enriched.append(
            {
                **c,
                "lots": lots,
                "update_datetime": avail.get("update_datetime"),
                "lots_available": primary.get("lots_available"),
                "total_lots": primary.get("total_lots"),
                "lot_type": primary.get("lot_type"),
            }
        )

    def sort_key(c: dict) -> tuple[int, int]:
        lots_available = c.get("lots_available")
        return (0 if lots_available is not None else 1, -(lots_available or 0))

    enriched.sort(key=sort_key)
    return enriched
