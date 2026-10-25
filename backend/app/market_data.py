"""Market-data provider selection.

Every caller gets its client from ``get_market_data_client()``; nothing else
imports a concrete provider. Clients expose the same five methods and return
FMP-shaped dicts (``date/open/high/low/close/volume``, ``adjOpen/adjClose``,
``date/dividend/paymentDate``, ``date/numerator/denominator``,
``symbol/sector``), so ingestion code is provider-agnostic.

The provider is chosen once, from settings (``MARKET_DATA_PROVIDER``):

* ``auto`` (default) — FMP when ``FMP_API_KEY`` is set, otherwise Yahoo.
* ``fmp`` / ``yahoo`` — force one.

There is deliberately no per-request fallback: if the chosen provider fails,
the error surfaces instead of silently mixing sources in the stored data.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Protocol

from .config import get_settings

log = logging.getLogger(__name__)

PROVIDERS = ("fmp", "yahoo")
_PLACEHOLDER_KEYS = {"", "replace_with_your_key"}


class MarketDataError(Exception):
    """Any provider failure (network, HTTP, empty/malformed payload)."""


class MarketDataClient(Protocol):
    name: str

    def historical_eod(self, symbol: str, start: dt.date, end: dt.date) -> list[dict[str, Any]]: ...
    def historical_eod_adjusted(self, symbol: str, start: dt.date, end: dt.date) -> list[dict[str, Any]]: ...
    def dividends(self, symbol: str) -> list[dict[str, Any]]: ...
    def splits(self, symbol: str) -> list[dict[str, Any]]: ...
    def index_constituents(self, index: str = "sp500") -> list[dict[str, Any]]: ...
    def close(self) -> None: ...
    def __enter__(self) -> "MarketDataClient": ...
    def __exit__(self, *exc: Any) -> None: ...


def active_provider() -> str:
    s = get_settings()
    choice = (s.market_data_provider or "auto").strip().lower()
    if choice == "auto":
        return "fmp" if s.fmp_api_key.strip() not in _PLACEHOLDER_KEYS else "yahoo"
    if choice not in PROVIDERS:
        raise MarketDataError(
            f"Unknown MARKET_DATA_PROVIDER {choice!r}; expected auto, fmp or yahoo"
        )
    return choice


def get_market_data_client() -> MarketDataClient:
    provider = active_provider()
    if provider == "fmp":
        from .fmp_client import FMPClient

        return FMPClient()
    from .yahoo_client import YahooClient

    return YahooClient()


def provider_name(client: Any) -> str:
    """Provider label for a client instance (test fakes may not set one)."""
    return getattr(client, "name", None) or "unknown"


def prefetch(client: Any, symbols: list[str], start: dt.date, end: dt.date) -> None:
    """Let providers that support batching warm their cache in one request."""
    fn = getattr(client, "prefetch", None)
    if fn is not None and symbols:
        fn(symbols, start, end)
