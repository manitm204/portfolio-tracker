"""Ingestion idempotency, corporate actions, and API integration tests."""

from __future__ import annotations


import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import datetime as dt

from app.ingestion import (
    TRAILING_LOOKBACK_CALENDAR_DAYS,
    earliest_needed_date,
    ny_today,
    refresh_market_data,
)
from app.models import PriceBar, Transaction, TransactionType

from .conftest import D0, D2, add_bars, buy, deposit, make_account
from .test_bootstrap_and_io import FakeFMP


def test_earliest_needed_date_covers_trailing_year_even_for_new_account(db):
    make_account(db, "ACC", start=ny_today() - dt.timedelta(days=5))
    db.commit()
    expected = ny_today() - dt.timedelta(days=TRAILING_LOOKBACK_CALENDAR_DAYS)
    assert earliest_needed_date(db) == expected


def test_earliest_needed_date_uses_account_start_when_older(db):
    old_start = ny_today() - dt.timedelta(days=TRAILING_LOOKBACK_CALENDAR_DAYS + 100)
    make_account(db, "ACC", start=old_start)
    db.commit()
    assert earliest_needed_date(db) == old_start


def test_refresh_is_idempotent(db):
    make_account(db, "ACC", start=D0)
    deposit(db, "ACC", D0, 1000.0)
    buy(db, "ACC", D0, "AAA", 10.0, 100.0)
    db.commit()

    fake = FakeFMP()
    r1 = refresh_market_data(db, client=fake)
    n1 = db.execute(select(PriceBar)).scalars().all()
    r2 = refresh_market_data(db, client=fake)
    n2 = db.execute(select(PriceBar)).scalars().all()
    assert r1.status == "success" and r2.status == "success"
    assert len(n1) == len(n2)  # no duplicated bars
    # AAA + benchmarks tracked
    tickers = {b.ticker for b in n2}
    assert {"AAA", "SPY", "QQQ"} <= tickers


def test_refresh_partial_failure_surfaces(db):
    make_account(db, "ACC", start=D0)
    deposit(db, "ACC", D0, 1000.0)
    buy(db, "ACC", D0, "BAD", 10.0, 100.0)
    db.commit()

    from app.fmp_client import FMPError

    class FlakyFMP(FakeFMP):
        def historical_eod(self, symbol, start, end):
            if symbol == "BAD":
                raise FMPError("boom")
            return super().historical_eod(symbol, start, end)

        def historical_eod_adjusted(self, symbol, start, end):
            if symbol == "BAD":
                raise FMPError("boom")
            return super().historical_eod_adjusted(symbol, start, end)

    report = refresh_market_data(db, client=FlakyFMP())
    assert report.status == "partial"
    assert any("BAD" in f for f in report.failures)
    from app.models import SymbolSyncState

    state = db.get(SymbolSyncState, "BAD")
    assert state.status == "error"


def test_dividend_auto_transaction_created_once(db):
    make_account(db, "ACC", start=D0)
    deposit(db, "ACC", D0, 1000.0)
    buy(db, "ACC", D0, "AAA", 10.0, 100.0)
    db.commit()

    class DivFMP(FakeFMP):
        def dividends(self, symbol):
            if symbol == "AAA":
                return [
                    {"date": "2026-07-28", "paymentDate": "2026-07-28", "dividend": 0.5}
                ]
            return []

    fake = DivFMP()
    refresh_market_data(db, client=fake)
    refresh_market_data(db, client=fake)  # run twice — must not duplicate
    divs = (
        db.execute(
            select(Transaction).where(Transaction.type == TransactionType.DIVIDEND)
        )
        .scalars()
        .all()
    )
    assert len(divs) == 1
    assert divs[0].cash_flow == pytest.approx(10 * 0.5)
    assert divs[0].shares == 10


def test_split_auto_transaction(db):
    make_account(db, "ACC", start=D0)
    deposit(db, "ACC", D0, 1000.0)
    buy(db, "ACC", D0, "AAA", 10.0, 100.0)
    db.commit()

    class SplitFMP(FakeFMP):
        def splits(self, symbol):
            if symbol == "AAA":
                return [{"date": "2026-07-28", "numerator": 2, "denominator": 1}]
            return []

    refresh_market_data(db, client=SplitFMP())
    splits = (
        db.execute(select(Transaction).where(Transaction.type == TransactionType.SPLIT))
        .scalars()
        .all()
    )
    assert len(splits) == 1 and splits[0].split_ratio == 2.0


# ---------------------------------------------------------------------------
@pytest.fixture()
def client(db, spy_qqq):
    from app.database import get_db
    from app.main import app

    make_account(db, "ACC", start=D0)
    deposit(db, "ACC", D0, 1000.0)
    buy(db, "ACC", D0, "AAA", 10.0, 50.0)
    add_bars(db, "AAA", {D0: 52.0, D2: 53.0})
    db.commit()

    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_api_accounts_and_summary(client):
    accounts = client.get("/api/accounts").json()
    assert any(a["id"] == "ACC" for a in accounts)
    summary = client.get("/api/accounts/ACC/summary").json()
    assert summary["current_value"] > 0
    assert summary["invested_capital"] == 1000.0
    assert "freshness" in summary


def test_api_unknown_account_404(client):
    assert client.get("/api/accounts/NOPE/summary").status_code == 404


def test_api_performance_holdings_risk_heatmap(client):
    perf = client.get("/api/accounts/ACC/performance").json()
    assert perf["value"]["dates"]
    assert "growth_of_100" in perf and "SPY" in perf["growth_of_100"]
    holdings = client.get("/api/accounts/ACC/holdings").json()
    assert holdings["holdings"][0]["ticker"] == "AAA"
    risk = client.get("/api/accounts/ACC/risk").json()
    assert risk["observations"] >= 1
    hm = client.get("/api/accounts/ACC/heatmap?period=1D").json()
    assert hm["tiles"] and hm["tiles"][0]["ticker"] == "AAA"
    dq = client.get("/api/data-quality").json()
    assert "issues" in dq and "refresh_runs" in dq


def test_api_transactions_export_and_invalid_date(client):
    txt = client.get("/api/accounts/ACC/transactions/export")
    assert txt.status_code == 200 and "BUY" in txt.text
    assert client.get("/api/accounts/ACC/performance?start=bogus").status_code == 422
