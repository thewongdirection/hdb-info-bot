import json
from datetime import date
from pathlib import Path

import pytest

from hdb_bot.stats import (
    earliest_period,
    filter_recent,
    group_by_flat_type,
    monthly_average_series,
    parse_month,
    summarize,
)

FIXTURES = Path(__file__).parent / "fixtures"
TODAY = date(2026, 7, 15)


def _load(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text())


def test_parse_month_valid():
    assert parse_month("2026-07") == (2026, 7)


@pytest.mark.parametrize("bad", ["", "not-a-month", "2026-13", "2026", None])
def test_parse_month_invalid(bad):
    assert parse_month(bad) is None


def test_earliest_period_matches_hand_computed_cutoff():
    assert earliest_period(12, today=date(2026, 7, 11)) == "2025-08"
    assert earliest_period(1, today=date(2026, 7, 11)) == "2026-07"
    assert earliest_period(24, today=date(2026, 1, 15)) == "2024-02"


def test_earliest_period_agrees_with_filter_recent():
    """earliest_period() exists so a SQL query can filter with a plain
    string comparison instead of pulling every row into Python -- so it
    must draw exactly the same line as filter_recent()'s in-Python cutoff."""
    today = date(2026, 7, 15)
    records = [
        {"month": "2025-07"},  # one month before the 12-month cutoff
        {"month": "2025-08"},  # exactly at the cutoff
        {"month": "2026-07"},
    ]
    kept = filter_recent(records, "month", months_window=12, today=today)
    kept_months = {r["month"] for r in kept}

    cutoff = earliest_period(12, today=today)
    assert cutoff == "2025-08"
    assert kept_months == {"2025-08", "2026-07"}
    assert all(m >= cutoff for m in kept_months)
    assert "2025-07" not in kept_months


def test_summarize_empty_list_returns_empty():
    assert summarize([], price_field="resale_price", month_field="month", today=TODAY) == []


def test_summarize_resale_fixture_matches_expected():
    records = _load("sample_resale_records.json")
    stats = summarize(
        records, price_field="resale_price", month_field="month",
        months_window=12, today=TODAY,
    )
    by_type = {s.flat_type: s for s in stats}

    four_room = by_type["4 ROOM"]
    assert four_room.count == 27
    assert four_room.min == 520000.0
    assert four_room.max == 550000.0
    assert four_room.mean == pytest.approx(530000.0)
    assert four_room.median == pytest.approx(520000.0)
    assert four_room.p25 <= four_room.median <= four_room.p75
    assert four_room.trend_label == "up"
    assert four_room.trend_pct == pytest.approx(10.0)

    five_room = by_type["5 ROOM"]
    assert five_room.count == 3
    assert five_room.min == 700000.0
    assert five_room.max == 720000.0
    assert five_room.mean == pytest.approx(710000.0)
    assert five_room.median == pytest.approx(710000.0)
    # Only 1 of the 3 records falls in the last-3-months trend window.
    assert five_room.trend_label == "insufficient_data"
    assert five_room.trend_pct is None


def test_summarize_rental_fixture_matches_expected():
    records = _load("sample_rental_records.json")
    stats = summarize(
        records, price_field="monthly_rent", month_field="rent_approval_date",
        months_window=12, today=TODAY,
    )
    assert len(stats) == 1
    three_room = stats[0]
    assert three_room.flat_type == "3 ROOM"
    assert three_room.count == 27
    assert three_room.min == 1800.0
    assert three_room.max == 2100.0
    assert three_room.mean == pytest.approx(1900.0)
    assert three_room.median == pytest.approx(1800.0)
    assert three_room.trend_label == "up"
    assert three_room.trend_pct == pytest.approx(23.529, rel=1e-3)


def test_summarize_ignores_records_missing_price_or_month():
    records = [
        {"flat_type": "4 ROOM", "month": "2026-06", "resale_price": None},
        {"flat_type": "4 ROOM", "month": None, "resale_price": 500000},
        {"flat_type": "4 ROOM", "month": "2026-06", "resale_price": 500000},
    ]
    stats = summarize(records, price_field="resale_price", month_field="month", today=TODAY)
    assert len(stats) == 1
    assert stats[0].count == 1


def test_summarize_single_record_gives_flat_quantiles():
    records = [{"flat_type": "4 ROOM", "month": "2026-06", "resale_price": 500000}]
    stats = summarize(records, price_field="resale_price", month_field="month", today=TODAY)
    s = stats[0]
    assert s.count == 1
    assert s.min == s.max == s.mean == s.median == s.p25 == s.p75 == 500000.0


def test_monthly_average_series_computes_mean_per_month_sorted():
    records = [
        {"month": "2026-02", "resale_price": 500000},
        {"month": "2026-01", "resale_price": 400000},
        {"month": "2026-01", "resale_price": 420000},
    ]
    series = monthly_average_series(records, price_field="resale_price", month_field="month", today=TODAY)
    assert series == [("2026-01", 410000.0), ("2026-02", 500000.0)]


def test_monthly_average_series_respects_window():
    records = [
        {"month": "2020-01", "resale_price": 100000},  # far outside any reasonable window
        {"month": "2026-07", "resale_price": 600000},
    ]
    series = monthly_average_series(
        records, price_field="resale_price", month_field="month", months_window=12, today=TODAY
    )
    assert series == [("2026-07", 600000.0)]


def test_monthly_average_series_skips_missing_price_or_month():
    records = [
        {"month": "2026-06", "resale_price": None},
        {"month": None, "resale_price": 500000},
        {"month": "2026-06", "resale_price": 500000},
    ]
    series = monthly_average_series(records, price_field="resale_price", month_field="month", today=TODAY)
    assert series == [("2026-06", 500000.0)]


def test_monthly_average_series_empty_input():
    assert monthly_average_series([], price_field="resale_price", month_field="month", today=TODAY) == []


def test_group_by_flat_type_splits_correctly():
    records = [
        {"flat_type": "4 ROOM", "resale_price": 500000},
        {"flat_type": "3 ROOM", "resale_price": 400000},
        {"flat_type": "4 ROOM", "resale_price": 510000},
    ]
    grouped = group_by_flat_type(records)
    assert set(grouped.keys()) == {"4 ROOM", "3 ROOM"}
    assert len(grouped["4 ROOM"]) == 2
    assert len(grouped["3 ROOM"]) == 1


def test_group_by_flat_type_drops_records_missing_flat_type():
    records = [{"flat_type": "4 ROOM", "resale_price": 500000}, {"resale_price": 999999}]
    grouped = group_by_flat_type(records)
    assert list(grouped.keys()) == ["4 ROOM"]


def test_group_by_flat_type_empty_input():
    assert group_by_flat_type([]) == {}
