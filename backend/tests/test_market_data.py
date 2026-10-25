"""Provider selection, Yahoo payload shaping, and provider-agnostic ingestion."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pandas as pd
import pytest
from sqlalchemy import select

from app import market_data
from app.ingestion import refresh_market_data
from app.market_data import MarketDataError, active_provider
from app.models import RefreshRun, Transaction, TransactionType
from app.yahoo_client import YahooClient, to_yahoo_symbol

from .conftest import D0, buy, deposit, make_account
from .test_bootstrap_and_io import FakeFMP


def _settings(monkeypatch, provider: str, key: str) -> None:
    fake = SimpleNamespace(market_data_provider=provider, fmp_api_key=key)
    monkeypatch.setattr(market_data, "get_settings", lambda: fake)


@pytest.mark.parametrize(
    "provider,key,expected",
    [
        ("auto", "real-key", "fmp"),
        ("auto", "", "yahoo"),
        ("auto", "replace_with_your_key", "yahoo"),
        ("AUTO", "  ", "yahoo"),
        ("yahoo", "real-key", "yahoo"),
        ("fmp", "", "fmp"),
    ],
)
def test_active_provider(monkeypatch, provider, key, expected):
    _settings(monkeypatch, provider, key)
    assert active_provider() == expected


def test_unknown_provider_rejected(monkeypatch):
    _settings(monkeypatch, "polygon", "")
    with pytest.raises(MarketDataError):
        active_provider()


def test_fmp_error_is_a_market_data_error():
    from app.fmp_client import FMPError

    assert issubclass(FMPError, MarketDataError)


def test_yahoo_symbol_translation():
    assert to_yahoo_symbol("BRK.B") == "BRK-B"
    assert to_yahoo_symbol("spy") == "SPY"


# ---------------------------------------------------------------------------
def _yahoo_with_frame(symbol: str, start: dt.date, end: dt.date) -> YahooClient:
    """YahooClient whose cache already holds a Yahoo-shaped frame (no network)."""
    idx = pd.DatetimeIndex(
        ["2026-07-27", "2026-07-28", "2026-07-29"], tz="America/New_York"
    )
    raw = pd.DataFrame(
        {
            "Open": [100.0, 50.0, 52.0],
            "High": [101.0, 51.0, 53.0],
            "Low": [99.0, 49.0, 51.0],
            "Close": [100.0, 50.0, float("nan")],
            "Adj Close": [98.0, 49.0, float("nan")],
            "Volume": [1000, 2000, 0],
            "Dividends": [0.0, 0.25, 0.0],
            "Stock Splits": [0.0, 2.0, 0.0],
        },
        index=idx,
    )
    from app.yahoo_client import _normalize

    client = YahooClient()
    client._cache[symbol] = (start, end, _normalize(raw))
    return client


def test_yahoo_payloads_match_fmp_shape():
    start, end = dt.date(2026, 7, 1), dt.date(2026, 7, 31)
    c = _yahoo_with_frame("AAA", start, end)

    raw = c.historical_eod("AAA", start, end)
    assert [r["date"] for r in raw] == ["2026-07-27", "2026-07-28"]  # NaN close dropped
    assert raw[0] == {
        "date": "2026-07-27", "open": 100.0, "high": 101.0, "low": 99.0,
        "close": 100.0, "volume": 1000,
    }

    adj = c.historical_eod_adjusted("AAA", start, end)
    assert adj[0]["adjClose"] == 98.0
    assert adj[0]["adjOpen"] == pytest.approx(100.0 * 98.0 / 100.0)

    assert c.dividends("AAA") == [{"date": "2026-07-28", "dividend": 0.25}]
    assert c.splits("AAA") == [
        {"date": "2026-07-28", "numerator": 2.0, "denominator": 1.0}
    ]


def test_yahoo_range_slicing_and_reverse_split():
    start, end = dt.date(2026, 7, 1), dt.date(2026, 7, 31)
    c = _yahoo_with_frame("AAA", start, end)
    one_day = c.historical_eod("AAA", dt.date(2026, 7, 28), dt.date(2026, 7, 28))
    assert [r["date"] for r in one_day] == ["2026-07-28"]

    frame = c._cache["AAA"][2]
    frame.loc[dt.date(2026, 7, 28), "splits"] = 0.1  # 1-for-10 reverse split
    assert c.splits("AAA")[0]["numerator"] == 1.0
    assert c.splits("AAA")[0]["denominator"] == pytest.approx(10.0)


def test_yahoo_empty_adjusted_history_is_an_error():
    start, end = dt.date(2026, 7, 1), dt.date(2026, 7, 31)
    c = YahooClient()
    from app.yahoo_client import _normalize

    c._cache["ZZZ"] = (start, end, _normalize(None))
    with pytest.raises(MarketDataError):
        c.historical_eod_adjusted("ZZZ", start, end)


# ---------------------------------------------------------------------------
def test_refresh_records_provider_and_labels_corporate_actions(db):
    make_account(db, "ACC", start=D0)
    deposit(db, "ACC", D0, 1000.0)
    buy(db, "ACC", D0, "AAA", 10.0, 100.0)
    db.commit()

    class YahooLikeFake(FakeFMP):
        name = "yahoo"

        def __init__(self):
            super().__init__()
            self.prefetched: list[str] = []

        def prefetch(self, symbols, start, end):
            self.prefetched = list(symbols)

        def dividends(self, symbol):
            return [{"date": "2026-07-28", "dividend": 0.5}] if symbol == "AAA" else []

    fake = YahooLikeFake()
    report = refresh_market_data(db, client=fake)
    assert "AAA" in fake.prefetched and "SPY" in fake.prefetched

    run = db.get(RefreshRun, report.run_id)
    assert run.provider == "yahoo"
    div = db.execute(
        select(Transaction).where(Transaction.type == TransactionType.DIVIDEND)
    ).scalar_one()
    assert div.source == "YAHOO_CORPORATE_ACTIONS"
    # No paymentDate from Yahoo -> credited on the ex-date.
    assert div.trade_date == dt.date(2026, 7, 28)

    # Same dividend seen later from a different provider is not duplicated.
    class FmpLikeFake(YahooLikeFake):
        name = "fmp"

    refresh_market_data(db, client=FmpLikeFake())
    assert (
        len(
            db.execute(
                select(Transaction).where(Transaction.type == TransactionType.DIVIDEND)
            ).all()
        )
        == 1
    )
