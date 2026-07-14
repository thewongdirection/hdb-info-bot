import pytest

from hdb_bot.charts import build_price_comparison_chart, warm_up

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def test_returns_valid_png_bytes():
    series = {"Bishan": [("2025-01", 500000.0), ("2025-02", 505000.0)]}
    png = build_price_comparison_chart(series)
    assert png.startswith(PNG_MAGIC)
    assert len(png) > 100


def test_multiple_series_with_misaligned_months_does_not_crash():
    series = {
        "Bishan": [("2025-01", 500000.0), ("2025-02", 505000.0), ("2025-04", 520000.0)],
        "Tampines": [("2025-01", 450000.0), ("2025-03", 455000.0)],
    }
    png = build_price_comparison_chart(series)
    assert png.startswith(PNG_MAGIC)


def test_empty_series_dict_raises():
    with pytest.raises(ValueError):
        build_price_comparison_chart({})


def test_series_with_only_empty_point_lists_raises():
    with pytest.raises(ValueError):
        build_price_comparison_chart({"Bishan": [], "Tampines": []})


def test_single_series_single_point():
    png = build_price_comparison_chart({"Bishan": [("2025-01", 500000.0)]})
    assert png.startswith(PNG_MAGIC)


def test_warm_up_does_not_raise():
    warm_up()


def test_max_entries_renders_without_crashing():
    # MAX_COMPARE_ENTRIES in conversation.py is 6 -- covers the boundary
    # where marker/linestyle cycling would repeat.
    series = {
        f"Town{i}": [("2025-01", 500000.0 + i * 1000), ("2025-02", 505000.0 + i * 1000)]
        for i in range(6)
    }
    png = build_price_comparison_chart(series)
    assert png.startswith(PNG_MAGIC)


def test_more_series_than_marker_styles_still_renders():
    # More series than len(_MARKERS)/_LINESTYLES must still cycle rather
    # than raise an IndexError.
    from hdb_bot.charts import _MARKERS

    series = {
        f"Town{i}": [("2025-01", 500000.0 + i * 1000)] for i in range(len(_MARKERS) + 3)
    }
    png = build_price_comparison_chart(series)
    assert png.startswith(PNG_MAGIC)
