"""Downloads and refreshes local CSV copies of every dataset in `datasets.py`.

The bot's conversation flow never queries data.gov.sg live at request time —
it reads from these local copies via `local_store.py`. This module is the
only thing that talks to data.gov.sg for data, and it does so on two
occasions: once at startup (blocking, so the bot has data immediately) and
then periodically in the background (see `main.py`'s job queue).

Uses data.gov.sg's bulk CSV download flow (initiate-download + poll-download,
returning a signed S3 URL) rather than paginating datastore_search — a single
CSV fetch instead of hundreds of small JSON requests. Before downloading,
each dataset's metadata `lastUpdatedAt` timestamp is checked against a local
manifest so unchanged datasets (which is most of them, most of the time)
are skipped entirely.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from .datasets import ALL_DATASETS, DatasetInfo

logger = logging.getLogger(__name__)

METADATA_BASE = "https://api-production.data.gov.sg/v2/public/api/datasets"
DOWNLOAD_BASE = "https://api-open.data.gov.sg/v1/public/api/datasets"

MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 1.0
POLL_ATTEMPTS = 10
POLL_INTERVAL_SECONDS = 2.0
DEFAULT_TIMEOUT_SECONDS = 120.0


def default_data_dir() -> Path:
    """hdb_bot/data_sync.py -> hdb_bot/ -> <hdb-info-bot subfolder>/data"""
    return Path(__file__).resolve().parent.parent / "data"


@dataclass
class SyncResult:
    resource_id: str
    label: str
    changed: bool
    row_count: int | None
    error: str | None = None


class DataSyncError(Exception):
    """Raised when data.gov.sg can't be reached for metadata or a download."""


class DataSyncer:
    def __init__(
        self,
        data_dir: Path | None = None,
        api_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ):
        self.data_dir = data_dir or default_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.api_key = api_key
        self.timeout = timeout
        self.manifest_path = self.data_dir / "manifest.json"
        self._manifest: dict = self._load_manifest()

    def csv_path(self, resource_id: str) -> Path:
        return self.data_dir / f"{resource_id}.csv"

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self.api_key} if self.api_key else {}

    def _load_manifest(self) -> dict:
        if self.manifest_path.exists():
            try:
                return json.loads(self.manifest_path.read_text())
            except (json.JSONDecodeError, OSError):
                logger.warning("Could not parse manifest at %s, starting fresh", self.manifest_path)
        return {}

    def _save_manifest(self) -> None:
        self.manifest_path.write_text(json.dumps(self._manifest, indent=2))

    async def _get_with_retry(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = await client.get(url, headers=self._headers())
            except httpx.HTTPError as exc:
                last_exc = exc
                logger.warning("Request error for %s (attempt %d): %s", url, attempt + 1, exc)
                await asyncio.sleep(BASE_BACKOFF_SECONDS * (2**attempt))
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                last_exc = DataSyncError(f"HTTP {resp.status_code} from {url}")
                await asyncio.sleep(BASE_BACKOFF_SECONDS * (2**attempt))
                continue
            return resp
        raise DataSyncError(f"Request to {url} failed after {MAX_RETRIES} attempts") from last_exc

    async def _fetch_metadata(self, client: httpx.AsyncClient, resource_id: str) -> dict:
        resp = await self._get_with_retry(client, f"{METADATA_BASE}/{resource_id}/metadata")
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("code") != 0:
            raise DataSyncError(f"metadata error for {resource_id}: {payload}")
        return payload["data"]

    async def _get_download_url(self, client: httpx.AsyncClient, resource_id: str) -> str:
        await self._get_with_retry(client, f"{DOWNLOAD_BASE}/{resource_id}/initiate-download")
        for _ in range(POLL_ATTEMPTS):
            resp = await self._get_with_retry(client, f"{DOWNLOAD_BASE}/{resource_id}/poll-download")
            resp.raise_for_status()
            url = resp.json().get("data", {}).get("url")
            if url:
                return url
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
        raise DataSyncError(f"Timed out waiting for a download URL for {resource_id}")

    async def sync_dataset(self, dataset: DatasetInfo, *, force: bool = False) -> SyncResult:
        entry = self._manifest.get(dataset.resource_id, {})

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            upstream_updated: str | None = None
            try:
                meta = await self._fetch_metadata(client, dataset.resource_id)
                upstream_updated = meta.get("lastUpdatedAt")
            except Exception as exc:
                logger.warning(
                    "Could not fetch metadata for %s, will re-download to be safe: %s",
                    dataset.resource_id, exc,
                )

            already_fresh = (
                not force
                and self.csv_path(dataset.resource_id).exists()
                and upstream_updated is not None
                and entry.get("last_updated_at") == upstream_updated
            )
            if already_fresh:
                return SyncResult(
                    dataset.resource_id, dataset.label, changed=False, row_count=entry.get("row_count")
                )

            try:
                csv_url = await self._get_download_url(client, dataset.resource_id)
                resp = await client.get(csv_url, timeout=self.timeout)
                resp.raise_for_status()
            except Exception as exc:
                return SyncResult(
                    dataset.resource_id, dataset.label, changed=False,
                    row_count=entry.get("row_count"), error=str(exc),
                )
            content = resp.content

        self.csv_path(dataset.resource_id).write_bytes(content)
        row_count = max(content.count(b"\n") - 1, 0)
        self._manifest[dataset.resource_id] = {
            "label": dataset.label,
            "last_updated_at": upstream_updated,
            "synced_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "row_count": row_count,
        }
        self._save_manifest()
        return SyncResult(dataset.resource_id, dataset.label, changed=True, row_count=row_count)

    async def sync_all(self, *, force: bool = False) -> list[SyncResult]:
        results = []
        for dataset in ALL_DATASETS:
            result = await self.sync_dataset(dataset, force=force)
            results.append(result)
            if result.error:
                logger.error("Sync failed for %s: %s", dataset.label, result.error)
            elif result.changed:
                logger.info("Synced %s: %s rows", dataset.label, result.row_count)
            else:
                logger.debug("%s already up to date", dataset.label)
        return results
