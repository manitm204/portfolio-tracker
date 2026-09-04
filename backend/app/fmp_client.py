"""Thin FMP (Financial Modeling Prep) client.

* The API key is injected server-side from Settings and is never logged.
* Retries with exponential backoff on transient failures and 429s.
* All methods return plain Python structures; persistence happens elsewhere.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from typing import Any

import httpx

from .config import get_settings

log = logging.getLogger(__name__)

# httpx logs full request URLs at INFO, which would leak the API key into
# logs. Cap it at WARNING.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class FMPError(Exception):
    pass


class FMPClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        s = get_settings()
        self._api_key = api_key if api_key is not None else s.fmp_api_key
        self._base = (base_url or s.fmp_base_url).rstrip("/")
        self._max_retries = s.fmp_max_retries
        self._timeout = s.fmp_timeout_seconds
        if not self._api_key:
            raise FMPError("FMP_API_KEY is not configured")
        self._client = httpx.Client(timeout=self._timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "FMPClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    def _get(self, path: str, **params: Any) -> Any:
        params = {k: v for k, v in params.items() if v is not None}
        params["apikey"] = self._api_key
        url = f"{self._base}/{path.lstrip('/')}"
        last_err: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = self._client.get(url, params=params)
                if resp.status_code in _RETRYABLE_STATUS:
                    raise FMPError(f"HTTP {resp.status_code} from FMP ({path})")
                resp.raise_for_status()
                return resp.json()
            except (httpx.TransportError, FMPError, httpx.HTTPStatusError) as err:
                last_err = err
                if attempt >= self._max_retries:
                    break
                sleep_s = min(2**attempt, 15)
                log.warning(
                    "FMP request %s failed (attempt %d/%d): %s — retrying in %.1fs",
                    path,
                    attempt + 1,
                    self._max_retries,
                    _redact(str(err), self._api_key),
                    sleep_s,
                )
                time.sleep(sleep_s)
        raise FMPError(
            f"FMP request failed for {path}: {_redact(str(last_err), self._api_key)}"
        )

    # ------------------------------------------------------------------
    def historical_eod(
        self, symbol: str, start: dt.date, end: dt.date
    ) -> list[dict[str, Any]]:
        """Raw OHLCV bars, ascending by date."""
        data = self._get(
            "historical-price-eod/full",
            symbol=symbol,
            **{"from": start.isoformat(), "to": end.isoformat()},
        )
        rows = data if isinstance(data, list) else []
        return sorted(rows, key=lambda r: r.get("date", ""))

    def historical_eod_adjusted(
        self, symbol: str, start: dt.date, end: dt.date
    ) -> list[dict[str, Any]]:
        """Dividend-adjusted bars (adjOpen/adjClose), ascending by date."""
        data = self._get(
            "historical-price-eod/dividend-adjusted",
            symbol=symbol,
            **{"from": start.isoformat(), "to": end.isoformat()},
        )
        rows = data if isinstance(data, list) else []
        return sorted(rows, key=lambda r: r.get("date", ""))

    def dividends(self, symbol: str) -> list[dict[str, Any]]:
        data = self._get("dividends", symbol=symbol)
        return data if isinstance(data, list) else []

    def splits(self, symbol: str) -> list[dict[str, Any]]:
        data = self._get("splits", symbol=symbol)
        return data if isinstance(data, list) else []

    def index_constituents(self, index: str = "sp500") -> list[dict[str, Any]]:
        """Current membership list for an index (e.g. symbol, sector, name)."""
        data = self._get(f"{index}-constituent")
        return data if isinstance(data, list) else []

    def market_cap(self, symbol: str) -> float | None:
        """Latest market capitalization, or None if unavailable."""
        data = self._get("market-capitalization", symbol=symbol)
        if isinstance(data, list) and data:
            cap = data[0].get("marketCap")
            return float(cap) if cap is not None else None
        return None


def _redact(text: str, key: str) -> str:
    return text.replace(key, "***") if key else text
