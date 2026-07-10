from hdb_bot import formatting
from hdb_bot.stats import FlatTypeStats


def _stat(flat_type="4 ROOM", trend_label="up", trend_pct=10.0) -> FlatTypeStats:
    return FlatTypeStats(
        flat_type=flat_type, count=10, min=500000, max=600000, mean=550000,
        median=550000, p25=520000, p75=580000, trend_pct=trend_pct, trend_label=trend_label,
    )


def test_flat_type_normalizes_hyphen_and_space_forms_the_same_way():
    message_space = formatting.format_stats_message("buy", ["BISHAN"], [_stat(flat_type="3 ROOM")])
    message_hyphen = formatting.format_stats_message("rent", ["BISHAN"], [_stat(flat_type="3-ROOM")])
    assert "3 Room" in message_space
    assert "3 Room" in message_hyphen
    assert "3-Room" not in message_hyphen


def test_format_stats_message_includes_money_and_town():
    message = formatting.format_stats_message("buy", ["BISHAN"], [_stat()])
    assert "Bishan" in message
    assert "$550,000" in message


def test_rent_intent_appends_per_month_unit():
    message = formatting.format_stats_message("rent", ["BISHAN"], [_stat()])
    assert "/month" in message


def test_insufficient_data_trend_has_no_percentage():
    message = formatting.format_stats_message(
        "buy", ["BISHAN"], [_stat(trend_label="insufficient_data", trend_pct=None)]
    )
    assert "not enough history" in message


def test_locality_not_found_with_and_without_suggestions():
    with_suggestions = formatting.locality_not_found("asdf", ["BISHAN", "YISHUN"])
    assert "Bishan" in with_suggestions and "Yishun" in with_suggestions

    without_suggestions = formatting.locality_not_found("asdf", [])
    assert "asdf" in without_suggestions
