from hdb_bot import formatting
from hdb_bot.glossary import SOURCES_FOOTER
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
    assert "not enough transaction history" in message


def test_locality_not_found_with_and_without_suggestions():
    with_suggestions = formatting.locality_not_found("asdf", ["BISHAN", "YISHUN"])
    assert "Bishan" in with_suggestions and "Yishun" in with_suggestions

    without_suggestions = formatting.locality_not_found("asdf", [])
    assert "asdf" in without_suggestions


def test_stats_message_includes_sources_footer():
    message = formatting.format_stats_message("buy", ["BISHAN"], [_stat()])
    assert SOURCES_FOOTER in message


def test_carpark_message_includes_sources_footer():
    carparks = [{"address": "blk 1 test st", "lots_available": 5, "total_lots": 10,
                 "free_parking": "NO", "night_parking": "YES"}]
    message = formatting.format_carpark_message(["BISHAN"], carparks)
    assert SOURCES_FOOTER in message


def test_compare_chart_caption_includes_sources_footer():
    caption = formatting.compare_chart_caption(["Bishan", "Tampines"], 24)
    assert SOURCES_FOOTER in caption


def test_trend_chart_caption_includes_sources_footer_and_town():
    caption = formatting.trend_chart_caption(["Bishan"], "buy", 12)
    assert "Bishan" in caption
    assert "resale price" in caption
    assert SOURCES_FOOTER in caption


def test_trend_chart_caption_rent_says_rental_price():
    caption = formatting.trend_chart_caption(["Bishan"], "rent", 12)
    assert "rental price" in caption


def test_no_trend_chart_data_message_is_nonempty():
    assert formatting.no_trend_chart_data_message()


def test_fmt_flat_type_normalizes_hyphen_and_space():
    assert formatting.fmt_flat_type("3 ROOM") == "3 Room"
    assert formatting.fmt_flat_type("3-ROOM") == "3 Room"


def test_greeting_mentions_glossary_command():
    assert "/glossary" in formatting.greeting()


def test_ask_which_carpark_message_is_nonempty():
    assert formatting.ask_which_carpark_message()


def test_carpark_lots_breakdown_labels_car_confidently_and_others_generically():
    carpark = {
        "address": "blk 1 test st",
        "lots": [
            {"lot_type": "C", "lots_available": 42, "total_lots": 100},
            {"lot_type": "H", "lots_available": 0, "total_lots": 1},
            {"lot_type": "Y", "lots_available": 10, "total_lots": 20},
        ],
        "update_datetime": "2026-01-01T00:00:00",
    }
    message = formatting.carpark_lots_breakdown_message(carpark)
    assert "Car: 42/100 lots available" in message
    # Only "C" is confidently labelled — other codes shown as their raw type,
    # not an invented (possibly wrong) full name.
    assert "Type H" in message
    assert "Type Y" in message
    assert "2026-01-01T00:00:00" in message
    assert SOURCES_FOOTER in message


def test_carpark_lots_breakdown_handles_no_live_data():
    carpark = {"address": "blk 1 test st", "lots": [], "update_datetime": None}
    message = formatting.carpark_lots_breakdown_message(carpark)
    assert "not currently reporting" in message


def test_tone_no_longer_uses_singlish_particles():
    # Regression guard for the professional-tone rewrite — these Singlish
    # particles should no longer appear in the bot's core messages.
    text = "\n".join([
        formatting.greeting(),
        formatting.ask_locality("buy"),
        formatting.format_stats_message("buy", ["BISHAN"], [_stat()]),
        formatting.cancelled_message(),
        formatting.error_message(),
    ])
    for particle in (" lah", " leh", " lor", "kaki", "paiseh", "steady,"):
        assert particle not in text.lower()
