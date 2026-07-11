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

from . import ai_assistant, carparks, formatting, local_store
from .charts import build_price_comparison_chart
from .datasets import DATASETS_FOR_INTENT
from .geocoding import geocode_many
from .glossary import SOURCES_FOOTER, format_full_glossary
from .localities import LocalityMatch, LocalityNotFound, resolve
from .maps import nearest_town
from .stats import filter_recent, group_by_flat_type, monthly_average_series, summarize

logger = logging.getLogger(__name__)

CHOOSING_INTENT, ASKING_LOCALITY, ASKING_AI_QUESTION = range(3)

# How many unique blocks (by transaction count) to geocode/plot per request —
# keeps geocoding latency and the number of venue messages sent reasonable.
MAX_BLOCK_VENUES = 10

# Spacing between consecutive venue messages to the same chat, to stay well
# clear of Telegram's per-chat flood-control limits (guideline: ~1 msg/sec).
BLOCK_VENUE_SEND_DELAY_SECONDS = 0.35

# How many districts/areas the "Compare" chart will plot at once — keeps the
# chart legible and each request's local_store reads bounded.
MAX_COMPARE_ENTRIES = 6

# How many carparks are offered as pick-one buttons after a carpark search.
MAX_CARPARK_BUTTONS = 10
_CARPARK_BUTTON_LABEL_MAX_LEN = 30

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
        [InlineKeyboardButton("Ask AI 🤖", callback_data="intent:ask_ai")],
    ]
)

_RESULTS_FOLLOWUP_KEYBOARD = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("📍 Plot blocks on map", callback_data="show_blocks")],
        [InlineKeyboardButton("📊 View price trend chart", callback_data="show_trend_chart")],
    ]
)

# Attached to every prompt that's waiting on the user to type something
# (locality entry, reprompts after an unresolved/invalid input) so there's
# always a one-tap way out back to the start, not just /cancel.
_MAIN_MENU_ONLY_KEYBOARD = InlineKeyboardMarkup(
    [[InlineKeyboardButton("🏠 Main Menu", callback_data="restart")]]
)


async def _send_main_menu(message) -> None:
    """Every branch ends here — no dead ends, always back at the same
    starting welcome message and initial options as /start."""
    await message.reply_text(formatting.greeting(), reply_markup=_INTENT_KEYBOARD)


async def _bail_to_main_menu(message, text: str) -> int:
    """The shared shape for every "nothing to do here" branch — no prior
    query, missing config, no data/results found: explain briefly, then
    back to the main menu."""
    await message.reply_text(text)
    await _send_main_menu(message)
    return CHOOSING_INTENT


async def _reprompt_locality(message, text: str) -> int:
    """The shared shape for every "please try again" branch while asking
    for a locality: send `text` with the always-available Main Menu button
    attached, and stay in ASKING_LOCALITY."""
    await message.reply_text(text, reply_markup=_MAIN_MENU_ONLY_KEYBOARD)
    return ASKING_LOCALITY


def _build_trend_chart_bytes(
    all_records: list[dict],
    *,
    price_field: str,
    month_field: str,
    months_window: int,
    price_unit_suffix: str,
    title: str,
) -> bytes | None:
    """Synchronous, CPU-bound: grouping/aggregating the records plus the
    matplotlib render itself. Meant to be run via asyncio.to_thread — see
    show_price_trend_chart. Returns None if there's no data to chart."""
    series: dict[str, list[tuple[str, float]]] = {}
    for flat_type, recs in group_by_flat_type(all_records).items():
        points = monthly_average_series(
            recs, price_field=price_field, month_field=month_field, months_window=months_window
        )
        if points:
            series[formatting.fmt_flat_type(flat_type)] = points

    if not series:
        return None
    return build_price_comparison_chart(series, price_unit_suffix=price_unit_suffix, title=title)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.effective_message.reply_text(formatting.greeting(), reply_markup=_INTENT_KEYBOARD)
    return CHOOSING_INTENT


async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """The "🏠 Main Menu" bail-out button attached to every prompt that's
    waiting on user input — registered as a fallback so it works from any
    state (see build_conversation_handler)."""
    query = update.callback_query
    await query.answer()
    await _send_main_menu(query.message)
    return CHOOSING_INTENT


async def intent_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    intent = query.data.split(":", 1)[1]
    context.user_data["intent"] = intent

    if intent == "ask_ai":
        # No "Main Menu" button here on purpose: /stop is the one documented
        # way out of AI Q&A mode (see ai_question_received), so the user
        # keeps getting follow-up answers instead of being bounced out by an
        # accidental tap.
        await query.message.reply_text(formatting.ask_ai_prompt_message())
        return ASKING_AI_QUESTION

    return await _reprompt_locality(query.message, formatting.ask_locality(intent))


async def _suggest_town_via_geocoding(text: str, context: ContextTypes.DEFAULT_TYPE) -> str | None:
    """Last-resort fallback when the input didn't string-match anything at
    all (no town/alias/postal-code/district match, and no fuzzy candidates):
    geocode the raw text and suggest whichever HDB town's centroid is
    closest. Returns None (silently — caller falls back to the plain
    not-found message) if no Maps key is configured, or if geocoding fails
    or can't place the input at all."""
    config = context.bot_data["config"]
    if not config.google_maps_api_key:
        return None
    geocoded = await geocode_many(
        [text],
        config.google_maps_api_key,
        context.bot_data["geocode_cache"],
        client=context.bot_data.get("http_client"),
    )
    coords = geocoded.get(text)
    if coords is None:
        return None
    lat, lng = coords
    return nearest_town(lat, lng)


async def locality_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text or ""
    intent = context.user_data.get("intent", "buy")

    if intent == "compare":
        return await _handle_compare_query(update, context, text)

    try:
        match: LocalityMatch = resolve(text)
    except LocalityNotFound as exc:
        if not exc.suggestions:
            suggested_town = await _suggest_town_via_geocoding(text, context)
            if suggested_town:
                return await _reprompt_locality(
                    update.message, formatting.geocode_nearest_suggestion(text, suggested_town)
                )
        return await _reprompt_locality(
            update.message, formatting.locality_not_found(text, exc.suggestions)
        )

    if intent == "carparks":
        return await _handle_carparks_query(update, context, match)
    return await _handle_price_query(update, context, match, intent)


async def ai_question_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text or ""
    config = context.bot_data["config"]

    if not config.anthropic_api_key:
        return await _bail_to_main_menu(update.message, formatting.ai_not_configured_message())

    await update.message.reply_text(formatting.ai_thinking_message())
    try:
        answer = await ai_assistant.ask(
            text,
            anthropic_client=context.bot_data["anthropic_client"],
            data_gov_sg_api_key=config.data_gov_sg_api_key,
            http_client=context.bot_data.get("http_client"),
        )
    except Exception:
        logger.exception("AI assistant call failed")
        await update.message.reply_text(
            f"{formatting.ai_unavailable_message()}\n\n{formatting.ai_exit_hint()}"
        )
        return ASKING_AI_QUESTION

    # Stays in ASKING_AI_QUESTION rather than returning to the main menu —
    # this is a back-and-forth Q&A, not a one-shot query like the button
    # flows, so the user keeps asking follow-ups until they explicitly /stop.
    await update.message.reply_text(
        f"{answer}\n\n{SOURCES_FOOTER}\n\n{formatting.ai_exit_hint()}"
    )
    return ASKING_AI_QUESTION


async def ai_question_stopped(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _bail_to_main_menu(update.effective_message, formatting.ai_stopped_message())


async def _handle_price_query(
    update: Update, context: ContextTypes.DEFAULT_TYPE, match: LocalityMatch, intent: str
) -> int:
    config = context.bot_data["config"]
    datasets = DATASETS_FOR_INTENT[intent]

    # Reads the local cache that data_sync.py keeps refreshed — no live
    # data.gov.sg call happens here, so this stays fast and off the rate limit.
    all_records = await local_store.load_town_records_multi(datasets, match.towns)

    stats = summarize(
        all_records,
        price_field=datasets[0].price_field,
        month_field=datasets[0].month_field,
        months_window=config.recent_months_window,
    )

    if not stats:
        await update.message.reply_text(formatting.no_data_message(match.towns))
        return await _reprompt_locality(update.message, formatting.ask_locality(intent))

    message = formatting.format_stats_message(
        intent, match.towns, stats, note=match.note, months_window=config.recent_months_window
    )
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

    context.user_data["last_query"] = {"intent": intent, "towns": match.towns}
    await update.message.reply_text(
        "Want to explore these results further?", reply_markup=_RESULTS_FOLLOWUP_KEYBOARD
    )
    await _send_main_menu(update.message)
    return CHOOSING_INTENT


def _carpark_button_label(c: dict) -> str:
    address = c["address"].title()
    if len(address) > _CARPARK_BUTTON_LABEL_MAX_LEN:
        address = address[: _CARPARK_BUTTON_LABEL_MAX_LEN - 1] + "…"
    lots, total = c.get("lots_available"), c.get("total_lots")
    if lots is not None and total is not None:
        return f"{address} ({lots}/{total})"
    return address


async def _handle_carparks_query(
    update: Update, context: ContextTypes.DEFAULT_TYPE, match: LocalityMatch
) -> int:
    config = context.bot_data["config"]

    matched = await asyncio.to_thread(carparks.get_carparks_for_towns, match.towns)
    if not matched:
        await update.message.reply_text(formatting.no_carparks_message(match.towns))
        return await _reprompt_locality(update.message, formatting.ask_locality("carparks"))

    availability = await carparks.fetch_availability(
        config.data_gov_sg_api_key, client=context.bot_data.get("http_client")
    )
    enriched = carparks.join_availability(matched, availability)

    message = formatting.format_carpark_message(match.towns, enriched, note=match.note)
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

    # Keyed by car_park_no so the "pick a carpark" buttons below can look up
    # full details (coords + lot breakdown) without a second query.
    context.user_data["last_carparks_by_no"] = {
        c["car_park_no"]: c for c in enriched if c.get("car_park_no")
    }

    pickable = [c for c in enriched if c.get("car_park_no")][:MAX_CARPARK_BUTTONS]
    keyboard_rows = [
        [InlineKeyboardButton(_carpark_button_label(c), callback_data=f"carpark:{c['car_park_no']}")]
        for c in pickable
    ]

    await update.message.reply_text(
        formatting.ask_which_carpark_message(), reply_markup=InlineKeyboardMarkup(keyboard_rows)
    )
    await _send_main_menu(update.message)
    return CHOOSING_INTENT


async def _handle_compare_query(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
) -> int:
    config = context.bot_data["config"]
    raw_entries = [e.strip() for e in text.split(",") if e.strip()]

    if not raw_entries:
        return await _reprompt_locality(
            update.message, formatting.compare_no_valid_localities_message([text])
        )

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
        return await _reprompt_locality(
            update.message, formatting.compare_no_valid_localities_message(failed)
        )

    # buy/sell both read the resale dataset group — a comparison of "average
    # prices" is inherently about the resale market.
    datasets = DATASETS_FOR_INTENT["buy"]

    async def _points_for(label: str, match: LocalityMatch) -> tuple[str, list[tuple[str, float]]]:
        all_records = await local_store.load_town_records_multi(datasets, match.towns)
        # monthly_average_series is real CPU work over potentially tens of
        # thousands of records — run it in a thread so it doesn't block the
        # event loop (and every other district's concurrent fetch/compute).
        points = await asyncio.to_thread(
            monthly_average_series,
            all_records,
            price_field=datasets[0].price_field,
            month_field=datasets[0].month_field,
            months_window=config.chart_months_window,
        )
        return label, points

    # Each district's records are independent of the others, so fetch all of
    # them concurrently instead of working through the list one at a time.
    per_district = await asyncio.gather(*(_points_for(label, match) for label, match in resolved))
    series: dict[str, list[tuple[str, float]]] = {
        label.title(): points for label, points in per_district if points
    }

    if not series:
        labels = [label.title() for label, _ in resolved]
        await update.message.reply_text(formatting.compare_no_data_message(labels))
        return await _reprompt_locality(update.message, formatting.ask_locality("compare"))

    if failed:
        await update.message.reply_text(formatting.compare_partial_failure_note(failed))
    if dropped_count:
        await update.message.reply_text(formatting.compare_too_many_note(dropped_count, MAX_COMPARE_ENTRIES))

    chart_bytes = await asyncio.to_thread(build_price_comparison_chart, series)
    await update.message.reply_photo(
        photo=chart_bytes,
        caption=formatting.compare_chart_caption(list(series.keys()), config.chart_months_window),
    )

    await _send_main_menu(update.message)
    return CHOOSING_INTENT


async def show_block_map(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    last_query = context.user_data.get("last_query")
    if not last_query:
        return await _bail_to_main_menu(query.message, formatting.run_a_search_first_message())

    config = context.bot_data["config"]
    if not config.google_maps_api_key:
        return await _bail_to_main_menu(query.message, formatting.no_maps_configured_message())

    intent = last_query["intent"]
    towns = last_query["towns"]
    datasets = DATASETS_FOR_INTENT[intent]

    all_records = await local_store.load_town_records_multi(datasets, towns)

    recent = filter_recent(
        all_records, month_field=datasets[0].month_field, months_window=config.recent_months_window
    )

    address_counts: Counter[str] = Counter()
    for r in recent:
        address = f"{(r.get('block') or '').strip()} {(r.get('street_name') or '').strip()}".strip()
        if address:
            address_counts[address] += 1
    top_entries = address_counts.most_common(MAX_BLOCK_VENUES)
    addresses = [a for a, _ in top_entries]
    counts_by_address = dict(top_entries)

    if not addresses:
        return await _bail_to_main_menu(query.message, formatting.block_map_no_data_message())

    await query.message.reply_text(formatting.geocoding_in_progress_message(len(addresses)))

    geocoded = await geocode_many(
        addresses,
        config.google_maps_api_key,
        context.bot_data["geocode_cache"],
        client=context.bot_data.get("http_client"),
    )
    if not geocoded:
        return await _bail_to_main_menu(query.message, formatting.block_map_failed_message())

    # Sent as native Telegram venues rather than a static image — each pin is
    # individually pannable/zoomable within Telegram and can be tapped to
    # open in the user's own maps app for directions.
    town_label = towns[0].title()
    for address in addresses:
        coords = geocoded.get(address)
        if coords is None:
            continue
        lat, lng = coords
        await query.message.reply_venue(
            latitude=lat,
            longitude=lng,
            title=address.title(),
            address=f"{town_label} — {counts_by_address[address]} transaction(s)",
        )
        await asyncio.sleep(BLOCK_VENUE_SEND_DELAY_SECONDS)

    await query.message.reply_text(
        formatting.block_venues_summary(towns, len(geocoded), len(addresses))
    )
    await _send_main_menu(query.message)
    return CHOOSING_INTENT


async def show_price_trend_chart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    last_query = context.user_data.get("last_query")
    if not last_query:
        return await _bail_to_main_menu(query.message, formatting.run_a_search_first_message())

    intent = last_query["intent"]
    towns = last_query["towns"]
    datasets = DATASETS_FOR_INTENT[intent]
    config = context.bot_data["config"]

    all_records = await local_store.load_town_records_multi(datasets, towns)

    price_unit_suffix = "per month" if intent == "rent" else ""
    title = "Average Rental Price Trend by Flat Type" if intent == "rent" else "Average Resale Price Trend by Flat Type"
    # Grouping/aggregating potentially hundreds of thousands of records and
    # rendering the matplotlib figure are both real CPU work — run them in a
    # thread so they don't block the event loop (and every other user's
    # messages) for the whole duration.
    chart_bytes = await asyncio.to_thread(
        _build_trend_chart_bytes,
        all_records,
        price_field=datasets[0].price_field,
        month_field=datasets[0].month_field,
        months_window=config.recent_months_window,
        price_unit_suffix=price_unit_suffix,
        title=title,
    )

    if chart_bytes is None:
        return await _bail_to_main_menu(query.message, formatting.no_trend_chart_data_message())

    await query.message.reply_photo(
        photo=chart_bytes,
        caption=formatting.trend_chart_caption(towns, intent, config.recent_months_window),
    )

    await _send_main_menu(query.message)
    return CHOOSING_INTENT


async def show_carpark_map(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    car_park_no = query.data.split(":", 1)[1]
    carparks_by_no = context.user_data.get("last_carparks_by_no")
    if not carparks_by_no or car_park_no not in carparks_by_no:
        return await _bail_to_main_menu(query.message, formatting.run_a_search_first_message())

    carpark = carparks_by_no[car_park_no]
    await query.message.reply_text(
        formatting.carpark_lots_breakdown_message(carpark), parse_mode=ParseMode.MARKDOWN
    )
    await query.message.reply_venue(
        latitude=carpark["lat"],
        longitude=carpark["lng"],
        title=carpark["address"].title(),
        address=f"Car park {car_park_no}",
    )
    await _send_main_menu(query.message)
    return CHOOSING_INTENT


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.effective_message.reply_text(formatting.cancelled_message())
    context.user_data.clear()
    return ConversationHandler.END


async def glossary_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Available at any point in the conversation — registered as a
    fallback. Like every other branch, it ends back at the main menu rather
    than leaving the user stuck wherever they were."""
    await update.effective_message.reply_text(format_full_glossary(), parse_mode=ParseMode.MARKDOWN)
    await _send_main_menu(update.effective_message)
    return CHOOSING_INTENT


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled exception while processing update: %s", update, exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(formatting.error_message())


def build_conversation_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSING_INTENT: [
                CallbackQueryHandler(intent_chosen, pattern=r"^intent:(buy|sell|rent|carparks|compare|ask_ai)$"),
                CallbackQueryHandler(show_block_map, pattern=r"^show_blocks$"),
                CallbackQueryHandler(show_price_trend_chart, pattern=r"^show_trend_chart$"),
                CallbackQueryHandler(show_carpark_map, pattern=r"^carpark:.+$"),
            ],
            ASKING_LOCALITY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, locality_received),
            ],
            ASKING_AI_QUESTION: [
                CommandHandler("stop", ai_question_stopped),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ai_question_received),
            ],
        },
        fallbacks=[
            # In fallbacks (not a per-state handler) so the "🏠 Main Menu"
            # button works no matter which state it's pressed from —
            # ASKING_LOCALITY included.
            CallbackQueryHandler(restart, pattern=r"^restart$"),
            CommandHandler("cancel", cancel),
            CommandHandler("glossary", glossary_command),
        ],
    )
