from urllib.parse import unquote

import httpx
import pytest
import respx

from hdb_bot.maps import (
    MAX_POINT_PINS,
    build_points_map_url,
    build_static_map_url,
    fetch_map_image,
    fetch_points_map_image,
)


def test_single_town_marker_and_legend():
    url, legend = build_static_map_url(["BISHAN"], api_key="fake-key")
    assert legend == [("A", "BISHAN")]
    assert "key=fake-key" in url
    assert url.count("markers=") == 1
    assert "label:A|color:red|1.3526,103.8352" in unquote(url)


def test_multiple_towns_get_sequential_letters():
    url, legend = build_static_map_url(["BISHAN", "TAMPINES", "YISHUN"], api_key="fake-key")
    assert legend == [("A", "BISHAN"), ("B", "TAMPINES"), ("C", "YISHUN")]
    assert url.count("markers=") == 3


def test_unknown_town_is_skipped_not_crashed():
    url, legend = build_static_map_url(["BISHAN", "NOT_A_REAL_TOWN"], api_key="fake-key")
    assert legend == [("A", "BISHAN")]
    assert url.count("markers=") == 1


def test_all_unknown_towns_raises_value_error():
    with pytest.raises(ValueError):
        build_static_map_url(["NOT_A_REAL_TOWN"], api_key="fake-key")


def test_api_key_is_urlencoded():
    url, _ = build_static_map_url(["BISHAN"], api_key="a key/with?special&chars")
    assert "key=a%20key%2Fwith%3Fspecial%26chars" in url


async def test_fetch_map_image_returns_none_without_api_key():
    result = await fetch_map_image(["BISHAN"], api_key=None)
    assert result is None


async def test_fetch_map_image_returns_none_for_unknown_towns():
    result = await fetch_map_image(["NOT_A_REAL_TOWN"], api_key="fake-key")
    assert result is None


@respx.mock
async def test_fetch_map_image_returns_bytes_and_legend():
    respx.get(url__startswith="https://maps.googleapis.com/maps/api/staticmap").mock(
        return_value=httpx.Response(200, content=b"fake-png-bytes")
    )
    result = await fetch_map_image(["BISHAN"], api_key="fake-key")
    assert result is not None
    assert result.image_bytes == b"fake-png-bytes"
    assert result.legend == [("A", "BISHAN")]


def test_build_points_map_url_encodes_all_coordinates():
    coords = [(1.35, 103.85), (1.30, 103.80)]
    url = build_points_map_url(coords, api_key="fake-key")
    assert "key=fake-key" in url
    assert url.count("markers=") == 1
    decoded = unquote(url)
    assert "color:blue|size:small|1.35,103.85|1.3,103.8" in decoded


def test_build_points_map_url_empty_raises():
    with pytest.raises(ValueError):
        build_points_map_url([], api_key="fake-key")


def test_build_points_map_url_caps_pin_count():
    coords = [(1.3 + i * 0.001, 103.8) for i in range(MAX_POINT_PINS + 20)]
    url = build_points_map_url(coords, api_key="fake-key")
    decoded = unquote(url)
    marker_value = decoded.split("markers=")[1].split("&key=")[0]
    points = marker_value.split("|")[2:]
    assert len(points) == MAX_POINT_PINS


def test_build_points_map_url_custom_color():
    url = build_points_map_url([(1.3, 103.8)], api_key="fake-key", color="green")
    assert "color:green" in unquote(url)


async def test_fetch_points_map_image_returns_none_without_api_key():
    assert await fetch_points_map_image([(1.3, 103.8)], api_key=None) is None


async def test_fetch_points_map_image_returns_none_for_empty_coords():
    assert await fetch_points_map_image([], api_key="fake-key") is None


@respx.mock
async def test_fetch_points_map_image_returns_bytes():
    respx.get(url__startswith="https://maps.googleapis.com/maps/api/staticmap").mock(
        return_value=httpx.Response(200, content=b"fake-blocks-png")
    )
    result = await fetch_points_map_image([(1.3, 103.8)], api_key="fake-key")
    assert result == b"fake-blocks-png"
