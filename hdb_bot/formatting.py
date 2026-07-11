"""Friendly, professional message templates.

Kept separate from stats.py so the number-crunching stays pure/testable and
the bot's "voice" can be adjusted here without touching logic. Jargon/acronym
explanations live in glossary.py; every substantive (data-bearing) reply
ends with glossary.SOURCES_FOOTER, citing data.gov.sg as the data source and
pointing users to HDB/CEA/MND for authoritative rules — this bot provides
general market information only, not financial, legal, or property advice.
"""
from __future__ import annotations

import random

from . import glossary
from .stats import FlatTypeStats

INTENT_LABELS = {
    "buy": "buy", "sell": "sell", "rent": "rent", "carparks": "check carparks",
    "compare": "compare districts",
}

_INTENT_VERB = {
    "buy": "looking to buy a flat",
    "sell": "assessing your flat's value",
    "rent": "looking to rent a flat",
    "carparks": "looking for carpark information",
    "compare": "comparing districts",
}

_TREND_EMOJI = {"up": "📈", "down": "📉", "flat": "➡️", "insufficient_data": ""}

_STATS_TERMS_NOTE = (
    "_“Median” is the middle transaction price; the “typical range” covers "
    "the middle 50% of transactions. Send /glossary for definitions of these "
    "and other HDB/property terms._"
)


_GREETING_OPENERS = [
    "Hello, and welcome! 👋",
    "Hi there! 👋",
    "Welcome! 👋",
    "Hey, good to see you! 👋",
    "Hello again! 👋",
]


def greeting() -> str:
    opener = random.choice(_GREETING_OPENERS)
    return (
        f"{opener} I'm the HDB property and carpark info bot. "
        "I can help you look at price trends for buying, selling, or "
        "renting a flat, check nearby carpark availability, or compare "
        "prices across a few districts. What would you like to do?\n\n"
        f"{glossary_hint()}"
    )


def ask_locality(intent: str) -> str:
    verb = _INTENT_VERB.get(intent, "getting started")
    if intent == "compare":
        return (
            f"Great, {verb}. Please enter a few areas separated by commas — "
            "town names, postal codes, or district numbers can be mixed and "
            "matched (for example, \"Bishan, Tampines, D19\")."
        )
    return (
        f"Great, {verb}. Which area are you interested in? You can enter a "
        "town name (e.g. \"Bishan\"), a 6-digit postal code (e.g. "
        "\"560123\"), or a district number (e.g. \"D19\" or \"19\")."
    )


def locality_not_found(raw_input: str, suggestions: list[str]) -> str:
    if suggestions:
        options = ", ".join(s.title() for s in suggestions)
        return (
            f"I couldn't quite place {raw_input!r}. Did you mean one of "
            f"these: {options}? Please feel free to try again."
        )
    return (
        f"I wasn't able to match {raw_input!r} to a known area. Please try a "
        "town name, a 6-digit postal code, or a district number (e.g. \"D19\")."
    )


def geocode_nearest_suggestion(raw_input: str, nearest_town: str) -> str:
    town = nearest_town.title()
    return (
        f"I couldn't match {raw_input!r} to a known HDB town directly, but "
        f"the closest one on the map looks to be {town}. Type \"{town}\" to "
        "go with that, or try another area."
    )


def no_data_message(towns: list[str]) -> str:
    return (
        f"I checked {_town_list(towns)} but found very few or no recent "
        "transactions in the data. You might like to try a nearby town instead."
    )


def _town_list(towns: list[str]) -> str:
    return ", ".join(t.title() for t in towns)


def _fmt_money(value: float) -> str:
    return f"${value:,.0f}"


def fmt_flat_type(flat_type: str) -> str:
    # Resale dataset uses "3 ROOM", rental dataset uses "3-ROOM" — normalize
    # so both read the same way in a reply.
    return flat_type.replace("-", " ").title()


def _trend_phrase(stat: FlatTypeStats, intent: str) -> str:
    emoji = _TREND_EMOJI[stat.trend_label]
    if stat.trend_label == "insufficient_data":
        return "(not enough transaction history yet for a year-on-year trend)"
    verb = (
        "risen" if stat.trend_label == "up"
        else "fallen" if stat.trend_label == "down"
        else "remained broadly stable"
    )
    if stat.trend_label == "flat":
        return f"{emoji} Prices have {verb} over the past year."
    return f"{emoji} Prices have {verb} {abs(stat.trend_pct):.1f}% year-on-year."


def format_stats_message(
    intent: str,
    towns: list[str],
    stats: list[FlatTypeStats],
    note: str | None = None,
    months_window: int = 12,
) -> str:
    town_list = _town_list(towns)
    unit = "/month" if intent == "rent" else ""

    lines = [f"Here is the resale price summary for *{town_list}* (last {months_window} months):", ""]
    if note:
        lines.append(f"ℹ️ {note}")
        lines.append("")

    for s in stats:
        lines.append(f"*{fmt_flat_type(s.flat_type)}* — {s.count} transaction(s)")
        lines.append(
            f"  Median: {_fmt_money(s.median)}{unit}  "
            f"(typical range {_fmt_money(s.p25)}–{_fmt_money(s.p75)}{unit})"
        )
        lines.append(f"  Full range: {_fmt_money(s.min)} – {_fmt_money(s.max)}{unit}")
        lines.append(f"  {_trend_phrase(s, intent)}")
        lines.append("")

    if intent == "sell":
        lines.append("You may wish to use the median price for a similar unit type as a reference for your asking price.")
    elif intent == "buy":
        lines.append("This reflects typical recent prices for similar units in the area.")
    else:
        lines.append("This reflects the typical going rate for similar units in the area.")

    lines.append("")
    lines.append(_STATS_TERMS_NOTE)
    lines.append("")
    lines.append(glossary.SOURCES_FOOTER)

    return "\n".join(lines).strip()


def trend_chart_caption(towns: list[str], intent: str, months_window: int) -> str:
    town_list = _town_list(towns)
    what = "rental price" if intent == "rent" else "resale price"
    return (
        f"📊 Average {what} by flat type, last {months_window} months — "
        f"{town_list}.\n\n{glossary.SOURCES_FOOTER}"
    )


def no_trend_chart_data_message() -> str:
    return "There isn't enough recent data to chart a price trend for that search, unfortunately."


def no_maps_configured_message() -> str:
    return "Map generation isn't enabled on this bot (no Google Maps key configured), so I can only provide the text summary for now."


def ask_ai_prompt_message() -> str:
    return (
        "Ask me anything about HDB resale/rental prices or carpark availability — "
        "e.g. \"how have 4-room prices in Tampines moved this year?\" or "
        "\"compare Bishan and Yishun resale prices\". I'll only answer using the "
        "real data.gov.sg figures, never a guess.\n\n"
        f"{ai_exit_hint()}"
    )


def ai_not_configured_message() -> str:
    return "The AI Q&A feature isn't enabled on this bot (no Anthropic API key configured) — please use the menu options instead."


def ai_thinking_message() -> str:
    return "One moment, let me look that up... 🤖"


def ai_unavailable_message() -> str:
    return "I wasn't able to reach the AI service just now — please try asking again."


def ai_exit_hint() -> str:
    return "Send /stop anytime to leave AI Q&A mode and return to the main menu."


def ai_stopped_message() -> str:
    return "Okay, leaving AI Q&A mode."


def run_a_search_first_message() -> str:
    return "Please run a search first — send /start and choose an area before requesting the map."


def geocoding_in_progress_message(count: int) -> str:
    return f"One moment, I'm mapping out {count} block(s) for you... 🗺️ (this may take a few seconds the first time)"


def block_map_no_data_message() -> str:
    return "I couldn't find any blocks to plot for that search, unfortunately."


def block_map_failed_message() -> str:
    return "I wasn't able to map any of those blocks this time — data.gov.sg or Google Maps may be temporarily unavailable. Please try again shortly."


def block_venues_summary(towns: list[str], geocoded_count: int, total_count: int) -> str:
    town_list = _town_list(towns)
    lines = [
        f"📍 That's {geocoded_count} of {total_count} HDB block(s) in *{town_list}* "
        "(the most-transacted blocks first), sent above as interactive map pins — "
        "tap any pin to pan, zoom, or open it in your maps app for directions."
    ]
    if geocoded_count < total_count:
        lines.append(f"({total_count - geocoded_count} could not be located.)")
    return "\n".join(lines)


def no_carparks_message(towns: list[str]) -> str:
    return f"I checked {_town_list(towns)} but couldn't find any HDB carparks there, unfortunately."


def format_carpark_message(
    towns: list[str], carparks: list[dict], note: str | None = None, shown_limit: int = 15
) -> str:
    town_list = _town_list(towns)
    lines = [f"🅿️ Here are the carparks near *{town_list}*:", ""]
    if note:
        lines.append(f"ℹ️ {note}")
        lines.append("")

    for c in carparks[:shown_limit]:
        address = c["address"].title()
        lots = c.get("lots_available")
        total = c.get("total_lots")
        if lots is not None and total is not None:
            lots_str = f"{lots}/{total} lots available"
        else:
            lots_str = "live availability currently unavailable"

        flags = []
        if c.get("free_parking", "").upper() not in ("", "NO"):
            flags.append(f"free parking {c['free_parking'].lower()}")
        if c.get("night_parking", "").upper() == "YES":
            flags.append("night parking available")
        flags_str = f" ({', '.join(flags)})" if flags else ""

        lines.append(f"*{address}* — {lots_str}{flags_str}")

    if len(carparks) > shown_limit:
        lines.append(f"\n...and {len(carparks) - shown_limit} more.")

    lines.append("")
    lines.append(glossary.SOURCES_FOOTER)

    return "\n".join(lines).strip()


# Only "C" (Car) is documented with confidence across public sources; the
# other codes data.gov.sg's feed uses (H, Y, S, ...) don't have a
# consistently corroborated meaning, so rather than guess, they're shown as
# their raw code — inaccurate labelling would be worse than no label.
_LOT_TYPE_LABELS = {"C": "Car"}


def _lot_type_label(lot_type: str | None) -> str:
    if not lot_type:
        return "Lots"
    return _LOT_TYPE_LABELS.get(lot_type.upper(), f"Type {lot_type}")


def ask_which_carpark_message() -> str:
    return "Which carpark would you like to see on the map? Choose one below:"


def carpark_lots_breakdown_message(carpark: dict) -> str:
    address = carpark["address"].title()
    lots = carpark.get("lots") or []

    lines = [f"🅿️ *{address}*", ""]
    if not lots:
        lines.append("Live availability is not currently reporting for this carpark.")
    else:
        for lot in lots:
            label = _lot_type_label(lot.get("lot_type"))
            available = lot.get("lots_available")
            total = lot.get("total_lots")
            if available is not None and total is not None:
                lines.append(f"{label}: {available}/{total} lots available")
            else:
                lines.append(f"{label}: live availability not currently reporting")

    update_datetime = carpark.get("update_datetime")
    if update_datetime:
        lines.append("")
        lines.append(f"_Last updated: {update_datetime}_")

    lines.append("")
    lines.append(glossary.SOURCES_FOOTER)
    return "\n".join(lines).strip()


def compare_no_valid_localities_message(raw_entries: list[str]) -> str:
    entries_list = ", ".join(repr(e) for e in raw_entries)
    return (
        f"I wasn't able to match any of these: {entries_list}. Please try "
        "town names, postal codes, or district numbers, separated by commas."
    )


def compare_partial_failure_note(failed_entries: list[str]) -> str:
    return f"ℹ️ I couldn't match: {', '.join(repr(e) for e in failed_entries)} — showing the results for the rest."


def compare_too_many_note(dropped_count: int, max_entries: int) -> str:
    return f"ℹ️ I've compared the first {max_entries} areas only ({dropped_count} more were not included)."


def compare_no_data_message(labels: list[str]) -> str:
    label_list = ", ".join(labels)
    return f"I checked {label_list} but there is no recent resale data available for any of them, unfortunately."


def compare_chart_caption(labels: list[str], months_window: int) -> str:
    label_list = ", ".join(labels)
    return (
        f"📊 Average resale price by month, last {months_window} months — "
        f"{label_list}.\n\n{glossary.SOURCES_FOOTER}"
    )


def glossary_hint() -> str:
    return "Send /glossary at any time for definitions of HDB and property terms (e.g. MOP, COV, resale levy, PSF)."


def error_message() -> str:
    return "I'm sorry, something went wrong on my end 🙈. Please try again shortly, or send /start to begin again."


def cancelled_message() -> str:
    return "No problem, your request has been cancelled. Send /start anytime you'd like to check HDB prices again."
