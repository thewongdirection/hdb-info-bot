"""The bot's ConversationHandler: /start -> pick intent -> pick locality -> results."""
from __future__ import annotations

import asyncio
import logging
from collections import Counter

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

from . import carparks, formatting, local_store
from .charts import build_price_comparison_chart
from .datasets import DATASETS_FOR_INTENT
from .geocoding import GeocodeCache, geocode_many
from .glossary import format_full_glossary
from .localities import LocalityMatch, LocalityNotFound, resolve
from .maps import fetch_map_image, fetch_points_map_image
from .stats import filter_recent, monthly_average_series, summarize

logger = logging.getLogger(__name__)

CHOOSING_INTENT, ASKING_LOCALITY = range(2)

# How many unique blocks (by transaction count) to geocode/plot per request —
# keeps geocoding latency and the map's pin count reasonable.
MAX_BLOCKS_TO_PLOT = 60

# How many districts/areas the "Compare" chart will plot at once — keeps the
# chart legible and each request's local_store reads bounded.
MAX_COMPARE_ENTRIES = 6

_INTENT_KEYBOARD = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("Buy 🏠", callback_data="intent:buy"),
            InlineKeyboardButton("Sell 💰", callback_data="intent:sell"),
        ],
        [
            InlineKeyboardButton("Rent 🔑", callback_data="intent:rent"),
            InlineKeyboardButton("Carparks 🅿️", callback_data="intent:carparks"),
        ],
        [InlineKeyboardButton("Compare Districts 📊", callback_data="intent:compare")],
    ]
)

_NEW_SEARCH_KEYBOARD = InlineKeyboardMarkup(
    [[InlineKeyboardButton("🔁 New search", callback_data="restart")]]
)

_RESULTS_KEYBOARD = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("📍 Plot blocks on map", callback_data="show_blocks")],
        [InlineKeyboardButton("🔁 New search", callback_data="restart")],
    ]
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

    if intent == "compare":
        return await _handle_compare_query(update, context, text)

    try:
        match: LocalityMatch = resolve(text)
    except LocalityNotFound as exc:
        await update.message.reply_text(formatting.locality_not_found(text, exc.suggestions))
        return ASKING_LOCALITY

    if intent == "carparks":
        return await _handle_carparks_query(update, context, match)
    return await _handle_price_query(update, context, match, intent)


async def _handle_price_query(
    update: Update, context: ContextTypes.DEFAULT_TYPE, match: LocalityMatch, intent: str
) -> int:
    config = context.bot_data["config"]
    datasets = DATASETS_FOR_INTENT[intent]

    # Reads the local cache that data_sync.py keeps refreshed — no live
    # data.gov.sg call happens here, so this stays fast and off the rate limit.
    all_records: list[dict] = []
    for town in match.towns:
        town_records = await asyncio.to_thread(local_store.load_town_records, datasets, town)
        all_records.extend(town_records)

    stats = summarize(
        all_records,
        price_field=datasets[0].price_field,
        month_field=datasets[0].month_field,
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

    context.user_data["last_query"] = {"intent": intent, "towns": match.towns}
    await update.message.reply_text("Want to check another area?", reply_markup=_RESULTS_KEYBOARD)
    return CHOOSING_INTENT


async def _handle_carparks_query(
    update: Update, context: ContextTypes.DEFAULT_TYPE, match: LocalityMatch
) -> int:
    config = context.bot_data["config"]

    matched = await asyncio.to_thread(carparks.get_carparks_for_towns, match.towns)
    if not matched:
        await update.message.reply_text(formatting.no_carparks_message(match.towns))
        await update.message.reply_text(formatting.ask_locality("carparks"))
        return ASKING_LOCALITY

    availability = await carparks.fetch_availability(config.data_gov_sg_api_key)
    enriched = carparks.join_availability(matched, availability)

    message = formatting.format_carpark_message(match.towns, enriched, note=match.note)
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

    coords = [(c["lat"], c["lng"]) for c in enriched]
    image_bytes = await fetch_points_map_image(coords, config.google_maps_api_key, color="green")
    if image_bytes is not None:
        await update.message.reply_photo(
            photo=image_bytes, caption=formatting.carpark_map_caption(match.towns, len(coords))
        )

    await update.message.reply_text("Want to check another area?", reply_markup=_NEW_SEARCH_KEYBOARD)
    return CHOOSING_INTENT


async def _handle_compare_query(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
) -> int:
    config = context.bot_data["config"]
    raw_entries = [e.strip() for e in text.split(",") if e.strip()]

    if not raw_entries:
        await update.message.reply_text(formatting.compare_no_valid_localities_message([text]))
        return ASKING_LOCALITY

    dropped_count = 0
    if len(raw_entries) > MAX_COMPARE_ENTRIES:
        dropped_count = len(raw_entries) - MAX_COMPARE_ENTRIES
        raw_entries = raw_entries[:MAX_COMPARE_ENTRIES]

    resolved: list[tuple[str, LocalityMatch]] = []
    failed: list[str] = []
    for entry in raw_entries:
        try:
            resolved.append((entry, resolve(entry)))
        except LocalityNotFound:
            failed.append(entry)

    if not resolved:
        await update.message.reply_text(formatting.compare_no_valid_localities_message(failed))
        return ASKING_LOCALITY

    # buy/sell both read the resale dataset group — a comparison of "average
    # prices" is inherently about the resale market.
    datasets = DATASETS_FOR_INTENT["buy"]
    series: dict[str, list[tuple[str, float]]] = {}
    for label, match in resolved:
        all_records: list[dict] = []
        for town in match.towns:
            town_records = await asyncio.to_thread(local_store.load_town_records, datasets, town)
            all_records.extend(town_records)
        points = monthly_average_series(
            all_records,
            price_field=datasets[0].price_field,
            month_field=datasets[0].month_field,
            months_window=config.chart_months_window,
        )
        if points:
            series[label.title()] = points

    if not series:
        labels = [label.title() for label, _ in resolved]
        await update.message.reply_text(formatting.compare_no_data_message(labels))
        await update.message.reply_text(formatting.ask_locality("compare"))
        return ASKING_LOCALITY

    if failed:
        await update.message.reply_text(formatting.compare_partial_failure_note(failed))
    if dropped_count:
        await update.message.reply_text(formatting.compare_too_many_note(dropped_count, MAX_COMPARE_ENTRIES))

    chart_bytes = build_price_comparison_chart(series)
    await update.message.reply_photo(
        photo=chart_bytes,
        caption=formatting.compare_chart_caption(list(series.keys()), config.chart_months_window),
    )

    await update.message.reply_text(
        "Want to compare another set of areas?", reply_markup=_NEW_SEARCH_KEYBOARD
    )
    return CHOOSING_INTENT


async def show_block_map(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    last_query = context.user_data.get("last_query")
    if not last_query:
        await query.message.reply_text(formatting.run_a_search_first_message())
        return CHOOSING_INTENT

    config = context.bot_data["config"]
    if not config.google_maps_api_key:
        await query.message.reply_text(formatting.no_maps_configured_message())
        return CHOOSING_INTENT

    intent = last_query["intent"]
    towns = last_query["towns"]
    datasets = DATASETS_FOR_INTENT[intent]

    all_records: list[dict] = []
    for town in towns:
        town_records = await asyncio.to_thread(local_store.load_town_records, datasets, town)
        all_records.extend(town_records)

    recent = filter_recent(
        all_records, month_field=datasets[0].month_field, months_window=config.recent_months_window
    )

    address_counts: Counter[str] = Counter()
    for r in recent:
        address = f"{(r.get('block') or '').strip()} {(r.get('street_name') or '').strip()}".strip()
        if address:
            address_counts[address] += 1
    addresses = [a for a, _ in address_counts.most_common(MAX_BLOCKS_TO_PLOT)]

    if not addresses:
        await query.message.reply_text(formatting.block_map_no_data_message())
        return CHOOSING_INTENT

    await query.message.reply_text(formatting.geocoding_in_progress_message(len(addresses)))

    cache = GeocodeCache()
    geocoded = await geocode_many(addresses, config.google_maps_api_key, cache)
    if not geocoded:
        await query.message.reply_text(formatting.block_map_failed_message())
        return CHOOSING_INTENT

    image_bytes = await fetch_points_map_image(list(geocoded.values()), config.google_maps_api_key)
    if image_bytes is None:
        await query.message.reply_text(formatting.block_map_failed_message())
        return CHOOSING_INTENT

    caption = formatting.block_map_caption(towns, len(geocoded), len(addresses))
    filename = f"hdb_blocks_{towns[0].lower().replace('/', '_')}.png"
    await query.message.reply_document(document=image_bytes, filename=filename, caption=caption)
    return CHOOSING_INTENT


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.effective_message.reply_text(formatting.cancelled_message())
    context.user_data.clear()
    return ConversationHandler.END


async def glossary_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Available at any point in the conversation without disrupting it —
    registered as a fallback, and returns None so PTB leaves the current
    per-chat state unchanged."""
    await update.effective_message.reply_text(format_full_glossary(), parse_mode=ParseMode.MARKDOWN)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled exception while processing update: %s", update, exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(formatting.error_message())


def build_conversation_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSING_INTENT: [
                CallbackQueryHandler(intent_chosen, pattern=r"^intent:(buy|sell|rent|carparks|compare)$"),
                CallbackQueryHandler(show_block_map, pattern=r"^show_blocks$"),
                CallbackQueryHandler(restart, pattern=r"^restart$"),
            ],
            ASKING_LOCALITY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, locality_received),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("glossary", glossary_command),
        ],
    )
