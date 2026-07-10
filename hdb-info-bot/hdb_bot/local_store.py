"""Serves town-filtered records from the locally-cached dataset CSVs.

The conversation flow calls `load_town_records()` — it never queries
data.gov.sg directly; only `data_sync.py` does that (see main.py's periodic
sync job). Each dataset CSV is parsed once and indexed by town in memory;
`invalidate_cache()` is called after a sync changes any file so the next
read picks up fresh data.
"""
from __future__ import annotations

import csv
import logging
from pathlib import Path

from .data_sync import default_data_dir
from .datasets import DatasetInfo

logger = logging.getLogger(__name__)

_index_cache: dict[str, dict[str, list[dict]]] = {}


def invalidate_cache(resource_id: str | None = None) -> None:
    """Drop cached town-indexes so the next read re-parses from disk.

    Pass a specific resource_id to invalidate just that dataset, or omit it
    to clear everything (used after a sync run that changed any file).
    """
    if resource_id is None:
        _index_cache.clear()
    else:
        _index_cache.pop(resource_id, None)


def _load_index(dataset: DatasetInfo, data_dir: Path) -> dict[str, list[dict]]:
    cached = _index_cache.get(dataset.resource_id)
    if cached is not None:
        return cached

    path = data_dir / f"{dataset.resource_id}.csv"
    index: dict[str, list[dict]] = {}
    if not path.exists():
        logger.warning(
            "No local cache file for %s yet (%s) — has the initial sync run?",
            dataset.label, path,
        )
        _index_cache[dataset.resource_id] = index
        return index

    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            town = (row.get("town") or "").strip().upper()
            if not town:
                continue
            index.setdefault(town, []).append(row)

    _index_cache[dataset.resource_id] = index
    return index


def load_town_records(
    datasets: list[DatasetInfo], town: str, *, data_dir: Path | None = None
) -> list[dict]:
    """Return every record for `town` across all the given datasets."""
    data_dir = data_dir or default_data_dir()
    town_key = town.strip().upper()
    records: list[dict] = []
    for dataset in datasets:
        index = _load_index(dataset, data_dir)
        records.extend(index.get(town_key, []))
    return records
