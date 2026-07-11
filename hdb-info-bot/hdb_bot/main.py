"""Entrypoint: builds the Application and runs it in polling or webhook mode.

RUN_MODE=polling is the simplest option (no public URL/port needed) — good
for the Oracle Cloud Always Free VM. RUN_MODE=webhook is for Cloud Run /
any host that gives you a public HTTPS URL and a $PORT to listen on.

Either way, a full dataset sync runs once (blocking) before the bot starts
serving, and then repeats in the background on `SYNC_INTERVAL_HOURS` — see
data_sync.py and local_store.py. The local SQLite cache is also eagerly
warmed right after each sync (startup and periodic alike) so a user's first
query is never the one paying the ingest cost.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from pathlib import Path

import httpx
from telegram.ext import Application, ContextTypes

from . import carparks, local_store
from .charts import warm_up as warm_up_charts
from .config import Config, load_config
from .conversation import build_conversation_handler, error_handler
from .data_sync import DataSyncer
from .datasets import LOCAL_STORE_DATASETS

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


async def _sync_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    syncer: DataSyncer = context.bot_data["data_syncer"]
    results = await syncer.sync_all()
    if any(r.changed for r in results):
        local_store.invalidate_cache()
        carparks.invalidate_cache()
        logger.info("Local dataset cache refreshed after sync")
        await asyncio.to_thread(
            local_store.warm_cache, LOCAL_STORE_DATASETS, data_dir=syncer.data_dir
        )
        logger.info("Local SQLite cache re-warmed after sync")


async def _post_shutdown(application: Application) -> None:
    client: httpx.AsyncClient | None = application.bot_data.get("http_client")
    if client is not None:
        await client.aclose()


async def _post_init(application: Application) -> None:
    config: Config = application.bot_data["config"]
    syncer: DataSyncer = application.bot_data["data_syncer"]

    # Shared across every Google Maps / Geocoding / carpark-availability call
    # for the app's whole lifetime, instead of each call opening its own
    # client — reuses one TCP+TLS connection per host instead of paying for
    # a fresh handshake on every single request.
    application.bot_data["http_client"] = httpx.AsyncClient(timeout=15.0)

    logger.info("Running initial dataset sync (this can take a minute the first time)...")
    results = await syncer.sync_all()
    local_store.invalidate_cache()
    carparks.invalidate_cache()
    for r in results:
        if r.error:
            logger.warning("Initial sync issue for %s: %s", r.label, r.error)
    logger.info("Initial dataset sync complete.")

    logger.info("Warming local SQLite cache (so the first user query isn't the one paying for it)...")
    await asyncio.to_thread(local_store.warm_cache, LOCAL_STORE_DATASETS, data_dir=syncer.data_dir)
    logger.info("Local SQLite cache warm.")

    await asyncio.to_thread(warm_up_charts)
    logger.info("Chart renderer warm.")

    interval = timedelta(hours=config.sync_interval_hours)
    application.job_queue.run_repeating(_sync_job, interval=interval, first=interval)


def main() -> None:
    config = load_config()

    application = (
        Application.builder()
        .token(config.telegram_bot_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    application.bot_data["config"] = config
    application.bot_data["data_syncer"] = DataSyncer(
        data_dir=Path(config.data_dir) if config.data_dir else None,
        api_key=config.data_gov_sg_api_key,
    )

    application.add_handler(build_conversation_handler())
    application.add_error_handler(error_handler)

    if config.run_mode == "webhook":
        logger.info("Starting in webhook mode on port %d", config.port)
        application.run_webhook(
            listen="0.0.0.0",
            port=config.port,
            webhook_url=config.webhook_url,
        )
    else:
        logger.info("Starting in polling mode")
        application.run_polling()


if __name__ == "__main__":
    main()
