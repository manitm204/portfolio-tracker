"""Application settings loaded from environment / .env (backend-only).

The FMP API key is read here and must never be returned by any API endpoint,
logged, or embedded in frontend bundles.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root = parent of backend/
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    fmp_api_key: str = ""
    database_url: str = f"sqlite:///{PROJECT_ROOT / 'data' / 'portfolio_tracker.db'}"
    app_timezone: str = "America/New_York"
    eod_refresh_time: str = "18:00"  # HH:MM local (app_timezone)

    # Risk methodology knobs (documented in /methodology)
    risk_free_rate_annual: float = 0.04
    min_obs_beta: int = 10
    min_obs_vol: int = 5
    min_obs_var: int = 20
    trading_days_per_year: int = 252

    fmp_base_url: str = "https://financialmodelingprep.com/stable"
    fmp_max_retries: int = 4
    fmp_timeout_seconds: float = 20.0

    @property
    def database_url_resolved(self) -> str:
        """Rewrite relative sqlite paths to be anchored at the project root."""
        url = self.database_url
        if url.startswith("sqlite:///./"):
            rel = url.removeprefix("sqlite:///./")
            return f"sqlite:///{PROJECT_ROOT / rel}"
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
