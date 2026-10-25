"""Keyless Yahoo Finance client (via yfinance) + Wikipedia S&P 500 list.

Drop-in for ``FMPClient``: same methods, same FMP-shaped dicts.

* One Yahoo history call returns raw OHLCV, Adj Close, dividends and splits
  together, so each symbol's frame is cached for the client's lifetime and
  every method is served from it. ``prefetch`` warms the cache for many
  symbols in batched downloads (used by refresh and Monte Carlo backfill).
* Yahoo's "Close" is split-adjusted but not dividend-adjusted — the same
  convention as FMP's ``historical-price-eod/full``.
* Yahoo has no dividend payment dates; ``paymentDate`` is omitted and the
  ledger credits on the ex-date (see ingestion._sync_corporate_actions).
* Yahoo spells share classes with a dash (BRK-B); symbols are translated on
  the way out and results are keyed by the caller's spelling.
"""

from __future__ import annotations

import datetime as dt
import io
import logging
import math
import time
from typing import Any

import httpx
import pandas as pd

from .config import get_settings
from .market_data import MarketDataError

log = logging.getLogger(__name__)

WIKI_SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
# Wikimedia's User-Agent policy rejects generic/browser UAs (403); it wants a
# tool name, a contact URL, and the HTTP library.
WIKI_USER_AGENT = (
    f"portfolio-tracker/1.0 (https://github.com/manitm204/portfolio-tracker) "
    f"httpx/{httpx.__version__}"
)
_COLUMNS = {
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Adj Close": "adj_close",
    "Volume": "volume",
    "Dividends": "dividends",
    "Stock Splits": "splits",
}
_BATCH_SIZE = 100


def to_yahoo_symbol(symbol: str) -> str:
    return symbol.replace(".", "-").upper()


class YahooClient:
    name = "yahoo"

    def __init__(self) -> None:
        import yfinance  # noqa: F401 — fail fast if the dependency is missing

        s = get_settings()
        self._max_retries = s.yahoo_max_retries
        self._timeout = s.yahoo_timeout_seconds
        # symbol -> (covered_start, covered_end, normalized frame indexed by date)
        self._cache: dict[str, tuple[dt.date, dt.date, pd.DataFrame]] = {}

    def close(self) -> None:
        self._cache.clear()

    def __enter__(self) -> "YahooClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    def _retry(self, what: str, fn):
        last_err: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                return fn()
            except MarketDataError:
                raise  # already classified as permanent
            except Exception as err:  # yfinance raises a zoo of types
                last_err = err
                if attempt >= self._max_retries:
                    break
                sleep_s = min(2**attempt, 15)
                log.warning(
                    "Yahoo request %s failed (attempt %d/%d): %s — retrying in %.1fs",
                    what, attempt + 1, self._max_retries, err, sleep_s,
                )
                time.sleep(sleep_s)
        raise MarketDataError(f"Yahoo request failed for {what}: {last_err}")

    def prefetch(self, symbols: list[str], start: dt.date, end: dt.date) -> None:
        """Batch-download history for ``symbols`` into the cache. Best effort:
        symbols that come back empty are simply fetched individually later."""
        import yfinance as yf

        todo = [s for s in dict.fromkeys(symbols) if not self._covers(s, start, end)]
        for i in range(0, len(todo), _BATCH_SIZE):
            chunk = todo[i : i + _BATCH_SIZE]
            ysyms = [to_yahoo_symbol(s) for s in chunk]
            try:
                df = self._retry(
                    f"batch of {len(chunk)}",
                    lambda: yf.download(
                        ysyms,
                        start=start.isoformat(),
                        end=(end + dt.timedelta(days=1)).isoformat(),
                        auto_adjust=False,
                        actions=True,
                        group_by="ticker",
                        progress=False,
                        threads=True,
                        timeout=self._timeout,
                    ),
                )
            except MarketDataError as err:
                log.warning("Yahoo batch prefetch failed, falling back to per-symbol: %s", err)
                continue
            if df is None or df.empty or not isinstance(df.columns, pd.MultiIndex):
                continue
            available = set(df.columns.get_level_values(0))
            for sym, ysym in zip(chunk, ysyms):
                if ysym not in available:
                    continue
                frame = _normalize(df[ysym])
                if not frame.empty:
                    self._cache[sym] = (start, end, frame)

    def _covers(self, symbol: str, start: dt.date, end: dt.date) -> bool:
        hit = self._cache.get(symbol)
        return hit is not None and hit[0] <= start and hit[1] >= end

    def _history(self, symbol: str, start: dt.date, end: dt.date) -> pd.DataFrame:
        if not self._covers(symbol, start, end):
            import yfinance as yf

            ysym = to_yahoo_symbol(symbol)
            raw = self._retry(
                symbol,
                lambda: yf.Ticker(ysym).history(
                    start=start.isoformat(),
                    end=(end + dt.timedelta(days=1)).isoformat(),
                    auto_adjust=False,
                    actions=True,
                    timeout=self._timeout,
                ),
            )
            self._cache[symbol] = (start, end, _normalize(raw))
        frame = self._cache[symbol][2]
        return frame[(frame.index >= start) & (frame.index <= end)]

    # ------------------------------------------------------------------
    def historical_eod(self, symbol: str, start: dt.date, end: dt.date) -> list[dict[str, Any]]:
        """Raw (split-adjusted, not dividend-adjusted) OHLCV, ascending by date."""
        frame = self._history(symbol, start, end)
        return [
            {
                "date": d.isoformat(),
                "open": _num(r.open),
                "high": _num(r.high),
                "low": _num(r.low),
                "close": _num(r.close),
                "volume": _int(r.volume),
            }
            for d, r in frame.iterrows()
            if _num(r.close) is not None
        ]

    def historical_eod_adjusted(
        self, symbol: str, start: dt.date, end: dt.date
    ) -> list[dict[str, Any]]:
        """Dividend-adjusted bars. Yahoo has no adjusted open, so it is
        derived as open × adj_close / close (same as benchmarks.py does)."""
        frame = self._history(symbol, start, end)
        rows = []
        for d, r in frame.iterrows():
            adj_close = _num(r.adj_close)
            if adj_close is None:
                continue
            open_, close = _num(r.open), _num(r.close)
            adj_open = open_ * adj_close / close if open_ is not None and close else None
            rows.append({"date": d.isoformat(), "adjOpen": adj_open, "adjClose": adj_close})
        if not rows:
            # The adjusted window always spans many sessions, so an empty
            # answer means a bad symbol or a throttled request — not "no news".
            raise MarketDataError(f"Yahoo returned no price history for {symbol}")
        return rows

    def _actions(self, symbol: str, column: str) -> pd.Series:
        hit = self._cache.get(symbol)
        if hit is not None:
            ser = hit[2][column]
        else:
            import yfinance as yf

            ticker = yf.Ticker(to_yahoo_symbol(symbol))
            ser = self._retry(
                f"{symbol} {column}",
                lambda: ticker.dividends if column == "dividends" else ticker.splits,
            )
            if ser is None:
                return pd.Series(dtype=float)
            ser.index = pd.DatetimeIndex(ser.index).date
        return ser[ser.fillna(0) != 0]

    def dividends(self, symbol: str) -> list[dict[str, Any]]:
        return [
            {"date": d.isoformat(), "dividend": float(v)}
            for d, v in self._actions(symbol, "dividends").items()
        ]

    def splits(self, symbol: str) -> list[dict[str, Any]]:
        out = []
        for d, ratio in self._actions(symbol, "splits").items():
            ratio = float(ratio)
            if ratio <= 0:
                continue
            num, den = (ratio, 1.0) if ratio >= 1 else (1.0, round(1 / ratio, 6))
            out.append({"date": d.isoformat(), "numerator": num, "denominator": den})
        return out

    def index_constituents(self, index: str = "sp500") -> list[dict[str, Any]]:
        """S&P 500 members from Wikipedia. Sectors are already GICS names."""
        if index != "sp500":
            raise MarketDataError(f"Yahoo provider only supports the sp500 index, not {index}")

        def fetch() -> str:
            resp = httpx.get(
                WIKI_SP500_URL,
                headers={"User-Agent": WIKI_USER_AGENT},
                timeout=self._timeout,
                follow_redirects=True,
            )
            if 400 <= resp.status_code < 500 and resp.status_code != 429:
                raise MarketDataError(
                    f"HTTP {resp.status_code} from Wikipedia S&P 500 list"
                )
            resp.raise_for_status()
            return resp.text

        html = self._retry("S&P 500 constituents", fetch)
        try:
            table = pd.read_html(io.StringIO(html), attrs={"id": "constituents"})[0]
        except (ValueError, IndexError) as err:
            raise MarketDataError(f"Could not parse S&P 500 table: {err}") from err
        return [
            {"symbol": str(r["Symbol"]).strip(), "sector": str(r["GICS Sector"]).strip()}
            for _, r in table.iterrows()
            if str(r.get("Symbol", "")).strip()
        ]


# ---------------------------------------------------------------------------
def _normalize(df: pd.DataFrame | None) -> pd.DataFrame:
    """Yahoo frame -> columns open/high/low/close/adj_close/volume/dividends/
    splits, indexed by plain ``datetime.date``, ascending."""
    if df is None or df.empty:
        return pd.DataFrame(columns=list(_COLUMNS.values()))
    out = df.rename(columns=_COLUMNS)
    for col in _COLUMNS.values():
        if col not in out.columns:
            out[col] = 0.0 if col in ("dividends", "splits") else float("nan")
    out = out[list(_COLUMNS.values())].copy()
    out.index = pd.DatetimeIndex(out.index).date
    return out.sort_index()


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _int(v: Any) -> int | None:
    f = _num(v)
    return int(f) if f is not None else None
