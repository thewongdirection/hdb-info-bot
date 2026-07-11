"""Natural-language querying over the bot's HDB datasets, via Claude tool use.

The model is strictly an orchestrator/summarizer, never a source of truth.
Every tool call bottoms out in the exact same deterministic code
(local_store.py, stats.py, carparks.py) that already powers the
button-based flow — the model decides *which* tool(s) to call and phrases
the final answer from their real, computed results, but it never invents a
price, trend, or lots-available figure itself. This mirrors the rest of
the bot's design: no asserting a number the data doesn't literally
support (see formatting.py's citation footer and glossary.py's
concepts-not-specifics approach to regulatory content).
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict
from typing import Any

from anthropic import AsyncAnthropic

from . import carparks, local_store
from .datasets import DATASETS_FOR_INTENT
from .localities import LocalityNotFound, resolve
from .stats import group_by_flat_type, monthly_average_series, summarize

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-5"
MAX_TOKENS = 1024
MAX_TOOL_ITERATIONS = 5
MAX_COMPARE_LOCALITIES = 6

SYSTEM_PROMPT = """\
You are a data-lookup assistant embedded inside a Telegram bot that provides \
HDB (Singapore public housing) resale/rental price and carpark information, \
sourced from data.gov.sg.

Ground rules:
- You can ONLY state numbers that came from a tool result in this \
conversation. Never estimate, recall from your own knowledge, or round in a \
way that isn't directly traceable to a tool's output.
- If a tool call errors or returns no data, say so plainly and suggest a \
nearby town or a different question, rather than guessing.
- If the user's question needs a locality (town, postal code, or district) \
you weren't given, ask a brief clarifying question instead of assuming one.
- You provide general market information only, not financial, legal, or \
property advice. Do not recommend whether someone should buy, sell, rent, or \
invest. Do not state specific regulatory figures (MOP duration, resale levy \
amounts, eligibility rules, etc.) since these vary by case and change over \
time — point users to HDB, CEA, or MND for authoritative rules, and mention \
they can send /glossary for definitions of terms like MOP, COV, or PSF.
- Keep answers conversational and concise: a sentence or two of \
interpretation plus the concrete figures, not a wall of text.
"""

TOOLS: list[dict] = [
    {
        "name": "get_price_stats",
        "description": (
            "Get resale/rental price statistics (count, median, mean, range, "
            "year-on-year trend) for an HDB town, broken down by flat type, "
            "over a recent window of months."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "locality": {
                    "type": "string",
                    "description": "A town name, 6-digit postal code, or district number/name, e.g. 'Bishan', '560123', 'D19'.",
                },
                "intent": {
                    "type": "string",
                    "enum": ["buy", "sell", "rent"],
                    "description": "'buy' and 'sell' both look at resale price data; 'rent' looks at rental data.",
                },
                "months_window": {
                    "type": "integer",
                    "description": "How many recent months to include. Default 12.",
                },
            },
            "required": ["locality", "intent"],
        },
    },
    {
        "name": "get_price_trend",
        "description": (
            "Get a month-by-month average price series per flat type for an "
            "HDB town — use this when the user asks how prices have moved or "
            "changed over time, rather than just the current snapshot."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "locality": {"type": "string"},
                "intent": {"type": "string", "enum": ["buy", "sell", "rent"]},
                "months_window": {
                    "type": "integer",
                    "description": "How many recent months to include. Default 12.",
                },
            },
            "required": ["locality", "intent"],
        },
    },
    {
        "name": "compare_localities",
        "description": "Compare average monthly resale prices across multiple HDB towns/districts over time.",
        "input_schema": {
            "type": "object",
            "properties": {
                "localities": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "2-6 town names, postal codes, or district numbers to compare.",
                },
                "months_window": {
                    "type": "integer",
                    "description": "How many recent months to include. Default 24.",
                },
            },
            "required": ["localities"],
        },
    },
    {
        "name": "get_carpark_availability",
        "description": "Get nearby HDB carparks and their live lots-available counts for a town/area.",
        "input_schema": {
            "type": "object",
            "properties": {
                "locality": {"type": "string"},
            },
            "required": ["locality"],
        },
    },
]


def _resolve_or_error(locality: str) -> tuple[list[str] | None, dict | None]:
    """Returns (towns, None) on success or (None, error_dict) on failure —
    every tool below shares this exact not-found shape."""
    try:
        match = resolve(locality)
    except LocalityNotFound as exc:
        return None, {
            "error": f"Could not resolve {locality!r} to a known HDB town.",
            "suggestions": exc.suggestions,
        }
    return match.towns, None


async def _tool_get_price_stats(locality: str, intent: str, months_window: int = 12) -> dict:
    if intent not in DATASETS_FOR_INTENT:
        return {"error": f"intent must be one of {sorted(DATASETS_FOR_INTENT)}, got {intent!r}"}
    towns, error = _resolve_or_error(locality)
    if error:
        return error

    datasets = DATASETS_FOR_INTENT[intent]
    records = await local_store.load_town_records_multi(datasets, towns)
    stats = summarize(
        records,
        price_field=datasets[0].price_field,
        month_field=datasets[0].month_field,
        months_window=months_window,
    )
    if not stats:
        return {"towns": towns, "months_window": months_window, "stats_by_flat_type": [], "note": "no recent transactions found"}
    return {
        "towns": towns,
        "months_window": months_window,
        "stats_by_flat_type": [asdict(s) for s in stats],
    }


async def _tool_get_price_trend(locality: str, intent: str, months_window: int = 12) -> dict:
    if intent not in DATASETS_FOR_INTENT:
        return {"error": f"intent must be one of {sorted(DATASETS_FOR_INTENT)}, got {intent!r}"}
    towns, error = _resolve_or_error(locality)
    if error:
        return error

    datasets = DATASETS_FOR_INTENT[intent]
    records = await local_store.load_town_records_multi(datasets, towns)
    series_by_type: dict[str, list[tuple[str, float]]] = {}
    for flat_type, recs in group_by_flat_type(records).items():
        points = monthly_average_series(
            recs,
            price_field=datasets[0].price_field,
            month_field=datasets[0].month_field,
            months_window=months_window,
        )
        if points:
            series_by_type[flat_type] = points

    if not series_by_type:
        return {"towns": towns, "months_window": months_window, "monthly_average_by_flat_type": {}, "note": "not enough recent data to chart a trend"}
    return {"towns": towns, "months_window": months_window, "monthly_average_by_flat_type": series_by_type}


async def _tool_compare_localities(localities: list[str], months_window: int = 24) -> dict:
    datasets = DATASETS_FOR_INTENT["buy"]
    localities = localities[:MAX_COMPARE_LOCALITIES]

    async def _series_for(locality: str) -> tuple[str, list[tuple[str, float]] | None]:
        towns, error = _resolve_or_error(locality)
        if error:
            return locality, None
        records = await local_store.load_town_records_multi(datasets, towns)
        points = monthly_average_series(
            records,
            price_field=datasets[0].price_field,
            month_field=datasets[0].month_field,
            months_window=months_window,
        )
        return locality, points or None

    results = await asyncio.gather(*(_series_for(loc) for loc in localities))
    resolved = {loc: points for loc, points in results if points is not None}
    unresolved = [loc for loc, points in results if points is None]
    return {
        "monthly_average_resale_price_by_locality": resolved,
        "unresolved_localities": unresolved,
        "months_window": months_window,
    }


async def _tool_get_carpark_availability(
    locality: str, *, data_gov_sg_api_key: str | None, http_client
) -> dict:
    towns, error = _resolve_or_error(locality)
    if error:
        return error

    matched = await asyncio.to_thread(carparks.get_carparks_for_towns, towns)
    if not matched:
        return {"towns": towns, "carparks": [], "note": "no HDB carparks found nearby"}

    availability = await carparks.fetch_availability(data_gov_sg_api_key, client=http_client)
    enriched = carparks.join_availability(matched, availability)
    return {
        "towns": towns,
        "carparks": [
            {
                "address": c["address"],
                "lots_available": c.get("lots_available"),
                "total_lots": c.get("total_lots"),
                "lot_type": c.get("lot_type"),
            }
            for c in enriched[:20]
        ],
    }


async def _execute_tool(name: str, tool_input: dict, *, data_gov_sg_api_key: str | None, http_client) -> dict:
    try:
        if name == "get_price_stats":
            return await _tool_get_price_stats(**tool_input)
        if name == "get_price_trend":
            return await _tool_get_price_trend(**tool_input)
        if name == "compare_localities":
            return await _tool_compare_localities(**tool_input)
        if name == "get_carpark_availability":
            return await _tool_get_carpark_availability(
                **tool_input, data_gov_sg_api_key=data_gov_sg_api_key, http_client=http_client
            )
        return {"error": f"Unknown tool {name!r}"}
    except TypeError as exc:
        # Bad/missing arguments from the model -- report back as a tool
        # error so it can retry, rather than crashing the conversation.
        logger.warning("Tool %s called with bad arguments %r: %s", name, tool_input, exc)
        return {"error": f"Invalid arguments for {name}: {exc}"}


def _extract_text(content_blocks: list[Any]) -> str:
    return "".join(block.text for block in content_blocks if block.type == "text").strip()


async def ask(
    question: str,
    *,
    anthropic_client: AsyncAnthropic,
    data_gov_sg_api_key: str | None,
    http_client,
) -> str:
    """Run the full tool-use loop for one user question, returning the
    model's final natural-language answer.

    Never raises for "the model didn't behave" cases (bad tool args, no
    data found) — those come back as a plain-English answer describing the
    problem, same as everything else in this module. Real API failures
    (auth, network, rate limit) do propagate, since the caller needs to
    show a distinct "AI service unavailable" message for those.
    """
    messages: list[dict] = [{"role": "user", "content": question}]

    for _ in range(MAX_TOOL_ITERATIONS):
        response = await anthropic_client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        if response.stop_reason != "tool_use":
            text = _extract_text(response.content)
            return text or "I wasn't able to come up with an answer for that — could you rephrase the question?"

        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            result = await _execute_tool(
                block.name, block.input, data_gov_sg_api_key=data_gov_sg_api_key, http_client=http_client
            )
            tool_results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(result)}
            )
        messages.append({"role": "user", "content": tool_results})

    return (
        "That question needed more steps than I'm allowed to take in one go — "
        "could you ask something a bit more specific?"
    )
