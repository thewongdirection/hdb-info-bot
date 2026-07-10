import json
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram.ext import ConversationHandler

from hdb_bot import conversation
from hdb_bot.config import Config

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    async def _instant_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setattr(conversation.asyncio, "sleep", _instant_sleep)


def _make_config(**overrides) -> Config:
    defaults = dict(
        telegram_bot_token="test-token",
        data_gov_sg_api_key=None,
        google_maps_api_key=None,
        run_mode="polling",
        webhook_url=None,
        port=8080,
        recent_months_window=12,
        chart_months_window=24,
        sync_interval_hours=24,
        data_dir=None,
    )
    defaults.update(overrides)
    return Config(**defaults)


def _make_update_message(text: str):
    update = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.message.reply_photo = AsyncMock()
    return update


def _make_update_callback(data: str):
    update = MagicMock()
    update.callback_query.data = data
    update.callback_query.answer = AsyncMock()
    update.callback_query.message.reply_text = AsyncMock()
    update.callback_query.message.reply_document = AsyncMock()
    update.callback_query.message.reply_venue = AsyncMock()
    return update


def _make_context(config: Config):
    context = MagicMock()
    context.user_data = {}
    context.bot_data = {"config": config}
    return context


async def test_start_sends_greeting_and_moves_to_choosing_intent():
    update = MagicMock()
    update.effective_message.reply_text = AsyncMock()
    context = _make_context(_make_config())

    state = await conversation.start(update, context)

    assert state == conversation.CHOOSING_INTENT
    update.effective_message.reply_text.assert_awaited_once()


async def test_intent_chosen_stores_intent_and_asks_locality():
    update = _make_update_callback("intent:sell")
    context = _make_context(_make_config())

    state = await conversation.intent_chosen(update, context)

    assert state == conversation.ASKING_LOCALITY
    assert context.user_data["intent"] == "sell"
    update.callback_query.message.reply_text.assert_awaited_once()


async def test_locality_received_unresolvable_reprompts_without_crashing():
    update = _make_update_message("xyzabc123notaplace")
    context = _make_context(_make_config())
    context.user_data["intent"] = "buy"

    state = await conversation.locality_received(update, context)

    assert state == conversation.ASKING_LOCALITY
    update.message.reply_text.assert_awaited_once()


async def test_locality_received_success_sends_stats(monkeypatch):
    records = json.loads((FIXTURES / "sample_resale_records.json").read_text())
    load_mock = MagicMock(return_value=records)
    monkeypatch.setattr(conversation.local_store, "load_town_records", load_mock)

    # No Google Maps key configured -> should skip the map without erroring.
    config = _make_config(recent_months_window=12, google_maps_api_key=None)
    context = _make_context(config)
    context.user_data["intent"] = "buy"
    update = _make_update_message("Bishan")

    state = await conversation.locality_received(update, context)

    assert state == conversation.CHOOSING_INTENT
    assert update.message.reply_text.await_count >= 2  # stats message + "new search" prompt
    load_mock.assert_called()
    assert context.user_data["last_query"] == {"intent": "buy", "towns": ["BISHAN"]}


async def test_locality_received_carparks_success(monkeypatch):
    matched = [
        {
            "car_park_no": "ACB", "address": "Test Address", "lat": 1.3, "lng": 103.8,
            "car_park_type": "SURFACE", "type_of_parking_system": "ELECTRONIC",
            "short_term_parking": "WHOLE DAY", "free_parking": "NO", "night_parking": "YES",
            "nearest_town": "BISHAN",
        }
    ]
    monkeypatch.setattr(conversation.carparks, "get_carparks_for_towns", MagicMock(return_value=matched))
    monkeypatch.setattr(
        conversation.carparks, "fetch_availability",
        AsyncMock(return_value={"ACB": {"lots_available": 10, "total_lots": 20, "lot_type": "C", "update_datetime": "now"}}),
    )

    context = _make_context(_make_config(google_maps_api_key=None))
    context.user_data["intent"] = "carparks"
    update = _make_update_message("Bishan")

    state = await conversation.locality_received(update, context)

    assert state == conversation.CHOOSING_INTENT
    update.message.reply_text.assert_awaited()
    conversation.carparks.get_carparks_for_towns.assert_called_once()


async def test_locality_received_carparks_no_carparks_reprompts(monkeypatch):
    monkeypatch.setattr(conversation.carparks, "get_carparks_for_towns", MagicMock(return_value=[]))
    context = _make_context(_make_config())
    context.user_data["intent"] = "carparks"
    update = _make_update_message("Bishan")

    state = await conversation.locality_received(update, context)

    assert state == conversation.ASKING_LOCALITY
    update.message.reply_text.assert_awaited()


async def test_show_block_map_no_prior_query_reprompts():
    update = _make_update_callback("show_blocks")
    context = _make_context(_make_config())

    state = await conversation.show_block_map(update, context)

    assert state == conversation.CHOOSING_INTENT
    update.callback_query.message.reply_text.assert_awaited_once()


async def test_show_block_map_no_api_key_configured():
    update = _make_update_callback("show_blocks")
    context = _make_context(_make_config(google_maps_api_key=None))
    context.user_data["last_query"] = {"intent": "buy", "towns": ["BISHAN"]}

    state = await conversation.show_block_map(update, context)

    assert state == conversation.CHOOSING_INTENT
    update.callback_query.message.reply_text.assert_awaited_once()


async def test_show_block_map_success(monkeypatch):
    records = json.loads((FIXTURES / "sample_resale_records.json").read_text())
    monkeypatch.setattr(conversation.local_store, "load_town_records", MagicMock(return_value=records))
    monkeypatch.setattr(
        conversation, "geocode_many", AsyncMock(return_value={"123 BISHAN ST 11": (1.35, 103.83)})
    )

    update = _make_update_callback("show_blocks")
    context = _make_context(_make_config(google_maps_api_key="fake-key"))
    context.user_data["last_query"] = {"intent": "buy", "towns": ["BISHAN"]}

    state = await conversation.show_block_map(update, context)

    assert state == conversation.CHOOSING_INTENT
    update.callback_query.message.reply_venue.assert_awaited_once()
    venue_kwargs = update.callback_query.message.reply_venue.await_args.kwargs
    assert venue_kwargs["latitude"] == 1.35
    assert venue_kwargs["longitude"] == 103.83
    assert venue_kwargs["title"] == "123 Bishan St 11"
    update.callback_query.message.reply_document.assert_not_awaited()


async def test_show_block_map_sends_one_venue_per_geocoded_block(monkeypatch):
    this_month = date.today().strftime("%Y-%m")
    records = [
        {"month": this_month, "flat_type": "4 ROOM", "resale_price": 500000, "block": "123", "street_name": "BISHAN ST 11"},
        {"month": this_month, "flat_type": "4 ROOM", "resale_price": 510000, "block": "124", "street_name": "BISHAN ST 12"},
        {"month": this_month, "flat_type": "4 ROOM", "resale_price": 520000, "block": "125", "street_name": "BISHAN ST 13"},
    ]
    geocoded = {
        "123 BISHAN ST 11": (1.35, 103.83),
        "124 BISHAN ST 12": (1.351, 103.831),
        "125 BISHAN ST 13": (1.352, 103.832),
    }
    monkeypatch.setattr(conversation.local_store, "load_town_records", MagicMock(return_value=records))
    monkeypatch.setattr(conversation, "geocode_many", AsyncMock(return_value=geocoded))

    update = _make_update_callback("show_blocks")
    context = _make_context(_make_config(google_maps_api_key="fake-key"))
    context.user_data["last_query"] = {"intent": "buy", "towns": ["BISHAN"]}

    state = await conversation.show_block_map(update, context)

    assert state == conversation.CHOOSING_INTENT
    assert update.callback_query.message.reply_venue.await_count == len(geocoded)


async def test_show_block_map_no_addresses_found(monkeypatch):
    monkeypatch.setattr(conversation.local_store, "load_town_records", MagicMock(return_value=[]))
    update = _make_update_callback("show_blocks")
    context = _make_context(_make_config(google_maps_api_key="fake-key"))
    context.user_data["last_query"] = {"intent": "buy", "towns": ["BISHAN"]}

    state = await conversation.show_block_map(update, context)

    assert state == conversation.CHOOSING_INTENT
    update.callback_query.message.reply_text.assert_awaited()


async def test_show_block_map_geocoding_fails_gracefully(monkeypatch):
    records = json.loads((FIXTURES / "sample_resale_records.json").read_text())
    monkeypatch.setattr(conversation.local_store, "load_town_records", MagicMock(return_value=records))
    monkeypatch.setattr(conversation, "geocode_many", AsyncMock(return_value={}))

    update = _make_update_callback("show_blocks")
    context = _make_context(_make_config(google_maps_api_key="fake-key"))
    context.user_data["last_query"] = {"intent": "buy", "towns": ["BISHAN"]}

    state = await conversation.show_block_map(update, context)

    assert state == conversation.CHOOSING_INTENT
    # progress message + failure message, no venues sent
    update.callback_query.message.reply_venue.assert_not_awaited()


_COMPARE_RECORDS = [
    {"month": "2026-01", "resale_price": 500000, "flat_type": "4 ROOM"},
    {"month": "2026-02", "resale_price": 510000, "flat_type": "4 ROOM"},
]


async def test_compare_success_sends_chart(monkeypatch):
    monkeypatch.setattr(
        conversation.local_store, "load_town_records", MagicMock(return_value=_COMPARE_RECORDS)
    )
    context = _make_context(_make_config())
    context.user_data["intent"] = "compare"
    update = _make_update_message("Bishan, Tampines")

    state = await conversation.locality_received(update, context)

    assert state == conversation.CHOOSING_INTENT
    update.message.reply_photo.assert_awaited_once()
    photo_bytes = update.message.reply_photo.await_args.kwargs["photo"]
    assert photo_bytes.startswith(b"\x89PNG\r\n\x1a\n")


async def test_compare_partial_failure_still_charts_valid_entries(monkeypatch):
    monkeypatch.setattr(
        conversation.local_store, "load_town_records", MagicMock(return_value=_COMPARE_RECORDS)
    )
    context = _make_context(_make_config())
    context.user_data["intent"] = "compare"
    update = _make_update_message("Bishan, xyzabc123notaplace")

    state = await conversation.locality_received(update, context)

    assert state == conversation.CHOOSING_INTENT
    update.message.reply_photo.assert_awaited_once()
    # a note about the failed entry should have gone out as one of the reply_text calls
    all_text = " ".join(str(c.args) for c in update.message.reply_text.await_args_list)
    assert "xyzabc123notaplace" in all_text


async def test_compare_all_invalid_reprompts():
    context = _make_context(_make_config())
    context.user_data["intent"] = "compare"
    update = _make_update_message("xyzabc123, asdfghjkl456")

    state = await conversation.locality_received(update, context)

    assert state == conversation.ASKING_LOCALITY
    update.message.reply_photo.assert_not_awaited()


async def test_compare_no_data_reprompts(monkeypatch):
    monkeypatch.setattr(conversation.local_store, "load_town_records", MagicMock(return_value=[]))
    context = _make_context(_make_config())
    context.user_data["intent"] = "compare"
    update = _make_update_message("Bishan, Tampines")

    state = await conversation.locality_received(update, context)

    assert state == conversation.ASKING_LOCALITY
    update.message.reply_photo.assert_not_awaited()


async def test_compare_caps_entries_at_max(monkeypatch):
    monkeypatch.setattr(
        conversation.local_store, "load_town_records", MagicMock(return_value=_COMPARE_RECORDS)
    )
    context = _make_context(_make_config())
    context.user_data["intent"] = "compare"
    many_towns = ["Bishan", "Tampines", "Bedok", "Yishun", "Punggol", "Sengkang", "Hougang", "Woodlands"]
    update = _make_update_message(", ".join(many_towns))

    state = await conversation.locality_received(update, context)

    assert state == conversation.CHOOSING_INTENT
    update.message.reply_photo.assert_awaited_once()
    all_text = " ".join(str(c.args) for c in update.message.reply_text.await_args_list)
    assert "6" in all_text  # MAX_COMPARE_ENTRIES mentioned in the "dropped" note


async def test_compare_empty_input_reprompts():
    context = _make_context(_make_config())
    context.user_data["intent"] = "compare"
    update = _make_update_message("   ")

    state = await conversation.locality_received(update, context)

    assert state == conversation.ASKING_LOCALITY


async def test_locality_received_no_data_reprompts(monkeypatch):
    load_mock = MagicMock(return_value=[])
    monkeypatch.setattr(conversation.local_store, "load_town_records", load_mock)
    context = _make_context(_make_config())
    context.user_data["intent"] = "rent"
    update = _make_update_message("Punggol")

    state = await conversation.locality_received(update, context)

    assert state == conversation.ASKING_LOCALITY
    update.message.reply_text.assert_awaited()


async def test_cancel_ends_conversation_and_clears_state():
    update = MagicMock()
    update.effective_message.reply_text = AsyncMock()
    context = _make_context(_make_config())
    context.user_data["intent"] = "buy"

    state = await conversation.cancel(update, context)

    assert state == ConversationHandler.END
    assert context.user_data == {}
    update.effective_message.reply_text.assert_awaited_once()


async def test_error_handler_replies_with_friendly_message():
    from telegram import Update

    update = MagicMock(spec=Update)
    update.effective_message.reply_text = AsyncMock()
    context = MagicMock()
    context.error = RuntimeError("boom")

    await conversation.error_handler(update, context)

    update.effective_message.reply_text.assert_awaited_once()


async def test_glossary_command_replies_with_glossary_text():
    update = MagicMock()
    update.effective_message.reply_text = AsyncMock()
    context = _make_context(_make_config())

    result = await conversation.glossary_command(update, context)

    assert result is None  # leaves conversation state unchanged (PTB fallback semantics)
    update.effective_message.reply_text.assert_awaited_once()
    sent_text = update.effective_message.reply_text.await_args.args[0]
    assert "MOP" in sent_text
    assert "hdb.gov.sg" in sent_text
