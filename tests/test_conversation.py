import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram.ext import ConversationHandler

from hdb_bot import conversation
from hdb_bot.config import Config

FIXTURES = Path(__file__).parent / "fixtures"


def _make_config(**overrides) -> Config:
    defaults = dict(
        telegram_bot_token="test-token",
        data_gov_sg_api_key=None,
        google_maps_api_key=None,
        run_mode="polling",
        webhook_url=None,
        port=8080,
        cache_ttl_seconds=21600,
        recent_months_window=12,
    )
    defaults.update(overrides)
    return Config(**defaults)


def _make_update_message(text: str):
    update = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


def _make_update_callback(data: str):
    update = MagicMock()
    update.callback_query.data = data
    update.callback_query.answer = AsyncMock()
    update.callback_query.message.reply_text = AsyncMock()
    return update


def _make_context(config: Config, datagov_client=None):
    context = MagicMock()
    context.user_data = {}
    context.bot_data = {"config": config, "datagov_client": datagov_client or AsyncMock()}
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


async def test_locality_received_success_sends_stats():
    records = json.loads((FIXTURES / "sample_resale_records.json").read_text())
    datagov_client = AsyncMock()
    datagov_client.fetch_town_records.return_value = records

    # No Google Maps key configured -> should skip the map without erroring.
    config = _make_config(recent_months_window=12, google_maps_api_key=None)
    context = _make_context(config, datagov_client=datagov_client)
    context.user_data["intent"] = "buy"
    update = _make_update_message("Bishan")

    state = await conversation.locality_received(update, context)

    assert state == conversation.CHOOSING_INTENT
    assert update.message.reply_text.await_count >= 2  # stats message + "new search" prompt
    datagov_client.fetch_town_records.assert_awaited()


async def test_locality_received_no_data_reprompts():
    datagov_client = AsyncMock()
    datagov_client.fetch_town_records.return_value = []
    context = _make_context(_make_config(), datagov_client=datagov_client)
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
