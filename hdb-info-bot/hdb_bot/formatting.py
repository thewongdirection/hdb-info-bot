"""Casual Singaporean-toned message templates.

Kept separate from stats.py so the number-crunching stays pure/testable and
the "voice" of the bot can be tweaked here without touching logic.
"""
from __future__ import annotations

from .stats import FlatTypeStats

INTENT_LABELS = {"buy": "buy", "sell": "sell", "rent": "rent"}

_INTENT_VERB = {
    "buy": "shopping for a place",
    "sell": "sizing up your flat",
    "rent": "hunting for a place to rent",
}

_TREND_EMOJI = {"up": "📈", "down": "📉", "flat": "➡️", "insufficient_data": ""}


def greeting() -> str:
    return (
        "Eh hello there! 👋 I'm your HDB kaki — tell me, you looking to *buy*, "
        "*sell*, or *rent* a flat?"
    )


def ask_locality(intent: str) -> str:
    verb = _INTENT_VERB.get(intent, "checking out")
    return (
        f"Steady, {verb} ah! Which area you keen on? Can just type the "
        "town (e.g. \"Bishan\"), a postal code (e.g. \"560123\"), or a "
        "district number (e.g. \"D19\" or \"19\")."
    )


def locality_not_found(raw_input: str, suggestions: list[str]) -> str:
    if suggestions:
        options = ", ".join(s.title() for s in suggestions)
        return (
            f"Hmm, dunno what area {raw_input!r} is leh 🤔. You mean one of "
            f"these: {options}? Try typing it again."
        )
    return (
        f"Paiseh, cannot make out what area {raw_input!r} is. Try a town "
        "name, 6-digit postal code, or district number (like D19)."
    )


def no_data_message(towns: list[str]) -> str:
    town_list = ", ".join(t.title() for t in towns)
    return (
        f"Wah, checked {town_list} but got very little or no recent "
        "transactions in our data leh. Maybe try a nearby town instead?"
    )


def _fmt_money(value: float) -> str:
    return f"${value:,.0f}"


def _fmt_flat_type(flat_type: str) -> str:
    # Resale dataset uses "3 ROOM", rental dataset uses "3-ROOM" — normalize
    # so both read the same way in a reply.
    return flat_type.replace("-", " ").title()


def _trend_phrase(stat: FlatTypeStats, intent: str) -> str:
    emoji = _TREND_EMOJI[stat.trend_label]
    if stat.trend_label == "insufficient_data":
        return "(not enough history yet for a trend)"
    verb = "gone up" if stat.trend_label == "up" else "dropped" if stat.trend_label == "down" else "stayed flat"
    return f"{emoji} {verb} {abs(stat.trend_pct):.1f}% vs. a year ago"


def format_stats_message(
    intent: str,
    towns: list[str],
    stats: list[FlatTypeStats],
    note: str | None = None,
    months_window: int = 12,
) -> str:
    town_list = ", ".join(t.title() for t in towns)
    unit = "/month" if intent == "rent" else ""

    lines = [f"Ok here's the lobang for *{town_list}* (last {months_window} months):", ""]
    if note:
        lines.append(f"ℹ️ {note}")
        lines.append("")

    for s in stats:
        lines.append(f"*{_fmt_flat_type(s.flat_type)}* — {s.count} transaction(s)")
        lines.append(
            f"  Median: {_fmt_money(s.median)}{unit}  "
            f"(typical range {_fmt_money(s.p25)}–{_fmt_money(s.p75)}{unit})"
        )
        lines.append(f"  Full range: {_fmt_money(s.min)} – {_fmt_money(s.max)}{unit}")
        lines.append(f"  Trend: {_trend_phrase(s, intent)}")
        lines.append("")

    if intent == "sell":
        lines.append("Use the median for similar unit types as your starting ask price lah 👍")
    elif intent == "buy":
        lines.append("Confirm plus chop, that's roughly what similar units are going for 👍")
    else:
        lines.append("That's the going rate for similar units in the area 👍")

    return "\n".join(lines).strip()


def map_caption(legend: list[tuple[str, str]]) -> str:
    lines = ["📍 Map legend:"]
    for letter, town in legend:
        lines.append(f"  {letter} — {town.title()}")
    return "\n".join(lines)


def error_message() -> str:
    return "Eh paiseh, something went wrong on my end 🙈. Try again in a bit, or /start over."


def cancelled_message() -> str:
    return "No worries, cancelled! Send /start anytime you want to check HDB prices again."
