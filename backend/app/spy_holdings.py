"""SPY's published daily holdings, used for index-heatmap tile weights.

State Street's daily file is the fund's own weight list, so it needs no
per-symbol market-cap lookups and works with either market-data provider. It
publishes no sectors; those come from the cached S&P 500 constituent list.
"""

from __future__ import annotations

import io

import httpx
from openpyxl import load_workbook

from .market_data import MarketDataError

HOLDINGS_URL = (
    "https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/"
    "etfs/us/holdings-daily-us-en-spy.xlsx"
)
_USER_AGENT = "Mozilla/5.0 (compatible; portfolio-tracker/1.0)"


def parse_holdings(content: bytes) -> list[dict]:
    """Rows of ``{ticker, name, weight}``; ``weight`` is a fraction of the fund."""
    sheet = load_workbook(io.BytesIO(content), read_only=True, data_only=True).active
    rows = sheet.iter_rows(values_only=True)
    header = next((r for r in rows if r and r[0] == "Name" and "Ticker" in r), None)
    if header is None:
        raise MarketDataError("SPY holdings file has no header row")
    ticker_col, weight_col = header.index("Ticker"), header.index("Weight")
    out = []
    for row in rows:
        ticker, weight = row[ticker_col], row[weight_col]
        if not ticker or ticker == "-" or not isinstance(weight, (int, float)):
            continue
        out.append(
            {
                # Stored the way the constituent list spells share classes.
                "ticker": str(ticker).replace(".", "-").upper(),
                "name": str(row[0]).title(),
                "weight": float(weight) / 100.0,
            }
        )
    if len(out) < 400:
        raise MarketDataError(f"SPY holdings file has only {len(out)} rows")
    return out


def fetch_spy_holdings() -> list[dict]:
    try:
        response = httpx.get(
            HOLDINGS_URL,
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
            timeout=30.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as err:
        raise MarketDataError(f"SPY holdings download failed: {err}") from err
    return parse_holdings(response.content)
