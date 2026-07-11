"""Tests for ai_assistant.py's tools and the tool-use loop.

The tool functions are tested with local_store.load_town_records_multi
mocked (they're thin wrappers around stats.py/carparks.py, already covered
by their own test suites) -- these tests focus on the tool layer's own
responsibilities: locality resolution, argument validation, and shaping
results for the model. ask()'s tool-use loop is tested against a fake
Anthropic client so no real API calls happen.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from hdb_bot import ai_assistant


def _resale_record(town="BISHAN", flat_type="4 ROOM", month="2025-08", price=520000):
    return {
        "town": town,
        "flat_type": flat_type,
        "block": "123",
        "street_name": "BISHAN ST 11",
        "month": month,
        "resale_price": price,
    }


# --- individual tools -----------------------------------------------------


async def test_get_price_stats_returns_shaped_result(monkeypatch):
    records = [_resale_record(price=p) for p in (500000, 520000, 540000)]
    monkeypatch.setattr(
        ai_assistant.local_store, "load_town_records_multi", AsyncMock(return_value=records)
    )

    result = await ai_assistant._tool_get_price_stats("Bishan", "buy", months_window=12)

    assert result["towns"] == ["BISHAN"]
    assert len(result["stats_by_flat_type"]) == 1
    assert result["stats_by_flat_type"][0]["flat_type"] == "4 ROOM"
    assert result["stats_by_flat_type"][0]["count"] == 3


async def test_get_price_stats_rejects_bad_intent():
    result = await ai_assistant._tool_get_price_stats("Bishan", "invest")
    assert "error" in result


async def test_get_price_stats_unresolvable_locality_returns_suggestions():
    result = await ai_assistant._tool_get_price_stats("xyzabc123notaplace", "buy")
    assert "error" in result
    assert "suggestions" in result


async def test_get_price_stats_no_data_returns_empty_with_note(monkeypatch):
    monkeypatch.setattr(
        ai_assistant.local_store, "load_town_records_multi", AsyncMock(return_value=[])
    )
    result = await ai_assistant._tool_get_price_stats("Bishan", "buy")
    assert result["stats_by_flat_type"] == []
    assert "note" in result


async def test_get_price_trend_groups_by_flat_type(monkeypatch):
    records = [
        _resale_record(flat_type="3 ROOM", month="2025-07", price=400000),
        _resale_record(flat_type="3 ROOM", month="2025-08", price=410000),
        _resale_record(flat_type="4 ROOM", month="2025-08", price=520000),
    ]
    monkeypatch.setattr(
        ai_assistant.local_store, "load_town_records_multi", AsyncMock(return_value=records)
    )

    result = await ai_assistant._tool_get_price_trend("Bishan", "buy")

    assert set(result["monthly_average_by_flat_type"]) == {"3 ROOM", "4 ROOM"}


async def test_get_price_trend_rejects_bad_intent():
    result = await ai_assistant._tool_get_price_trend("Bishan", "invest")
    assert "error" in result


async def test_compare_localities_reports_unresolved_separately(monkeypatch):
    async def fake_load(datasets, towns):
        return [_resale_record(town=towns[0], price=500000)]

    monkeypatch.setattr(ai_assistant.local_store, "load_town_records_multi", fake_load)

    result = await ai_assistant._tool_compare_localities(["Bishan", "xyzabc123notaplace"])

    assert "Bishan" in result["monthly_average_resale_price_by_locality"]
    assert result["unresolved_localities"] == ["xyzabc123notaplace"]


async def test_compare_localities_caps_at_max(monkeypatch):
    seen_localities = []

    async def fake_load(datasets, towns):
        seen_localities.append(towns)
        return [_resale_record(town=towns[0])]

    monkeypatch.setattr(ai_assistant.local_store, "load_town_records_multi", fake_load)

    too_many = ["Bishan", "Tampines", "Bedok", "Yishun", "Punggol", "Sengkang", "Woodlands"]
    result = await ai_assistant._tool_compare_localities(too_many)

    assert len(seen_localities) == ai_assistant.MAX_COMPARE_LOCALITIES


async def test_get_carpark_availability_shapes_result(monkeypatch):
    monkeypatch.setattr(
        ai_assistant.carparks, "get_carparks_for_towns",
        MagicMock(return_value=[{"car_park_no": "A1", "address": "Blk 1 Bishan St", "lat": 1.35, "lng": 103.8}]),
    )
    monkeypatch.setattr(ai_assistant.carparks, "fetch_availability", AsyncMock(return_value={}))
    monkeypatch.setattr(
        ai_assistant.carparks, "join_availability",
        MagicMock(return_value=[{"address": "Blk 1 Bishan St", "lots_available": 10, "total_lots": 50, "lot_type": "C"}]),
    )

    result = await ai_assistant._tool_get_carpark_availability(
        "Bishan", data_gov_sg_api_key=None, http_client=None
    )

    assert result["towns"] == ["BISHAN"]
    assert result["carparks"][0]["lots_available"] == 10


async def test_get_carpark_availability_no_carparks_nearby(monkeypatch):
    monkeypatch.setattr(ai_assistant.carparks, "get_carparks_for_towns", MagicMock(return_value=[]))

    result = await ai_assistant._tool_get_carpark_availability(
        "Bishan", data_gov_sg_api_key=None, http_client=None
    )

    assert result["carparks"] == []
    assert "note" in result


async def test_get_carpark_availability_unresolvable_locality():
    result = await ai_assistant._tool_get_carpark_availability(
        "xyzabc123notaplace", data_gov_sg_api_key=None, http_client=None
    )
    assert "error" in result


async def test_rank_towns_returns_every_town_sorted_by_median(monkeypatch):
    rows = [
        {"town": "BISHAN", "flat_type": "4 ROOM", "count": 3, "mean": 520000, "median": 520000},
        {"town": "YISHUN", "flat_type": "4 ROOM", "count": 5, "mean": 400000, "median": 400000},
    ]
    monkeypatch.setattr(
        ai_assistant.local_store, "town_price_summary", MagicMock(return_value=rows)
    )

    result = await ai_assistant._tool_rank_towns("buy")

    assert [t["town"] for t in result["towns"]] == ["YISHUN", "BISHAN"]  # cheapest first


async def test_rank_towns_normalizes_flat_type_case(monkeypatch):
    summary_mock = MagicMock(return_value=[])
    monkeypatch.setattr(ai_assistant.local_store, "town_price_summary", summary_mock)

    await ai_assistant._tool_rank_towns("buy", flat_type="4-room".replace("-", " "))

    assert summary_mock.call_args.kwargs["flat_type"] == "4 ROOM"


async def test_rank_towns_rejects_bad_intent():
    result = await ai_assistant._tool_rank_towns("invest")
    assert "error" in result


async def test_rank_towns_no_data_returns_empty_with_note(monkeypatch):
    monkeypatch.setattr(
        ai_assistant.local_store, "town_price_summary", MagicMock(return_value=[])
    )
    result = await ai_assistant._tool_rank_towns("buy")
    assert result["towns"] == []
    assert "note" in result


# --- tool dispatch ----------------------------------------------------------


async def test_execute_tool_dispatches_by_name(monkeypatch):
    monkeypatch.setattr(
        ai_assistant, "_tool_get_price_stats", AsyncMock(return_value={"ok": True})
    )
    result = await ai_assistant._execute_tool(
        "get_price_stats", {"locality": "Bishan", "intent": "buy"},
        data_gov_sg_api_key=None, http_client=None,
    )
    assert result == {"ok": True}


async def test_execute_tool_dispatches_rank_towns(monkeypatch):
    monkeypatch.setattr(ai_assistant, "_tool_rank_towns", AsyncMock(return_value={"towns": []}))
    result = await ai_assistant._execute_tool(
        "rank_towns", {"intent": "buy"}, data_gov_sg_api_key=None, http_client=None
    )
    assert result == {"towns": []}


async def test_execute_tool_unknown_name_returns_error():
    result = await ai_assistant._execute_tool(
        "not_a_real_tool", {}, data_gov_sg_api_key=None, http_client=None
    )
    assert "error" in result


async def test_execute_tool_bad_arguments_returns_error_not_crash():
    result = await ai_assistant._execute_tool(
        "get_price_stats", {"locality": "Bishan"},  # missing required 'intent'
        data_gov_sg_api_key=None, http_client=None,
    )
    assert "error" in result


# --- ask() tool-use loop -----------------------------------------------------


def _text_response(text: str):
    return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=text)])


def _tool_use_response(name: str, tool_input: dict, tool_use_id: str = "tool_1"):
    return SimpleNamespace(
        stop_reason="tool_use",
        content=[SimpleNamespace(type="tool_use", id=tool_use_id, name=name, input=tool_input)],
    )


async def test_ask_returns_text_when_model_answers_directly():
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=_text_response("Prices in Bishan look stable."))

    answer = await ai_assistant.ask(
        "how's Bishan?", anthropic_client=client, data_gov_sg_api_key=None, http_client=None
    )

    assert answer == "Prices in Bishan look stable."
    client.messages.create.assert_awaited_once()


async def test_ask_executes_tool_then_returns_final_text(monkeypatch):
    monkeypatch.setattr(
        ai_assistant, "_tool_get_price_stats", AsyncMock(return_value={"towns": ["BISHAN"], "stats_by_flat_type": []})
    )
    client = MagicMock()
    client.messages.create = AsyncMock(
        side_effect=[
            _tool_use_response("get_price_stats", {"locality": "Bishan", "intent": "buy"}),
            _text_response("No recent transactions in Bishan."),
        ]
    )

    answer = await ai_assistant.ask(
        "buy price in bishan?", anthropic_client=client, data_gov_sg_api_key=None, http_client=None
    )

    assert answer == "No recent transactions in Bishan."
    assert client.messages.create.await_count == 2
    # The tool result must have been fed back as a user-role message.
    second_call_messages = client.messages.create.await_args_list[1].kwargs["messages"]
    assert second_call_messages[-1]["role"] == "user"
    assert second_call_messages[-1]["content"][0]["type"] == "tool_result"


async def test_ask_gives_up_after_max_iterations():
    client = MagicMock()
    client.messages.create = AsyncMock(
        return_value=_tool_use_response("get_price_stats", {"locality": "Bishan", "intent": "buy"})
    )

    answer = await ai_assistant.ask(
        "an endless question", anthropic_client=client, data_gov_sg_api_key=None, http_client=None
    )

    assert client.messages.create.await_count == ai_assistant.MAX_TOOL_ITERATIONS
    assert "more steps" in answer.lower()


async def test_ask_returns_fallback_text_for_empty_response():
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=_text_response(""))

    answer = await ai_assistant.ask(
        "???", anthropic_client=client, data_gov_sg_api_key=None, http_client=None
    )

    assert answer  # never returns an empty string
