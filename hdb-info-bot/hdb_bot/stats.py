"""Pure statistics functions over data.gov.sg HDB transaction records.

Kept dependency-free (stdlib `statistics` only) and free of any Telegram/HTTP
concerns so it's trivial to unit test with plain fixture lists.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date


@dataclass
class FlatTypeStats:
    flat_type: str
    count: int
    min: float
    max: float
    mean: float
    median: float
    p25: float
    p75: float
    trend_pct: float | None  # None => not enough history to compute
    trend_label: str  # "up" | "down" | "flat" | "insufficient_data"


def _month_index(year: int, month: int) -> int:
    return year * 12 + month


def parse_month(value: str) -> tuple[int, int] | None:
    """Parse a "YYYY-MM" style string into (year, month), or None if malformed."""
    try:
        year_str, month_str = value.strip().split("-")[:2]
        year, month = int(year_str), int(month_str)
        if 1 <= month <= 12:
            return year, month
    except (ValueError, AttributeError):
        pass
    return None


def filter_recent(
    records: list[dict],
    month_field: str,
    months_window: int = 12,
    today: date | None = None,
) -> list[dict]:
    """Return only the records within the last `months_window` months.

    Uses the same cutoff definition as `summarize()`'s headline stats, so
    callers that need the exact same "recent" record set (e.g. to plot the
    blocks behind those stats on a map) can filter independently of price
    grouping.
    """
    today = today or date.today()
    now_index = _month_index(today.year, today.month)
    cutoff_index = now_index - months_window

    recent = []
    for r in records:
        parsed = parse_month(str(r.get(month_field, "")))
        if parsed is None:
            continue
        if _month_index(*parsed) > cutoff_index:
            recent.append(r)
    return recent


def group_by_flat_type(records: list[dict]) -> dict[str, list[dict]]:
    """Split records into per-flat_type buckets, dropping any with no
    flat_type. Used for the flat-type price trend chart (see charts.py) —
    kept separate from monthly_average_series so callers can compute one
    series per flat_type from the same underlying record set."""
    grouped: dict[str, list[dict]] = {}
    for r in records:
        flat_type = r.get("flat_type")
        if flat_type:
            grouped.setdefault(flat_type, []).append(r)
    return grouped


def monthly_average_series(
    records: list[dict],
    price_field: str,
    month_field: str,
    months_window: int = 24,
    today: date | None = None,
) -> list[tuple[str, float]]:
    """Return [(month_str, average_price), ...], chronologically sorted, for
    every month in the window that has at least one record.

    Used for the multi-district price-comparison chart (see charts.py) —
    months with no data are simply omitted rather than zero-filled or
    interpolated, since either would misrepresent the underlying data.
    """
    recent = filter_recent(records, month_field, months_window, today)

    by_month: dict[tuple[int, int], list[float]] = {}
    for r in recent:
        parsed = parse_month(str(r.get(month_field, "")))
        price = r.get(price_field)
        if parsed is None or price is None:
            continue
        by_month.setdefault(parsed, []).append(float(price))

    return [
        (f"{year:04d}-{month:02d}", statistics.mean(prices))
        for (year, month), prices in sorted(by_month.items())
    ]


def _quantiles(values: list[float]) -> tuple[float, float, float]:
    """Return (p25, median, p75). Handles tiny sample sizes gracefully."""
    if len(values) == 1:
        v = values[0]
        return v, v, v
    q = statistics.quantiles(values, n=4, method="inclusive")
    return q[0], q[1], q[2]


def _median_of(records: list[dict], price_field: str) -> float | None:
    prices = [r[price_field] for r in records if r.get(price_field) is not None]
    if not prices:
        return None
    return statistics.median(float(p) for p in prices)


def _trend(
    all_records_for_type: list[tuple[int, dict]], price_field: str, now_index: int
) -> tuple[float | None, str]:
    """Compare the median of the last 3 months vs. the same quarter a year ago.

    `all_records_for_type` is a list of (month_index, record) tuples, not
    restricted to the "recent window" used for the headline stats — trend
    needs up to ~15 months of history even when the display window is 12.
    """
    recent_q = [r for idx, r in all_records_for_type if now_index - 2 <= idx <= now_index]
    year_ago_q = [
        r for idx, r in all_records_for_type if now_index - 14 <= idx <= now_index - 12
    ]

    if len(recent_q) < 3 or len(year_ago_q) < 3:
        return None, "insufficient_data"

    recent_median = _median_of(recent_q, price_field)
    year_ago_median = _median_of(year_ago_q, price_field)
    if not recent_median or not year_ago_median:
        return None, "insufficient_data"

    pct = (recent_median - year_ago_median) / year_ago_median * 100
    if pct > 1.5:
        label = "up"
    elif pct < -1.5:
        label = "down"
    else:
        label = "flat"
    return pct, label


def summarize(
    records: list[dict],
    price_field: str,
    month_field: str,
    months_window: int = 12,
    today: date | None = None,
) -> list[FlatTypeStats]:
    """Group records by flat_type and compute headline stats + YoY trend.

    `records` should be the FULL history for a town (not pre-filtered to the
    recent window) so the trend calculation has enough lookback; the
    recent-window filtering for headline stats happens inside this function.
    Returns an empty list if there's no usable data at all.
    """
    today = today or date.today()
    now_index = _month_index(today.year, today.month)
    cutoff_index = now_index - months_window

    by_type_all: dict[str, list[tuple[int, dict]]] = {}
    for r in records:
        parsed = parse_month(str(r.get(month_field, "")))
        if parsed is None or r.get(price_field) is None:
            continue
        idx = _month_index(*parsed)
        by_type_all.setdefault(r["flat_type"], []).append((idx, r))

    results: list[FlatTypeStats] = []
    for flat_type, dated_records in by_type_all.items():
        recent = [r for idx, r in dated_records if idx > cutoff_index]
        if not recent:
            continue
        prices = [float(r[price_field]) for r in recent]
        p25, median, p75 = _quantiles(prices)
        trend_pct, trend_label = _trend(dated_records, price_field, now_index)
        results.append(
            FlatTypeStats(
                flat_type=flat_type,
                count=len(recent),
                min=min(prices),
                max=max(prices),
                mean=statistics.mean(prices),
                median=median,
                p25=p25,
                p75=p75,
                trend_pct=trend_pct,
                trend_label=trend_label,
            )
        )

    results.sort(key=lambda s: s.count, reverse=True)
    return results
