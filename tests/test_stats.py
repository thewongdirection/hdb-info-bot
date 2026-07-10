import json
from datetime import date
from pathlib import Path

import pytest

from hdb_bot.stats import parse_month, summarize

FIXTURES = Path(__file__).parent / "fixtures"
TODAY = date(2026, 7, 15)


def _load(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text())


def test_parse_month_valid():
    assert parse_month("2026-07") == (2026, 7)


@pytest.mark.parametrize("bad", ["", "not-a-month", "2026-13", "2026", None])
def test_parse_month_invalid(bad):
    assert parse_month(bad) is None


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
