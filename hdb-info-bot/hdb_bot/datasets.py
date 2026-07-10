"""Registry of every data.gov.sg dataset the bot uses.

This is the single source of truth for dataset IDs — both `data_sync.py`
(which downloads/refreshes local copies) and `local_store.py` (which serves
records to the conversation flow from those local copies) read from here.

All datasets below are from the "Resale Flat Prices" collection
(https://data.gov.sg/collections/189/view) plus the HDB rental dataset,
covering https://data.gov.sg/datasets?topics=housing&resultId=189 in full.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DatasetInfo:
    resource_id: str
    label: str
    group: str  # "resale" | "rental" | "carpark_info"
    # price_field/month_field are only meaningful for the resale/rental
    # groups that stats.py operates on; the carpark_info dataset has
    # neither, so both default to None.
    price_field: str | None = None
    month_field: str | None = None


# The resale market has been split across 5 successive datasets over the
# years (approval-date era, then registration-date era); every era shares
# `month`, `town`, `flat_type`, `resale_price` fields, which is all this
# bot needs, so they're combined at read time in local_store.py.
RESALE_DATASETS: list[DatasetInfo] = [
    DatasetInfo(
        resource_id="d_ebc5ab87086db484f88045b47411ebc5",
        label="Resale Flat Prices (Approval Date), 1990-1999",
        group="resale", price_field="resale_price", month_field="month",
    ),
    DatasetInfo(
        resource_id="d_43f493c6c50d54243cc1eab0df142d6a",
        label="Resale Flat Prices (Approval Date), 2000-Feb 2012",
        group="resale", price_field="resale_price", month_field="month",
    ),
    DatasetInfo(
        resource_id="d_2d5ff9ea31397b66239f245f57751537",
        label="Resale Flat Prices (Registration Date), Mar 2012-Dec 2014",
        group="resale", price_field="resale_price", month_field="month",
    ),
    DatasetInfo(
        resource_id="d_ea9ed51da2787afaf8e51f827c304208",
        label="Resale Flat Prices (Registration Date), Jan 2015-Dec 2016",
        group="resale", price_field="resale_price", month_field="month",
    ),
    DatasetInfo(
        resource_id="d_8b84c4ee58e3cfc0ece0d773c8ca6abc",
        label="Resale Flat Prices (Registration Date), Jan 2017 onwards",
        group="resale", price_field="resale_price", month_field="month",
    ),
]

RENTAL_DATASETS: list[DatasetInfo] = [
    DatasetInfo(
        resource_id="d_c9f57187485a850908655db0e8cfe651",
        label="Renting Out of Flats, from Jan 2021",
        group="rental", price_field="monthly_rent", month_field="rent_approval_date",
    ),
]

# Static carpark facility info (address, SVY21 coordinates, parking system,
# free/night parking flags). Rarely changes, so it's synced like everything
# else above — the live lots-available count is a separate real-time API
# that can't be cached this way (see carparks.py).
CARPARK_INFO_DATASET = DatasetInfo(
    resource_id="d_23f946fa557947f93a8043bbef41dd09",
    label="HDB Carpark Information",
    group="carpark_info",
)

ALL_DATASETS: list[DatasetInfo] = RESALE_DATASETS + RENTAL_DATASETS + [CARPARK_INFO_DATASET]

# buy/sell both look at the resale market from opposite sides of the same trade.
DATASETS_FOR_INTENT: dict[str, list[DatasetInfo]] = {
    "buy": RESALE_DATASETS,
    "sell": RESALE_DATASETS,
    "rent": RENTAL_DATASETS,
}
