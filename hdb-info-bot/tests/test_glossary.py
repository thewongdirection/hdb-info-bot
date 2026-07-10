from hdb_bot.glossary import GLOSSARY, SOURCES_FOOTER, explain, format_full_glossary


def test_explain_is_case_insensitive():
    assert explain("mop") is not None
    assert explain("MOP") is not None
    assert explain(" Mop ") is not None


def test_explain_unknown_term_returns_none():
    assert explain("not a real term") is None


def test_explain_returns_expansion_and_explanation():
    entry = explain("COV")
    assert entry.term == "COV"
    assert "Cash Over Valuation" in entry.expansion
    assert len(entry.explanation) > 0


def test_format_full_glossary_includes_every_term_and_sources_footer():
    text = format_full_glossary()
    for entry in GLOSSARY.values():
        assert entry.term in text
    assert SOURCES_FOOTER in text


def test_sources_footer_cites_official_bodies():
    for keyword in ("HDB", "CEA", "MND", "data.gov.sg"):
        assert keyword in SOURCES_FOOTER
