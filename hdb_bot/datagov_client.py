"""Client for data.gov.sg's dataset search API (datastore_search).

Uses the classic `GET /api/action/datastore_search?resource_id=...` endpoint,
which is still live and supports exact-match `filters` + `limit`/`offset`
pagination. There's no date-range filter in this API, so callers fetch all
rows for a town and do time-window filtering client-side (see stats.py).
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass

import httpx

from .cache import TTLCache

logger = logging.getLogger(__name__)

BASE_URL = "https://data.gov.sg/api/action/datastore_search"

# HDB resale flat prices, registration date from Jan 2017 onwards.
RESALE_RESOURCE_ID = "d_8b84c4ee58e3cfc0ece0d773c8ca6abc"
# HDB "Renting Out of Flats" (owner-declared), from Jan 2021 onwards.
RENTAL_RESOURCE_ID = "d_c9f57187485a850908655db0e8cfe651"

PAGE_SIZE = 1000
MAX_ROWS = 10_000
MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 1.0


@dataclass(frozen=True)
class DatasetSpec:
    resource_id: str
    price_field: str
    month_field: str


RESALE_DATASET = DatasetSpec(
    resource_id=RESALE_RESOURCE_ID, price_field="resale_price", month_field="month"
)
RENTAL_DATASET = DatasetSpec(
    resource_id=RENTAL_RESOURCE_ID, price_field="monthly_rent", month_field="rent_approval_date"
)

# buy/sell both look at the resale market from opposite sides of the same trade.
DATASET_FOR_INTENT: dict[str, DatasetSpec] = {
    "buy": RESALE_DATASET,
    "sell": RESALE_DATASET,
    "rent": RENTAL_DATASET,
}


class DataGovError(Exception):
    """Raised when data.gov.sg can't be reached or returns a failure payload."""


class DataGovClient:
    def __init__(
        self,
        api_key: str | None = None,
        cache_ttl_seconds: float = 21600,
        timeout: float = 15.0,
    ):
        self.api_key = api_key
        self.timeout = timeout
        self._cache = TTLCache(cache_ttl_seconds)

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self.api_key} if self.api_key else {}

    async def fetch_town_records(
        self, resource_id: str, town: str, *, max_rows: int = MAX_ROWS
    ) -> list[dict]:
        """Fetch every record for a given town, paginating until exhausted."""
        cache_key = (resource_id, town.upper())
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        records: list[dict] = []
        offset = 0
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            while len(records) < max_rows:
                params = {
                    "resource_id": resource_id,
                    "limit": PAGE_SIZE,
                    "offset": offset,
                    "filters": json.dumps({"town": town.upper()}),
                }
                payload = await self._get_with_retry(client, params)
                batch = payload.get("result", {}).get("records", [])
                records.extend(batch)
                if len(batch) < PAGE_SIZE:
                    break
                offset += PAGE_SIZE

        records = records[:max_rows]
        self._cache.set(cache_key, records)
        return records

    async def _get_with_retry(self, client: httpx.AsyncClient, params: dict) -> dict:
        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = await client.get(BASE_URL, params=params, headers=self._headers())
            except httpx.HTTPError as exc:
                last_exc = exc
                logger.warning("data.gov.sg request error (attempt %d): %s", attempt + 1, exc)
                await asyncio.sleep(BASE_BACKOFF_SECONDS * (2**attempt))
                continue

            if resp.status_code == 429 or resp.status_code >= 500:
                last_exc = DataGovError(f"HTTP {resp.status_code} from data.gov.sg")
                logger.warning(
                    "data.gov.sg returned %d (attempt %d)", resp.status_code, attempt + 1
                )
                await asyncio.sleep(BASE_BACKOFF_SECONDS * (2**attempt))
                continue

            resp.raise_for_status()
            payload = resp.json()
            if not payload.get("success", False):
                raise DataGovError(f"data.gov.sg reported failure: {payload}")
            return payload

        raise DataGovError(
            f"data.gov.sg request failed after {MAX_RETRIES} attempts"
        ) from last_exc
