"""Town-centroid coordinates for HDB towns, and a nearest-town lookup.

Used by carparks.py to approximate a carpark's town from its coordinates
(carpark records carry lat/lng but no town field), and by conversation.py to
suggest an HDB town when a user's free-text area doesn't match anything —
see `nearest_town`.
"""
from __future__ import annotations

# Approximate town-centre coordinates for the 26 HDB towns. These are
# intentionally "town area" precision, not street-level — the underlying
# data.gov.sg datasets only carry a town field anyway.
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


def nearest_town(lat: float, lng: float) -> str:
    """The HDB town whose centroid is closest to (lat, lng).

    Singapore is small/flat enough that plain squared-degree distance is
    fine for "nearest of 26" — no need for a real haversine calculation."""
    return min(
        TOWN_CENTROIDS,
        key=lambda town: (TOWN_CENTROIDS[town][0] - lat) ** 2 + (TOWN_CENTROIDS[town][1] - lng) ** 2,
    )
