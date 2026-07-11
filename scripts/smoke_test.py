#!/usr/bin/env python3
"""Manual pre/post-deploy sanity check — runs a REAL dataset sync against
data.gov.sg, then reads back through the exact same local-cache code path
the bot uses.

Run this once locally before deploying, and again after deploying, so you
catch upstream schema drift or bad env vars before your users do. The first
run downloads all 7 registered CSVs — expect it to take a minute or two.

Usage:
    python scripts/smoke_test.py
    python scripts/smoke_test.py --town "Toa Payoh" --force-sync
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from hdb_bot import carparks, local_store  # noqa: E402
from hdb_bot.data_sync import DataSyncer  # noqa: E402
from hdb_bot.datasets import DATASETS_FOR_INTENT  # noqa: E402
from hdb_bot.localities import resolve  # noqa: E402
from hdb_bot.stats import summarize  # noqa: E402


async def main(town_text: str, force_sync: bool) -> None:
    print(f"1. Resolving locality input: {town_text!r}")
    match = resolve(town_text)
    print(f"   -> towns={match.towns} method={match.method} note={match.note}")

    print("\n2. Syncing datasets from data.gov.sg (real network calls)...")
    syncer = DataSyncer(api_key=os.environ.get("DATA_GOV_SG_API_KEY"))
    results = await syncer.sync_all(force=force_sync)
    for r in results:
        status = "ERROR" if r.error else ("downloaded" if r.changed else "already up to date")
        extra = f" - {r.error}" if r.error else ""
        print(f"   {r.label}: {status} ({r.row_count} rows){extra}")
    local_store.invalidate_cache()

    for intent in ("buy", "rent"):
        datasets = DATASETS_FOR_INTENT[intent]
        print(f"\n3. Reading local cache for intent={intent}, town={match.towns[0]}...")
        records = local_store.load_town_records(datasets, match.towns[0])
        print(f"   -> {len(records)} local records")
        if records:
            print(f"   sample record: {records[0]}")

        stats = summarize(
            records, price_field=datasets[0].price_field, month_field=datasets[0].month_field
        )
        for s in stats:
            print(
                f"   {s.flat_type}: count={s.count} median={s.median:.0f} "
                f"trend={s.trend_label} ({s.trend_pct})"
            )

    print(f"\n4. Reading local carpark cache for town={match.towns[0]}...")
    matched_carparks = carparks.get_carparks_for_towns([match.towns[0]])
    print(f"   -> {len(matched_carparks)} carparks near {match.towns[0]}")
    print("   Fetching live availability (real network call)...")
    availability = await carparks.fetch_availability(api_key=os.environ.get("DATA_GOV_SG_API_KEY"))
    print(f"   -> {len(availability)} carparks reporting live availability nationwide")
    if matched_carparks:
        enriched = carparks.join_availability(matched_carparks, availability)
        print(f"   sample: {enriched[0]}")

    print("\nAll good — smoke test complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--town", default="Bishan")
    parser.add_argument(
        "--force-sync", action="store_true", help="Re-download every dataset even if unchanged"
    )
    args = parser.parse_args()
    asyncio.run(main(args.town, args.force_sync))
