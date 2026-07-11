"""HDB / property jargon glossary + citation footer.

Explanations here are deliberately general and stable — durations, dollar
amounts, and percentages for things like MOP or resale levy change over
time and differ by flat type/scheme, so rather than state a specific
figure that could go stale or be wrong for a given case, each entry
describes the concept and points to the authoritative source for current
specifics. This bot is not a substitute for official guidance.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GlossaryEntry:
    term: str
    expansion: str
    explanation: str


# Ordered roughly by how often a user is likely to encounter the term.
GLOSSARY: dict[str, GlossaryEntry] = {
    "MOP": GlossaryEntry(
        "MOP", "Minimum Occupation Period",
        "The minimum period an owner must physically occupy their flat before "
        "they may sell it on the open market, rent it out in full, or buy "
        "private property. It varies by flat type and purchase scheme — HDB's "
        "website has the exact duration for a given flat.",
    ),
    "COV": GlossaryEntry(
        "COV", "Cash Over Valuation",
        "The amount a buyer pays in cash above a flat's official HDB valuation, "
        "on top of the loan- and CPF-financed portion. Whether any COV applies, "
        "and how much, is a matter of negotiation between buyer and seller.",
    ),
    "RESALE LEVY": GlossaryEntry(
        "Resale Levy", "Resale Levy",
        "A charge payable by some buyers of a second subsidised HDB flat, "
        "intended to keep the housing subsidy fair across buyers. Whether it "
        "applies, and how much, depends on the buyer's flat purchase history.",
    ),
    "OTP": GlossaryEntry(
        "OTP", "Option to Purchase",
        "A legal document that gives a buyer the exclusive right to buy a "
        "specific flat within a set period, once signed and the option fee "
        "is paid. It is a formal step in the HDB resale process.",
    ),
    "EIP": GlossaryEntry(
        "EIP", "Ethnic Integration Policy",
        "HDB quotas, by ethnic group, for each block and neighbourhood, meant "
        "to support ethnic diversity in public housing. It can affect who is "
        "eligible to buy a specific resale flat.",
    ),
    "SPR": GlossaryEntry(
        "SPR", "Singapore Permanent Resident",
        "A non-citizen granted permanent residency in Singapore; SPR "
        "households have different HDB eligibility and grant rules than "
        "citizen households.",
    ),
    "CPF": GlossaryEntry(
        "CPF", "Central Provident Fund",
        "Singapore's mandatory savings scheme. CPF savings can be used towards "
        "an HDB down payment and mortgage instalments, subject to rules on "
        "withdrawal limits and the flat's remaining lease.",
    ),
    "HFE LETTER": GlossaryEntry(
        "HFE Letter", "HDB Flat Eligibility Letter",
        "A letter confirming a household's eligibility to buy a flat and the "
        "housing loan/grants it may qualify for — typically needed before "
        "starting a flat purchase.",
    ),
    "BTO": GlossaryEntry(
        "BTO", "Build-To-Order",
        "HDB's main scheme for selling new flats, built after enough demand "
        "for a project is registered, as opposed to buying an existing "
        "(resale) flat.",
    ),
    "SBF": GlossaryEntry(
        "SBF", "Sale of Balance Flats",
        "An HDB sales exercise offering unselected flats from earlier BTO "
        "launches and other returned units, generally with shorter waiting "
        "times than a new BTO.",
    ),
    "PSF": GlossaryEntry(
        "PSF", "Price Per Square Foot",
        "A flat's price divided by its floor area — a common way to compare "
        "value across units of different sizes.",
    ),
    "REMAINING LEASE": GlossaryEntry(
        "Remaining Lease", "Remaining Lease",
        "The years left on a flat's 99-year lease. It affects how much CPF "
        "can be used, loan eligibility, and resale value — shorter remaining "
        "leases generally face more financing restrictions.",
    ),
    "MEDIAN": GlossaryEntry(
        "Median", "Median",
        "The middle value when all transactions are sorted from lowest to "
        "highest — half the transactions were above it, half below. It is "
        "less skewed by one or two unusually high or low sales than a "
        "simple average.",
    ),
    "TYPICAL RANGE": GlossaryEntry(
        "Typical Range", "25th–75th Percentile Range",
        "The middle 50% of transactions fall within this range — a way to "
        "show normal variation without being skewed by rare outliers at "
        "either extreme.",
    ),
}

SOURCES_FOOTER = (
    "Sources: transaction data from data.gov.sg (Singapore's official open "
    "data portal). This is general market information, not financial, legal, "
    "or property advice. For authoritative rules on eligibility, procedures, "
    "and fees, please refer to HDB (hdb.gov.sg), CEA (cea.gov.sg), and MND "
    "(mnd.gov.sg)."
)


def explain(term: str) -> GlossaryEntry | None:
    return GLOSSARY.get(term.strip().upper())


def format_full_glossary() -> str:
    lines = ["*HDB & Property Glossary*", ""]
    for entry in GLOSSARY.values():
        lines.append(f"*{entry.term}* ({entry.expansion})")
        lines.append(entry.explanation)
        lines.append("")
    lines.append(SOURCES_FOOTER)
    return "\n".join(lines).strip()
