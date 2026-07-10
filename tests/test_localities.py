import pytest

from hdb_bot.localities import (
    DISTRICT_TO_TOWNS,
    HDB_TOWNS,
    LocalityNotFound,
    resolve,
)


def test_postal_code_resolves_to_district_towns():
    # 560123 -> sector 56 -> district 20 -> Bishan/Ang Mo Kio
    match = resolve("560123")
    assert match.method == "postal_code"
    assert match.district == 20
    assert match.towns == DISTRICT_TO_TOWNS[20]


def test_postal_code_private_heavy_district_has_note():
    # 018956 -> sector 01 -> district 1 (Raffles Place, mostly private)
    match = resolve("018956")
    assert match.district == 1
    assert match.note is not None


@pytest.mark.parametrize("text", ["19", "D19", "d19", "district 19", "District 19"])
def test_district_number_variants(text):
    match = resolve(text)
    assert match.method == "district"
    assert match.district == 19
    assert match.towns == DISTRICT_TO_TOWNS[19]


def test_district_out_of_range_raises():
    with pytest.raises(LocalityNotFound):
        resolve("D29")
    with pytest.raises(LocalityNotFound):
        resolve("0")


def test_exact_town_name_case_insensitive():
    match = resolve("bishan")
    assert match.towns == ["BISHAN"]
    assert match.method == "town_exact"


def test_town_name_with_whitespace_variation():
    match = resolve("  toa   payoh  ")
    assert match.towns == ["TOA PAYOH"]


def test_alias_resolves():
    match = resolve("amk")
    assert match.towns == ["ANG MO KIO"]
    assert match.method == "town_alias"


def test_alias_substring_in_freeform_text():
    match = resolve("looking near cck area")
    assert match.towns == ["CHOA CHU KANG"]


def test_freeform_text_containing_town_name():
    match = resolve("somewhere near bishan lah")
    assert match.towns == ["BISHAN"]


def test_fuzzy_typo_resolves():
    match = resolve("tampinis")
    assert match.method == "town_fuzzy"
    assert match.towns == ["TAMPINES"]


def test_fuzzy_ambiguous_typo_raises_with_suggestions():
    # "bishn" is close to both BISHAN and YISHUN — should ask, not guess.
    with pytest.raises(LocalityNotFound) as exc_info:
        resolve("bishn")
    assert set(exc_info.value.suggestions) == {"BISHAN", "YISHUN"}


def test_no_match_raises_with_suggestions():
    with pytest.raises(LocalityNotFound) as exc_info:
        resolve("xyzabc123notaplace")
    assert exc_info.value.suggestions  # some fallback suggestions offered


def test_empty_input_raises():
    with pytest.raises(LocalityNotFound):
        resolve("   ")


def test_all_district_towns_are_valid_hdb_towns():
    for towns in DISTRICT_TO_TOWNS.values():
        for town in towns:
            assert town in HDB_TOWNS
