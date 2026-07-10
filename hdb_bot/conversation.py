"""The bot's ConversationHandler: /start -> pick intent -> pick locality -> results."""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from . import formatting
from .datagov_client import DATASET_FOR_INTENT, DataGovClient
from .localities import LocalityMatch, LocalityNotFound, resolve
from .maps import fetch_map_image
from .stats import summarize

logger = logging.getLogger(__name__)

CHOOSING_INTENT, ASKING_LOCALITY = range(2)

_INTENT_KEYBOARD = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("Buy 🏠", callback_data="intent:buy"),
            InlineKeyboardButton("Sell 💰", callback_data="intent:sell"),
            InlineKeyboardButton("Rent 🔑", callback_data="intent:rent"),
        ]
    ]
)

_NEW_SEARCH_KEYBOARD = InlineKeyboardMarkup(
    [[InlineKeyboardButton("🔁 New search", callback_data="restart")]]
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.effective_message.reply_text(formatting.greeting(), reply_markup=_INTENT_KEYBOARD)
    return CHOOSING_INTENT


async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(formatting.greeting(), reply_markup=_INTENT_KEYBOARD)
    return CHOOSING_INTENT


async def intent_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    intent = query.data.split(":", 1)[1]
    context.user_data["intent"] = intent
    await query.message.reply_text(formatting.ask_locality(intent))
    return ASKING_LOCALITY


async def locality_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text or ""
    intent = context.user_data.get("intent", "buy")

    try:
        match: LocalityMatch = resolve(text)
    except LocalityNotFound as exc:
        await update.message.reply_text(formatting.locality_not_found(text, exc.suggestions))
        return ASKING_LOCALITY

    config = context.bot_data["config"]
    client: DataGovClient = context.bot_data["datagov_client"]
    dataset = DATASET_FOR_INTENT[intent]

    all_records: list[dict] = []
    for town in match.towns:
        all_records.extend(await client.fetch_town_records(dataset.resource_id, town))

    stats = summarize(
        all_records,
        price_field=dataset.price_field,
        month_field=dataset.month_field,
        months_window=config.recent_months_window,
    )

    if not stats:
        await update.message.reply_text(formatting.no_data_message(match.towns))
        await update.message.reply_text(formatting.ask_locality(intent))
        return ASKING_LOCALITY

    message = formatting.format_stats_message(
        intent, match.towns, stats, note=match.note, months_window=config.recent_months_window
    )
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

    map_result = await fetch_map_image(match.towns, config.google_maps_api_key)
    if map_result is not None:
        await update.message.reply_photo(
            photo=map_result.image_bytes, caption=formatting.map_caption(map_result.legend)
        )

    await update.message.reply_text(
        "Want to check another area?", reply_markup=_NEW_SEARCH_KEYBOARD
    )
    return CHOOSING_INTENT


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.effective_message.reply_text(formatting.cancelled_message())
    context.user_data.clear()
    return ConversationHandler.END


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled exception while processing update: %s", update, exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(formatting.error_message())


def build_conversation_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSING_INTENT: [
                CallbackQueryHandler(intent_chosen, pattern=r"^intent:(buy|sell|rent)$"),
                CallbackQueryHandler(restart, pattern=r"^restart$"),
            ],
            ASKING_LOCALITY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, locality_received),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
