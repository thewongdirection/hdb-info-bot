from pathlib import Path

import httpx
import pytest
import respx

from hdb_bot import carparks
from hdb_bot.datasets import CARPARK_INFO_DATASET


@pytest.fixture(autouse=True)
def _clear_cache():
    carparks.invalidate_cache()
    yield
    carparks.invalidate_cache()


def _write_carpark_csv(path: Path) -> None:
    header = "car_park_no,address,x_coord,y_coord,car_park_type,type_of_parking_system,short_term_parking,free_parking,night_parking\n"
    # ACB is near Bishan/Toa Payoh-ish central area coordinates in real life;
    # here we just need something that lands close to a known town centroid.
    rows = [
        "ACB,BLK 270/271 ALBERT CENTRE BASEMENT CAR PARK,30314.7936,31490.4942,BASEMENT CAR PARK,ELECTRONIC PARKING,WHOLE DAY,NO,YES",
        "BAD,BAD ROW,notanumber,31490.4942,SURFACE CAR PARK,ELECTRONIC PARKING,WHOLE DAY,NO,NO",
    ]
    path.write_text(header + "\n".join(rows) + "\n")


def _carpark_csv_path(tmp_path: Path) -> Path:
    return tmp_path / f"{CARPARK_INFO_DATASET.resource_id}.csv"


def test_get_carparks_for_towns_converts_coords_and_assigns_nearest_town(tmp_path):
    _write_carpark_csv(_carpark_csv_path(tmp_path))
    result = carparks.get_carparks_for_towns(["CENTRAL AREA"], data_dir=tmp_path)
    assert len(result) == 1
    c = result[0]
    assert c["car_park_no"] == "ACB"
    assert c["nearest_town"] == "CENTRAL AREA"
    assert 1.29 < c["lat"] < 1.31


def test_malformed_row_is_skipped_not_crashed(tmp_path):
    _write_carpark_csv(_carpark_csv_path(tmp_path))
    result = carparks.get_carparks_for_towns(["ANG MO KIO", "CENTRAL AREA", "BEDOK"], data_dir=tmp_path)
    # only the ACB row is valid; the BAD row's non-numeric x_coord is skipped
    assert len(result) == 1


def test_missing_csv_file_returns_empty_list(tmp_path):
    result = carparks.get_carparks_for_towns(["BISHAN"], data_dir=tmp_path)
    assert result == []


def test_cache_reused_until_invalidated(tmp_path):
    csv_path = _carpark_csv_path(tmp_path)
    _write_carpark_csv(csv_path)
    first = carparks.get_carparks_for_towns(["CENTRAL AREA"], data_dir=tmp_path)
    assert len(first) == 1

    csv_path.write_text("car_park_no,address,x_coord,y_coord,car_park_type,type_of_parking_system,short_term_parking,free_parking,night_parking\n")
    still_cached = carparks.get_carparks_for_towns(["CENTRAL AREA"], data_dir=tmp_path)
    assert len(still_cached) == 1

    carparks.invalidate_cache()
    refreshed = carparks.get_carparks_for_towns(["CENTRAL AREA"], data_dir=tmp_path)
    assert refreshed == []


@respx.mock
async def test_fetch_availability_parses_car_lot_type():
    respx.get(carparks.AVAILABILITY_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "carpark_data": [
                            {
                                "carpark_number": "ACB",
                                "update_datetime": "2026-01-01T00:00:00",
                                "carpark_info": [{"total_lots": "100", "lot_type": "C", "lots_available": "42"}],
                            }
                        ]
                    }
                ]
            },
        )
    )
    result = await carparks.fetch_availability()
    assert result == {
        "ACB": {"lots_available": 42, "total_lots": 100, "lot_type": "C", "update_datetime": "2026-01-01T00:00:00"}
    }


@respx.mock
async def test_fetch_availability_falls_back_when_no_car_lot_type():
    respx.get(carparks.AVAILABILITY_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "carpark_data": [
                            {
                                "carpark_number": "MOTO1",
                                "carpark_info": [{"total_lots": "10", "lot_type": "M", "lots_available": "3"}],
                            }
                        ]
                    }
                ]
            },
        )
    )
    result = await carparks.fetch_availability()
    assert result["MOTO1"]["lot_type"] == "M"


@respx.mock
async def test_fetch_availability_returns_empty_on_failure():
    respx.get(carparks.AVAILABILITY_URL).mock(return_value=httpx.Response(500))
    result = await carparks.fetch_availability()
    assert result == {}


def test_join_availability_sorts_most_available_first():
    matched = [
        {"car_park_no": "A", "address": "A"},
        {"car_park_no": "B", "address": "B"},
        {"car_park_no": "C", "address": "C"},
    ]
    availability = {
        "A": {"lots_available": 5, "total_lots": 100},
        "B": {"lots_available": 50, "total_lots": 100},
        # C has no live data at all
    }
    result = carparks.join_availability(matched, availability)
    assert [c["car_park_no"] for c in result] == ["B", "A", "C"]
    assert result[2].get("lots_available") is None
