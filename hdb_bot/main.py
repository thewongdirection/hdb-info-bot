"""Entrypoint: builds the Application and runs it in polling or webhook mode.

RUN_MODE=polling is the simplest option (no public URL/port needed) — good
for the Oracle Cloud Always Free VM. RUN_MODE=webhook is for Cloud Run /
any host that gives you a public HTTPS URL and a $PORT to listen on.
"""
from __future__ import annotations

import logging

from telegram.ext import Application

from .config import load_config
from .conversation import build_conversation_handler, error_handler
from .datagov_client import DataGovClient

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


def main() -> None:
    config = load_config()

    application = Application.builder().token(config.telegram_bot_token).build()
    application.bot_data["config"] = config
    application.bot_data["datagov_client"] = DataGovClient(
        api_key=config.data_gov_sg_api_key, cache_ttl_seconds=config.cache_ttl_seconds
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
