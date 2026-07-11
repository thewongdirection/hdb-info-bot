"""Serves town-filtered records from a local SQLite cache of the dataset CSVs.

The conversation flow calls `load_town_records()` — it never queries
data.gov.sg directly; only `data_sync.py` does that (see main.py's periodic
sync job). This module owns turning each synced CSV into a queryable local
store: rows are ingested into a SQLite table (stdlib `sqlite3`, no new
dependency) indexed by `(resource_id, town)`, rather than being parsed into
one big Python dict-of-lists that stays resident in memory for the whole
process lifetime.

That distinction matters at this data's scale (~1.2M rows across all
datasets combined). A Python dict per row has real object overhead per
row, and holding *every* row for *every* town forever means peak memory
only ever grows. With SQLite, ingestion happens in bounded batches (so
peak memory during a (re-)ingest is capped at one batch, not the whole
dataset), the bulk of the data lives in the SQLite file — backed by the
OS page cache rather than Python object graphs — and each `load_town_records`
call only ever materializes the rows for the one town actually asked for,
which get garbage collected once that request finishes.

Only `flat_type`, `block`, `street_name`, and the dataset's own price/month
fields are ever read by the rest of the codebase (stats.py, formatting.py,
conversation.py), so those are the only columns stored — everything else in
the raw CSV (storey_range, floor_area_sqm, flat_model, lease_commence_date,
remaining_lease, ...) is dropped at ingest time.

`invalidate_cache()` marks a dataset (or all of them) for re-ingestion on
the next `load_town_records()` call — mirroring the old dict-cache's
contract exactly: mutating a CSV on disk has no effect until
`invalidate_cache()` is called (done by main.py's sync job after a dataset
actually changes), at which point the *next* read re-ingests from disk.
"""
from __future__ import annotations

import csv
import logging
import sqlite3
from pathlib import Path

from .data_sync import default_data_dir
from .datasets import DatasetInfo

logger = logging.getLogger(__name__)

_DB_FILENAME = "records.sqlite3"
_INGEST_BATCH_SIZE = 5000

# Which resource_ids currently have up-to-date rows in the SQLite table.
# Cleared (in full or per-resource_id) by invalidate_cache(); repopulated
# lazily the next time load_town_records() needs that dataset.
_ingested: set[str] = set()


def invalidate_cache(resource_id: str | None = None) -> None:
    """Mark cached dataset(s) as stale so the next read re-ingests from disk.

    Pass a specific resource_id to invalidate just that dataset, or omit it
    to mark everything stale (used after a sync run that changed any file).
    """
    if resource_id is None:
        _ingested.clear()
    else:
        _ingested.discard(resource_id)


def _db_path(data_dir: Path) -> Path:
    return data_dir / _DB_FILENAME


def _connect(data_dir: Path) -> sqlite3.Connection:
    data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_db_path(data_dir))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS records (
            resource_id TEXT NOT NULL,
            town TEXT NOT NULL,
            flat_type TEXT,
            block TEXT,
            street_name TEXT,
            price REAL,
            period TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_records_resource_town ON records(resource_id, town)"
    )
    return conn


def _ingest(dataset: DatasetInfo, data_dir: Path, conn: sqlite3.Connection) -> None:
    """(Re-)load `dataset`'s CSV into the records table, replacing any rows
    already stored for its resource_id. No-op (but still marks the dataset
    as ingested) if the CSV hasn't been synced down yet."""
    path = data_dir / f"{dataset.resource_id}.csv"
    conn.execute("DELETE FROM records WHERE resource_id = ?", (dataset.resource_id,))

    if not path.exists():
        logger.warning(
            "No local cache file for %s yet (%s) — has the initial sync run?",
            dataset.label, path,
        )
        conn.commit()
        _ingested.add(dataset.resource_id)
        return

    price_field = dataset.price_field
    month_field = dataset.month_field
    insert_sql = (
        "INSERT INTO records (resource_id, town, flat_type, block, street_name, price, period) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)"
    )

    batch: list[tuple] = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            town = (row.get("town") or "").strip().upper()
            if not town:
                continue

            price = None
            if price_field:
                raw_price = row.get(price_field)
                if raw_price:
                    try:
                        price = float(raw_price)
                    except ValueError:
                        price = None
            period = (row.get(month_field) or "").strip() if month_field else None

            batch.append((
                dataset.resource_id,
                town,
                (row.get("flat_type") or "").strip(),
                (row.get("block") or "").strip(),
                (row.get("street_name") or "").strip(),
                price,
                period,
            ))
            if len(batch) >= _INGEST_BATCH_SIZE:
                conn.executemany(insert_sql, batch)
                batch.clear()

    if batch:
        conn.executemany(insert_sql, batch)

    conn.commit()
    _ingested.add(dataset.resource_id)


def load_town_records(
    datasets: list[DatasetInfo], town: str, *, data_dir: Path | None = None
) -> list[dict]:
    """Return every record for `town` across all the given datasets."""
    data_dir = data_dir or default_data_dir()
    town_key = town.strip().upper()

    conn = _connect(data_dir)
    try:
        records: list[dict] = []
        for dataset in datasets:
            if dataset.resource_id not in _ingested:
                _ingest(dataset, data_dir, conn)

            cur = conn.execute(
                "SELECT town, flat_type, block, street_name, price, period "
                "FROM records WHERE resource_id = ? AND town = ?",
                (dataset.resource_id, town_key),
            )
            for town_val, flat_type, block, street_name, price, period in cur.fetchall():
                record: dict = {
                    "town": town_val,
                    "flat_type": flat_type,
                    "block": block,
                    "street_name": street_name,
                }
                if dataset.price_field:
                    record[dataset.price_field] = price
                if dataset.month_field:
                    record[dataset.month_field] = period
                records.append(record)
        return records
    finally:
        conn.close()
