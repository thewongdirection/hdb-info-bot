"""Google Static Maps rendering for matched HDB towns.

Google Static Maps marker labels only support a single character, so there's
no way to bake a full price string onto a pin. Instead each matched town gets
a lettered pin (A, B, C...) and the caller renders a text legend mapping each
letter back to the town + its price stats (see formatting.py).
"""
from __future__ import annotations

import logging
import string
from dataclasses import dataclass
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

STATIC_MAPS_BASE = "https://maps.googleapis.com/maps/api/staticmap"

# Approximate town-centre coordinates for the 26 HDB towns. These are
# intentionally "town area" precision, not street-level — the underlying
# data.gov.sg datasets only carry a town field anyway, so a per-town pin
# is the right granularity for "map out the localities" rather than a
# false-precision per-block pin.
TOWN_CENTROIDS: dict[str, tuple[float, float]] = {
    "ANG MO KIO": (1.3691, 103.8454),
    "BEDOK": (1.3236, 103.9273),
    "BISHAN": (1.3526, 103.8352),
    "BUKIT BATOK": (1.3590, 103.7637),
    "BUKIT MERAH": (1.2819, 103.8239),
    "BUKIT PANJANG": (1.3774, 103.7719),
    "BUKIT TIMAH": (1.3294, 103.8021),
    "CENTRAL AREA": (1.2903, 103.8519),
    "CHOA CHU KANG": (1.3840, 103.7470),
    "CLEMENTI": (1.3151, 103.7654),
    "GEYLANG": (1.3181, 103.8830),
    "HOUGANG": (1.3612, 103.8863),
    "JURONG EAST": (1.3329, 103.7436),
    "JURONG WEST": (1.3404, 103.7090),
    "KALLANG/WHAMPOA": (1.3100, 103.8651),
    "MARINE PARADE": (1.3020, 103.9070),
    "PASIR RIS": (1.3721, 103.9474),
    "PUNGGOL": (1.4043, 103.9021),
    "QUEENSTOWN": (1.2942, 103.7861),
    "SEMBAWANG": (1.4491, 103.8185),
    "SENGKANG": (1.3868, 103.8914),
    "SERANGOON": (1.3554, 103.8679),
    "TAMPINES": (1.3496, 103.9568),
    "TOA PAYOH": (1.3343, 103.8563),
    "WOODLANDS": (1.4382, 103.7891),
    "YISHUN": (1.4304, 103.8354),
}


@dataclass
class MapResult:
    image_bytes: bytes
    legend: list[tuple[str, str]]  # (letter, town)


def build_static_map_url(
    towns: list[str],
    api_key: str,
    *,
    size: str = "640x400",
    scale: int = 2,
    maptype: str = "roadmap",
) -> tuple[str, list[tuple[str, str]]]:
    """Build a Google Static Maps URL with one lettered pin per known town.

    Returns (url, legend). Raises ValueError if none of the given towns have
    a known centroid (nothing to plot).
    """
    letters = string.ascii_uppercase
    marker_parts: list[str] = []
    legend: list[tuple[str, str]] = []

    for letter, town in zip(letters, towns[:26]):
        coords = TOWN_CENTROIDS.get(town.upper())
        if coords is None:
            logger.warning("No centroid known for town %r, skipping pin", town)
            continue
        lat, lng = coords
        marker_value = f"label:{letter}|color:red|{lat},{lng}"
        marker_parts.append(f"markers={quote(marker_value, safe='')}")
        legend.append((letter, town.upper()))

    if not marker_parts:
        raise ValueError("No known map coordinates for the given town(s)")

    query = "&".join(
        [f"size={size}", f"scale={scale}", f"maptype={maptype}"]
        + marker_parts
        + [f"key={quote(api_key, safe='')}"]
    )
    return f"{STATIC_MAPS_BASE}?{query}", legend


async def fetch_map_image(
    towns: list[str], api_key: str | None, *, timeout: float = 15.0
) -> MapResult | None:
    """Fetch the static map image server-side (key never reaches the user).

    Returns None if no API key is configured or none of the towns can be
    plotted — callers should degrade to text-only stats in that case.
    """
    if not api_key:
        return None
    try:
        url, legend = build_static_map_url(towns, api_key)
    except ValueError:
        return None

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return MapResult(image_bytes=resp.content, legend=legend)


# Google Static Maps' practical URL-length budget (~8KB) comfortably fits far
# more than this many "lat,lng" pairs, but a map crammed with more pins than
# this stops being readable at typical Telegram photo sizes anyway.
MAX_POINT_PINS = 100


def build_points_map_url(
    coords: list[tuple[float, float]],
    api_key: str,
    *,
    color: str = "blue",
    size: str = "640x400",
    scale: int = 2,
    maptype: str = "roadmap",
) -> str:
    """Build a Static Maps URL with one small unlabeled pin per coordinate.

    Used for "cloud of points" views (individual HDB blocks, carparks) where
    there are too many locations for per-pin letters/legends to be useful —
    Google auto-fits the viewport to the given points. Raises ValueError if
    `coords` is empty.
    """
    if not coords:
        raise ValueError("No coordinates to plot")

    points = "|".join(f"{lat},{lng}" for lat, lng in coords[:MAX_POINT_PINS])
    marker_value = f"color:{color}|size:small|{points}"
    query = "&".join(
        [
            f"size={size}",
            f"scale={scale}",
            f"maptype={maptype}",
            f"markers={quote(marker_value, safe='')}",
            f"key={quote(api_key, safe='')}",
        ]
    )
    return f"{STATIC_MAPS_BASE}?{query}"


async def fetch_points_map_image(
    coords: list[tuple[float, float]],
    api_key: str | None,
    *,
    color: str = "blue",
    timeout: float = 15.0,
) -> bytes | None:
    """Fetch a points-cloud static map image server-side.

    Returns None if no API key is configured or there are no coordinates —
    callers should degrade gracefully (text-only) in that case.
    """
    if not api_key or not coords:
        return None
    try:
        url = build_points_map_url(coords, api_key, color=color)
    except ValueError:
        return None

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content
