"""Randomized regression coverage for locality resolution.

Complements test_localities.py's example-based unit tests with property-
style checks: for every input *category* the bot has to handle (postal
codes, district numbers in various spellings, town names, aliases, street
names, typos, and outright gibberish), a batch of randomly generated
instances is thrown at resolve() and checked for accuracy.

The randomness is seeded (_SEED) so failures are reproducible — a flaky
regression suite defeats its own purpose. Every category here was
empirically verified against the real resolve() during development (not
just reasoned about on paper), including two genuine surprises that shaped
these tests:

- Pure alphabetic gibberish can accidentally trigger a real match, because
  some aliases are very short ("BB", "BT", "JE", ...) and the alias check
  is a substring search — a long enough random string has decent odds of
  containing one by chance. That's correct behavior of the resolver, not a
  bug, so the "unresolvable" category below uses curated, empirically
  verified real place names rather than pure noise; pure noise only gets a
  crash-safety check (never raises anything other than LocalityNotFound).
- A real bug this suite caught: any typo of "QUEENSTOWN" that kept the
  substring "town" intact used to resolve to CENTRAL AREA (the generic
  "TOWN" alias) instead of fuzzy-matching QUEENSTOWN, because the alias
  substring check ran before fuzzy matching got a chance. Fixed in
  localities.py by requiring a word-boundary match for aliases.
"""
from __future__ import annotations

import random
import string

import pytest

from hdb_bot.localities import (
    _SECTOR_RANGES,
    DISTRICT_TO_TOWNS,
    HDB_TOWNS,
    TOWN_ALIASES,
    LocalityNotFound,
    resolve,
)

_SEED = 20260711
_VARIATIONS_PER_ITEM = 4


def _rng() -> random.Random:
    """A fresh, identically-seeded RNG per test — order-independent and
    reproducible regardless of which tests run or in what order."""
    return random.Random(_SEED)


def _random_case(rng: random.Random, text: str) -> str:
    """Randomly upper/lower each letter. resolve() upper-cases its input
    first, so no case variation should ever change the outcome."""
    return "".join(rng.choice((c.upper(), c.lower())) for c in text)


def _one_char_typo(rng: random.Random, text: str) -> str:
    """Replace one random character with a different random letter."""
    i = rng.randrange(len(text))
    other_letters = [c for c in string.ascii_lowercase if c != text[i].lower()]
    return text[:i] + rng.choice(other_letters) + text[i + 1 :]


# --- Postal codes --------------------------------------------------------


def test_random_valid_postal_codes_resolve_to_the_correct_district():
    rng = _rng()
    for district, towns in DISTRICT_TO_TOWNS.items():
        sectors = _SECTOR_RANGES[district]
        for _ in range(_VARIATIONS_PER_ITEM):
            sector = rng.choice(sectors)
            postal_code = f"{sector:02d}{rng.randint(0, 9999):04d}"
            match = resolve(postal_code)
            assert match.method == "postal_code"
            assert match.district == district
            assert match.towns == towns


# --- District numbers, every spelling data entry supports -----------------

_DISTRICT_TEMPLATES = [
    "{d}", "D{d}", "d{d}", "District {d}", "district {d}", "D {d}", "DISTRICT{d}", "0{d}",
]


def test_random_district_spellings_resolve_to_the_correct_towns():
    rng = _rng()
    for district, towns in DISTRICT_TO_TOWNS.items():
        for _ in range(_VARIATIONS_PER_ITEM):
            template = rng.choice(_DISTRICT_TEMPLATES)
            text = template.format(d=district)
            match = resolve(text)
            assert match.method == "district"
            assert match.district == district
            assert match.towns == towns


def test_out_of_range_district_numbers_are_rejected():
    rng = _rng()
    for _ in range(20):
        n = rng.choice([0, 29, 30, 99, rng.randint(29, 200)])
        with pytest.raises(LocalityNotFound):
            resolve(f"D{n}")


# --- Town names, every case variation -------------------------------------


def test_random_case_variations_of_town_names_resolve_exactly():
    rng = _rng()
    for town in HDB_TOWNS:
        for _ in range(_VARIATIONS_PER_ITEM):
            text = _random_case(rng, town)
            match = resolve(text)
            assert match.towns == [town]
            # "MARINE PARADE" is also its own alias entry, so it can
            # legitimately resolve via either path.
            assert match.method in ("town_exact", "town_alias")


# --- Aliases, every case variation ----------------------------------------


def test_random_case_variations_of_aliases_resolve_to_the_canonical_town():
    rng = _rng()
    for alias, canonical_town in TOWN_ALIASES.items():
        for _ in range(_VARIATIONS_PER_ITEM):
            text = _random_case(rng, alias)
            match = resolve(text)
            assert match.towns == [canonical_town]


# --- Realistic street names ------------------------------------------------
# Empirically verified against resolve() -- see module docstring.

_STREETS_CONTAINING_A_TOWN_NAME = [
    ("Yishun Ring Road", "YISHUN"),
    ("Tampines Street 11", "TAMPINES"),
    ("Bedok North Avenue 2", "BEDOK"),
    ("Ang Mo Kio Avenue 3", "ANG MO KIO"),
    ("Choa Chu Kang Loop", "CHOA CHU KANG"),
    ("Jurong West Street 52", "JURONG WEST"),
    ("Serangoon North Avenue 1", "SERANGOON"),
    ("Woodlands Drive 16", "WOODLANDS"),
    ("Punggol Field", "PUNGGOL"),
    ("Sengkang East Way", "SENGKANG"),
    ("Clementi Avenue 4", "CLEMENTI"),
    ("Hougang Street 21", "HOUGANG"),
    ("Pasir Ris Drive 6", "PASIR RIS"),
    ("Bukit Batok West Avenue 8", "BUKIT BATOK"),
    ("Bukit Panjang Ring Road", "BUKIT PANJANG"),
    ("Toa Payoh Lorong 1", "TOA PAYOH"),
    ("Queenstown MRT", "QUEENSTOWN"),
    ("Geylang Road", "GEYLANG"),
]

_STREETS_WITH_NO_HDB_TOWN = [
    "Orchard Road",
    "Robertson Quay",
    "Clarke Quay",
    "Sentosa Cove",
    "Raffles Place",
    "Beach Road",
    "Dhoby Ghaut",
    "Somerset Road",
    "River Valley Road",
    "Holland Village",
    "East Coast Road",
]


@pytest.mark.parametrize("street,expected_town", _STREETS_CONTAINING_A_TOWN_NAME)
def test_realistic_street_names_resolve_to_the_town_they_contain(street, expected_town):
    match = resolve(street)
    assert match.towns == [expected_town]


@pytest.mark.parametrize("street", _STREETS_WITH_NO_HDB_TOWN)
def test_realistic_non_hdb_street_names_are_correctly_unresolvable(street):
    with pytest.raises(LocalityNotFound) as exc_info:
        resolve(street)
    assert exc_info.value.suggestions == []


# --- Single-character typos of town names ---------------------------------


def test_random_single_char_typos_of_town_names_stay_accurate():
    """A typo should never silently resolve to the *wrong* town. Either it
    fuzzy-matches the right one directly, or it's flagged as ambiguous —
    but the correct town must always be reachable, never just dropped."""
    rng = _rng()
    single_word_towns = [t for t in HDB_TOWNS if " " not in t and "/" not in t]
    for town in single_word_towns:
        for _ in range(3):
            typo = _one_char_typo(rng, town)
            try:
                match = resolve(typo)
                assert town in match.towns, (
                    f"typo {typo!r} of {town!r} resolved to {match.towns}, losing the real town"
                )
            except LocalityNotFound as exc:
                assert town in exc.suggestions, (
                    f"typo {typo!r} of {town!r} was rejected without {town} in suggestions "
                    f"(got {exc.suggestions})"
                )


# --- Crash-safety fuzzing --------------------------------------------------


def test_random_gibberish_never_raises_anything_but_locality_not_found():
    """Not an accuracy check (see module docstring — short aliases can
    legitimately match inside random noise) — just confirms resolve()
    never crashes with an unexpected exception on arbitrary junk input."""
    rng = _rng()
    alphabets = [string.ascii_lowercase, string.ascii_uppercase, string.digits, string.punctuation, " "]
    for _ in range(100):
        alphabet = "".join(rng.sample(alphabets, k=rng.randint(1, 3)))
        length = rng.randint(0, 20)
        text = "".join(rng.choice(alphabet) for _ in range(length)) if alphabet else ""
        try:
            resolve(text)
        except LocalityNotFound:
            pass
