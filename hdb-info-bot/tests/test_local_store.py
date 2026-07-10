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

    assert DATASET_A.resource_id not in local_store._index_cache
    assert DATASET_B.resource_id in local_store._index_cache
