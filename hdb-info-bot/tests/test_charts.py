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
