import pytest

from hdb_bot.svy21 import svy21_to_wgs84


def test_origin_round_trips_to_known_lat_lon():
    lat, lon = svy21_to_wgs84(28001.642, 38744.572)
    assert lat == pytest.approx(1.366666, abs=1e-4)
    assert lon == pytest.approx(103.833333, abs=1e-4)


def test_known_carpark_lands_in_expected_area():
    # ACB: "BLK 270/271 ALBERT CENTRE BASEMENT CAR PARK" — near Bras Basah/Waterloo St.
    lat, lon = svy21_to_wgs84(30314.7936, 31490.4942)
    assert 1.29 < lat < 1.31
    assert 103.84 < lon < 103.86


def test_output_stays_within_singapore_bounding_box():
    # A handful of SVY21 coordinates spanning roughly the full extent of the island.
    samples = [
        (20000, 20000),
        (40000, 45000),
        (15000, 35000),
        (35000, 48000),
    ]
    for x, y in samples:
        lat, lon = svy21_to_wgs84(x, y)
        assert 1.1 < lat < 1.5
        assert 103.6 < lon < 104.1
