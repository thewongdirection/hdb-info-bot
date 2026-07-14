"""Resolve free-text/postal-code/district input into HDB town names.

The HDB resale & rental datasets on data.gov.sg only carry a `town` field
(e.g. "ANG MO KIO"), not postal codes or districts, so anything the user
types has to be mapped down to that fixed list of 26 towns before we can
query data.gov.sg.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

# The 26 HDB towns exactly as they appear in the data.gov.sg `town` field.
HDB_TOWNS: list[str] = [
    "ANG MO KIO", "BEDOK", "BISHAN", "BUKIT BATOK", "BUKIT MERAH",
    "BUKIT PANJANG", "BUKIT TIMAH", "CENTRAL AREA", "CHOA CHU KANG",
    "CLEMENTI", "GEYLANG", "HOUGANG", "JURONG EAST", "JURONG WEST",
    "KALLANG/WHAMPOA", "MARINE PARADE", "PASIR RIS", "PUNGGOL",
    "QUEENSTOWN", "SEMBAWANG", "SENGKANG", "SERANGOON", "TAMPINES",
    "TOA PAYOH", "WOODLANDS", "YISHUN",
]

# Common nicknames/abbreviations/typos -> canonical town name.
TOWN_ALIASES: dict[str, str] = {
    "AMK": "ANG MO KIO",
    "BB": "BUKIT BATOK",
    "BM": "BUKIT MERAH",
    "BP": "BUKIT PANJANG",
    "BT": "BUKIT TIMAH",
    "CCK": "CHOA CHU KANG",
    "JE": "JURONG EAST",
    "JW": "JURONG WEST",
    "KALLANG": "KALLANG/WHAMPOA",
    "WHAMPOA": "KALLANG/WHAMPOA",
    "MARINE PARADE": "MARINE PARADE",
    "TPY": "TOA PAYOH",
    "TOWN": "CENTRAL AREA",
    "CITY": "CENTRAL AREA",
    "CHINATOWN": "CENTRAL AREA",
    "TIONG BAHRU": "BUKIT MERAH",
    "TELOK BLANGAH": "BUKIT MERAH",
    "HARBOURFRONT": "BUKIT MERAH",
    "DAWSON": "QUEENSTOWN",
    "COMMONWEALTH": "QUEENSTOWN",
    "EUNOS": "GEYLANG",
    "PAYA LEBAR": "GEYLANG",
    "KATONG": "MARINE PARADE",
    "JOO CHIAT": "MARINE PARADE",
    "SERANGOON GARDEN": "SERANGOON",
    "YIO CHU KANG": "ANG MO KIO",
    "NOVENA": "TOA PAYOH",
    "BALESTIER": "TOA PAYOH",
    "WOODLEIGH": "TOA PAYOH",
    "ADMIRALTY": "WOODLANDS",
    "KRANJI": "WOODLANDS",
}

# Singapore postal districts (1-28) -> HDB town(s) covering that district.
# Districts are postal-sector groupings that don't line up cleanly with HDB
# town boundaries; several central/prime districts (9, 10, etc.) are mostly
# private housing with little or no HDB resale stock, so they map to the
# nearest HDB town(s) and `resolve()` attaches an explanatory note.
DISTRICT_TO_TOWNS: dict[int, list[str]] = {
    1: ["CENTRAL AREA"],
    2: ["CENTRAL AREA"],
    3: ["QUEENSTOWN", "BUKIT MERAH"],
    4: ["BUKIT MERAH"],
    5: ["CLEMENTI"],
    6: ["CENTRAL AREA"],
    7: ["CENTRAL AREA"],
    8: ["KALLANG/WHAMPOA"],
    9: ["BUKIT TIMAH"],
    10: ["BUKIT TIMAH"],
    11: ["TOA PAYOH", "BUKIT TIMAH"],
    12: ["TOA PAYOH", "SERANGOON"],
    13: ["TOA PAYOH", "GEYLANG"],
    14: ["GEYLANG"],
    15: ["MARINE PARADE"],
    16: ["BEDOK"],
    17: ["PASIR RIS"],
    18: ["TAMPINES", "PASIR RIS"],
    19: ["HOUGANG", "PUNGGOL", "SERANGOON"],
    20: ["BISHAN", "ANG MO KIO"],
    21: ["BUKIT TIMAH", "CLEMENTI"],
    22: ["JURONG EAST", "JURONG WEST"],
    23: ["BUKIT PANJANG", "CHOA CHU KANG"],
    24: ["CHOA CHU KANG"],
    25: ["WOODLANDS"],
    26: ["YISHUN", "ANG MO KIO"],
    27: ["YISHUN", "SEMBAWANG"],
    28: ["ANG MO KIO", "SENGKANG"],
}

# Districts with essentially no HDB resale stock (private housing dominant) —
# used only to attach a heads-up note, resolution still returns nearest towns.
PRIVATE_HEAVY_DISTRICTS = {1, 2, 4, 6, 7, 9, 10, 21}

# First two digits of a 6-digit postal code -> district number.
_SECTOR_TO_DISTRICT: dict[int, int] = {}
_SECTOR_RANGES: dict[int, list[int]] = {
    1: [1, 2, 3, 4, 5, 6], 2: [7, 8], 3: [14, 15, 16], 4: [9, 10],
    5: [11, 12, 13], 6: [17], 7: [18, 19], 8: [20, 21],
    9: [22, 23], 10: [24, 25, 26, 27], 11: [28, 29, 30], 12: [31, 32, 33],
    13: [34, 35, 36, 37], 14: [38, 39, 40, 41], 15: [42, 43, 44, 45],
    16: [46, 47, 48], 17: [49, 50, 81], 18: [51, 52], 19: [53, 54, 55, 82],
    20: [56, 57], 21: [58, 59], 22: [60, 61, 62, 63, 64], 23: [65, 66, 67, 68],
    24: [69, 70, 71], 25: [72, 73], 26: [77, 78], 27: [75, 76], 28: [79, 80],
}
for _district, _sectors in _SECTOR_RANGES.items():
    for _sector in _sectors:
        _SECTOR_TO_DISTRICT[_sector] = _district
del _district, _sectors, _sector


@dataclass
class LocalityMatch:
    towns: list[str]
    method: str  # "postal_code" | "district" | "town_exact" | "town_alias" | "town_fuzzy"
    district: int | None = None
    note: str | None = None
    raw_input: str = ""


class LocalityNotFound(Exception):
    """Raised when the input text can't be resolved to any HDB town."""

    def __init__(self, message: str, suggestions: list[str] | None = None):
        super().__init__(message)
        self.suggestions = suggestions or []


_DISTRICT_PATTERN = re.compile(r"^(?:D|DISTRICT)?\s*0*(\d{1,2})$")


def _district_note(district: int) -> str | None:
    if district in PRIVATE_HEAVY_DISTRICTS:
        return (
            f"District {district} is mostly private housing with very little "
            "HDB resale stock, so showing the nearest HDB town(s) instead."
        )
    return None


def resolve(text: str) -> LocalityMatch:
    """Resolve free text into one or more canonical HDB town names.

    Tries, in order: 6-digit postal code, district number (various
    spellings), exact town name, known alias, then fuzzy match. Raises
    LocalityNotFound (with suggestions) if nothing matches with confidence.
    """
    raw = text
    cleaned = text.strip().upper()
    cleaned = re.sub(r"\s+", " ", cleaned)

    if not cleaned:
        raise LocalityNotFound("Empty input", suggestions=[])

    # 1. Six-digit postal code.
    if re.fullmatch(r"\d{6}", cleaned):
        sector = int(cleaned[:2])
        district = _SECTOR_TO_DISTRICT.get(sector)
        if district is None:
            raise LocalityNotFound(f"Unrecognised postal sector in {cleaned!r}", suggestions=[])
        return LocalityMatch(
            towns=DISTRICT_TO_TOWNS[district],
            method="postal_code",
            district=district,
            note=_district_note(district),
            raw_input=raw,
        )

    # 2. District number: "19", "D19", "d 19", "district 19".
    district_m = _DISTRICT_PATTERN.match(cleaned)
    if district_m:
        district = int(district_m.group(1))
        if district in DISTRICT_TO_TOWNS:
            return LocalityMatch(
                towns=DISTRICT_TO_TOWNS[district],
                method="district",
                district=district,
                note=_district_note(district),
                raw_input=raw,
            )
        raise LocalityNotFound(f"District {district} is out of range (1-28)", suggestions=[])

    # 3. Exact alias match.
    if cleaned in TOWN_ALIASES:
        return LocalityMatch(towns=[TOWN_ALIASES[cleaned]], method="town_alias", raw_input=raw)

    # 4. Exact town match.
    if cleaned in HDB_TOWNS:
        return LocalityMatch(towns=[cleaned], method="town_exact", raw_input=raw)

    # 5. Substring match against town names / aliases (e.g. "near bishan").
    contains_hits = [t for t in HDB_TOWNS if t in cleaned or cleaned in t]
    if len(contains_hits) == 1:
        return LocalityMatch(towns=contains_hits, method="town_exact", raw_input=raw)

    # Word-boundary, not a bare substring check: a handful of aliases are
    # short, generic word fragments ("TOWN", "BB", "BT", ...) that can
    # appear glued inside an unrelated or misspelled word purely by chance
    # (e.g. "TOWN" is literally the tail end of "QUEENSTOWN" — a bare
    # substring check would misroute any typo of a real town to whatever
    # that fragment aliases to, before fuzzy matching ever gets a chance to
    # find the actual closest town).
    for alias, town in TOWN_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", cleaned):
            return LocalityMatch(towns=[town], method="town_alias", raw_input=raw)

    # 6. Fuzzy match (typos, partial words) against towns + aliases.
    #
    # A bare SequenceMatcher.ratio() cutoff isn't enough: it scores how many
    # characters match in total without caring whether the input and
    # candidate are even close in length. "SENTOSA" (7 chars) vs the
    # "EUNOS" alias (5 chars) scores 0.667 — comfortably over the 0.6
    # cutoff — purely from a handful of scattered single-character
    # coincidences, not real similarity. That let "Sentosa" (a resort
    # island with zero HDB flats) resolve confidently to GEYLANG.
    #
    # Requiring the two strings to be close in length fixes that, but a
    # flat length-ratio requirement is too strict on its own: legitimate
    # matches like "downtown" -> the "TOWN" alias are exactly this
    # shape — a short candidate against a much longer input — and must
    # keep working. What makes "downtown" legitimate is that "TOWN"
    # matches *in full*, as one unbroken run, i.e. it's a genuine substring
    # of the input rather than scattered fragments. So a large length gap
    # is only forgiven when the shorter string is fully, contiguously
    # contained in the longer one.
    candidates = HDB_TOWNS + list(TOWN_ALIASES.keys())
    scored = []
    for c in candidates:
        matcher = difflib.SequenceMatcher(None, cleaned, c)
        ratio = matcher.ratio()
        if ratio < 0.6:
            continue
        shorter_len = min(len(cleaned), len(c))
        longer_len = max(len(cleaned), len(c))
        if shorter_len / longer_len < 0.8:
            longest_run = max(
                (m.size for m in matcher.get_matching_blocks()), default=0
            )
            if longest_run < shorter_len:
                continue
        scored.append((ratio, c))
    scored.sort(key=lambda item: item[0], reverse=True)
    close = [c for _, c in scored[:3]]
    resolved_towns = []
    for c in close:
        town = TOWN_ALIASES.get(c, c)
        if town not in resolved_towns:
            resolved_towns.append(town)

    if len(resolved_towns) == 1:
        return LocalityMatch(towns=resolved_towns, method="town_fuzzy", raw_input=raw)

    if len(resolved_towns) > 1:
        raise LocalityNotFound(
            f"{raw!r} is ambiguous, could be: {', '.join(resolved_towns)}",
            suggestions=resolved_towns,
        )

    # Nothing matched at all. Deliberately no generic filler suggestions
    # here — conversation.py tries a geocoding-based "nearest actual HDB
    # town" suggestion for this exact case (empty suggestions signals that
    # nothing string-matched), and only falls back to a bare "not found"
    # message if that isn't available or doesn't find anything either.
    raise LocalityNotFound(f"Couldn't figure out what area {raw!r} means", suggestions=[])
