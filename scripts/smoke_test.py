#!/usr/bin/env python3
"""Manual pre/post-deploy sanity check — hits the REAL data.gov.sg API
(and Google Static Maps, if a key is configured) and prints what comes back.

Run this once locally before deploying, and again after deploying, so you
catch upstream schema drift or bad env vars before your users do.

Usage:
    python scripts/smoke_test.py
    python scripts/smoke_test.py --town "Toa Payoh"
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

from hdb_bot.datagov_client import DataGovClient, RESALE_DATASET, RENTAL_DATASET  # noqa: E402
from hdb_bot.localities import resolve  # noqa: E402
from hdb_bot.maps import build_static_map_url, fetch_map_image  # noqa: E402
from hdb_bot.stats import summarize  # noqa: E402


async def main(town_text: str) -> None:
    print(f"1. Resolving locality input: {town_text!r}")
    match = resolve(town_text)
    print(f"   -> towns={match.towns} method={match.method} note={match.note}")

    client = DataGovClient(api_key=os.environ.get("DATA_GOV_SG_API_KEY"))

    for label, dataset in (("resale", RESALE_DATASET), ("rental", RENTAL_DATASET)):
        print(f"\n2. Fetching {label} records for {match.towns[0]}...")
        records = await client.fetch_town_records(dataset.resource_id, match.towns[0], max_rows=500)
        print(f"   -> got {len(records)} records")
        if records:
            print(f"   sample record: {records[0]}")

        stats = summarize(records, price_field=dataset.price_field, month_field=dataset.month_field)
        for s in stats:
            print(
                f"   {s.flat_type}: count={s.count} median={s.median:.0f} "
                f"trend={s.trend_label} ({s.trend_pct})"
            )

    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    print("\n3. Google Static Maps check...")
    if not api_key:
        print("   GOOGLE_MAPS_API_KEY not set, skipping (bot will run text-only).")
    else:
        url, legend = build_static_map_url(match.towns, api_key)
        print(f"   URL (key redacted): {url.split('&key=')[0]}&key=***")
        result = await fetch_map_image(match.towns, api_key)
        if result:
            print(f"   -> fetched {len(result.image_bytes)} bytes, legend={result.legend}")
        else:
            print("   -> fetch_map_image returned None (check the key/quota)")

    print("\nAll good — smoke test complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--town", default="Bishan")
    args = parser.parse_args()
    asyncio.run(main(args.town))
