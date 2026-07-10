"""Entrypoint: builds the Application and runs it in polling or webhook mode.

RUN_MODE=polling is the simplest option (no public URL/port needed) — good
for the Oracle Cloud Always Free VM. RUN_MODE=webhook is for Cloud Run /
any host that gives you a public HTTPS URL and a $PORT to listen on.

Either way, a full dataset sync runs once (blocking) before the bot starts
serving, and then repeats in the background on `SYNC_INTERVAL_HOURS` — see
data_sync.py and local_store.py.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

from telegram.ext import Application, ContextTypes

from . import carparks, local_store
from .config import Config, load_config
from .conversation import build_conversation_handler, error_handler
from .data_sync import DataSyncer

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


async def _post_init(application: Application) -> None:
    config: Config = application.bot_data["config"]
    syncer: DataSyncer = application.bot_data["data_syncer"]

    logger.info("Running initial dataset sync (this can take a minute the first time)...")
    results = await syncer.sync_all()
    local_store.invalidate_cache()
    carparks.invalidate_cache()
    for r in results:
        if r.error:
            logger.warning("Initial sync issue for %s: %s", r.label, r.error)
    logger.info("Initial dataset sync complete.")

    interval = timedelta(hours=config.sync_interval_hours)
    application.job_queue.run_repeating(_sync_job, interval=interval, first=interval)


def main() -> None:
    config = load_config()

    application = (
        Application.builder().token(config.telegram_bot_token).post_init(_post_init).build()
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
