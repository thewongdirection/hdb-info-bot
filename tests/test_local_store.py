from pathlib import Path

import pytest

from hdb_bot import local_store
from hdb_bot.datasets import DatasetInfo

DATASET_A = DatasetInfo(resource_id="d_a", label="A", group="resale",
                         price_field="resale_price", month_field="month")
DATASET_B = DatasetInfo(resource_id="d_b", label="B", group="resale",
                         price_field="resale_price", month_field="month")


@pytest.fixture(autouse=True)
def _clear_cache():
    local_store.invalidate_cache()
    yield
    local_store.invalidate_cache()


def _write_csv(path: Path, rows: list[str]) -> None:
    path.write_text("month,town,flat_type,resale_price\n" + "\n".join(rows) + "\n")


def test_load_town_records_filters_case_insensitively(tmp_path):
    _write_csv(
        tmp_path / "d_a.csv",
        ["2026-01,BISHAN,4 ROOM,500000", "2026-01,YISHUN,4 ROOM,400000"],
    )
    records = local_store.load_town_records([DATASET_A], "bishan", data_dir=tmp_path)
    assert len(records) == 1
    assert records[0]["town"] == "BISHAN"


def test_load_town_records_combines_multiple_datasets(tmp_path):
    _write_csv(tmp_path / "d_a.csv", ["2026-01,BISHAN,4 ROOM,500000"])
    _write_csv(tmp_path / "d_b.csv", ["2020-01,BISHAN,4 ROOM,400000"])
    records = local_store.load_town_records([DATASET_A, DATASET_B], "BISHAN", data_dir=tmp_path)
    assert len(records) == 2


def test_missing_csv_file_returns_empty_list_not_crash(tmp_path):
    records = local_store.load_town_records([DATASET_A], "BISHAN", data_dir=tmp_path)
    assert records == []


def test_rows_with_blank_town_are_skipped(tmp_path):
    _write_csv(tmp_path / "d_a.csv", ["2026-01,BISHAN,4 ROOM,500000", "2026-01,,4 ROOM,999999"])
    records = local_store.load_town_records([DATASET_A], "BISHAN", data_dir=tmp_path)
    assert len(records) == 1


def test_cache_is_reused_until_invalidated(tmp_path):
    csv_path = tmp_path / "d_a.csv"
    _write_csv(csv_path, ["2026-01,BISHAN,4 ROOM,500000"])
    first = local_store.load_town_records([DATASET_A], "BISHAN", data_dir=tmp_path)
    assert len(first) == 1

    # Mutate the file on disk without invalidating -> should still see the old cached result.
    _write_csv(csv_path, ["2026-01,BISHAN,4 ROOM,500000", "2026-02,BISHAN,4 ROOM,510000"])
    still_cached = local_store.load_town_records([DATASET_A], "BISHAN", data_dir=tmp_path)
    assert len(still_cached) == 1

    local_store.invalidate_cache()
    refreshed = local_store.load_town_records([DATASET_A], "BISHAN", data_dir=tmp_path)
    assert len(refreshed) == 2


def test_invalidate_cache_for_single_resource_id(tmp_path):
    _write_csv(tmp_path / "d_a.csv", ["2026-01,BISHAN,4 ROOM,500000"])
    _write_csv(tmp_path / "d_b.csv", ["2026-01,BISHAN,4 ROOM,600000"])
    local_store.load_town_records([DATASET_A, DATASET_B], "BISHAN", data_dir=tmp_path)

    local_store.invalidate_cache(DATASET_A.resource_id)

    assert DATASET_A.resource_id not in local_store._ingested
    assert DATASET_B.resource_id in local_store._ingested


def test_warm_cache_ingests_without_a_town_query(tmp_path):
    _write_csv(tmp_path / "d_a.csv", ["2026-01,BISHAN,4 ROOM,500000"])

    local_store.warm_cache([DATASET_A], data_dir=tmp_path)

    assert DATASET_A.resource_id in local_store._ingested
    # Ingestion already happened, so this read hits the warmed table directly.
    records = local_store.load_town_records([DATASET_A], "BISHAN", data_dir=tmp_path)
    assert len(records) == 1


def test_town_price_summary_groups_by_town_and_flat_type(tmp_path):
    _write_csv(
        tmp_path / "d_a.csv",
        [
            "2026-01,BISHAN,4 ROOM,500000",
            "2026-02,BISHAN,4 ROOM,520000",
            "2026-01,YISHUN,3 ROOM,300000",
        ],
    )
    rows = local_store.town_price_summary([DATASET_A], cutoff_period="2025-01", data_dir=tmp_path)
    by_key = {(r["town"], r["flat_type"]): r for r in rows}

    assert by_key[("BISHAN", "4 ROOM")]["count"] == 2
    assert by_key[("BISHAN", "4 ROOM")]["median"] == 510000
    assert by_key[("YISHUN", "3 ROOM")]["count"] == 1


def test_town_price_summary_respects_cutoff_period(tmp_path):
    _write_csv(
        tmp_path / "d_a.csv",
        ["2024-01,BISHAN,4 ROOM,400000", "2026-01,BISHAN,4 ROOM,500000"],
    )
    rows = local_store.town_price_summary([DATASET_A], cutoff_period="2025-01", data_dir=tmp_path)
    assert len(rows) == 1
    assert rows[0]["count"] == 1
    assert rows[0]["mean"] == 500000


def test_town_price_summary_filters_by_flat_type(tmp_path):
    _write_csv(
        tmp_path / "d_a.csv",
        ["2026-01,BISHAN,4 ROOM,500000", "2026-01,BISHAN,3 ROOM,300000"],
    )
    rows = local_store.town_price_summary(
        [DATASET_A], cutoff_period="2025-01", flat_type="3 ROOM", data_dir=tmp_path
    )
    assert len(rows) == 1
    assert rows[0]["flat_type"] == "3 ROOM"


def test_town_price_summary_combines_multiple_datasets(tmp_path):
    _write_csv(tmp_path / "d_a.csv", ["2026-01,BISHAN,4 ROOM,500000"])
    _write_csv(tmp_path / "d_b.csv", ["2026-02,BISHAN,4 ROOM,520000"])
    rows = local_store.town_price_summary(
        [DATASET_A, DATASET_B], cutoff_period="2025-01", data_dir=tmp_path
    )
    assert len(rows) == 1
    assert rows[0]["count"] == 2


def test_town_price_summary_empty_when_nothing_in_window(tmp_path):
    _write_csv(tmp_path / "d_a.csv", ["2024-01,BISHAN,4 ROOM,400000"])
    rows = local_store.town_price_summary([DATASET_A], cutoff_period="2025-01", data_dir=tmp_path)
    assert rows == []


def test_warm_cache_skips_already_ingested_datasets(tmp_path):
    csv_path = tmp_path / "d_a.csv"
    _write_csv(csv_path, ["2026-01,BISHAN,4 ROOM,500000"])
    local_store.load_town_records([DATASET_A], "BISHAN", data_dir=tmp_path)

    # Mutate the file without invalidating -> warm_cache should not re-ingest it.
    _write_csv(csv_path, ["2026-01,BISHAN,4 ROOM,500000", "2026-02,BISHAN,4 ROOM,510000"])
    local_store.warm_cache([DATASET_A], data_dir=tmp_path)

    records = local_store.load_town_records([DATASET_A], "BISHAN", data_dir=tmp_path)
    assert len(records) == 1
