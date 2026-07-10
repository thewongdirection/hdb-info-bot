"""Environment-variable configuration loading/validation."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


class ConfigError(Exception):
    pass


@dataclass
class Config:
    telegram_bot_token: str
    data_gov_sg_api_key: str | None
    google_maps_api_key: str | None
    run_mode: str
    webhook_url: str | None
    port: int
    recent_months_window: int
    chart_months_window: int
    sync_interval_hours: float
    data_dir: str | None


def load_config() -> Config:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ConfigError("TELEGRAM_BOT_TOKEN is required (see .env.example)")

    run_mode = os.environ.get("RUN_MODE", "polling").strip().lower()
    if run_mode not in ("polling", "webhook"):
        raise ConfigError(f"RUN_MODE must be 'polling' or 'webhook', got {run_mode!r}")

    webhook_url = os.environ.get("WEBHOOK_URL", "").strip() or None
    if run_mode == "webhook" and not webhook_url:
        raise ConfigError("WEBHOOK_URL is required when RUN_MODE=webhook")

    return Config(
        telegram_bot_token=token,
        data_gov_sg_api_key=os.environ.get("DATA_GOV_SG_API_KEY", "").strip() or None,
        google_maps_api_key=os.environ.get("GOOGLE_MAPS_API_KEY", "").strip() or None,
        run_mode=run_mode,
        webhook_url=webhook_url,
        port=int(os.environ.get("PORT", "8080")),
        recent_months_window=int(os.environ.get("RECENT_MONTHS_WINDOW", "12")),
        chart_months_window=int(os.environ.get("CHART_MONTHS_WINDOW", "24")),
        sync_interval_hours=float(os.environ.get("SYNC_INTERVAL_HOURS", "24")),
        data_dir=os.environ.get("DATA_DIR", "").strip() or None,
    )
