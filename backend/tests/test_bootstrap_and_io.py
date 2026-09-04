"""Acceptance tests: seed hydration, FDXF exclusion, $500 reconciliation, CSV io."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from app.bootstrap import hydrate_account, load_seed_book
from app.csv_io import export_transactions, import_transactions
from app.models import OfficialFill, Transaction, TransactionType
from app.services import AccountContext, holdings_payload, summary_payload

from .conftest import add_bars

D125 = dt.date(2026, 7, 24)
D5 = dt.date(2026, 7, 29)


class FakeFMP:
    """Deterministic FMP stand-in: every symbol opens at 100 and closes at 101."""

    def __init__(self, open_price: float = 100.0):
        self.open_price = open_price
        self.calls: list[str] = []

    def historical_eod(self, symbol, start, end):
        self.calls.append(symbol)
        out = []
        d = start
        while d <= end:
            if d.weekday() < 5:
                out.append(
                    {
                        "symbol": symbol,
                        "date": d.isoformat(),
                        "open": self.open_price,
                        "high": 102.0,
                        "low": 99.0,
                        "close": 101.0,
                        "volume": 1000,
                    }
                )
            d += dt.timedelta(days=1)
        return out

    def historical_eod_adjusted(self, symbol, start, end):
        return [
            {**bar, "adjOpen": bar["open"], "adjClose": bar["close"]}
            for bar in self.historical_eod(symbol, start, end)
        ]

    def dividends(self, symbol):
        return []

    def splits(self, symbol):
        return []

    def close(self):
        pass


@pytest.fixture()
def seeded(db):
    load_seed_book(db)
    return db


def test_seed_book_loads_all_targets(seeded):
    from app.models import ModelTarget

    db = seeded
    t125 = (
        db.execute(select(ModelTarget).where(ModelTarget.account_id == "PORTFOLIO_125"))
        .scalars()
        .all()
    )
    t5 = (
        db.execute(select(ModelTarget).where(ModelTarget.account_id == "PORTFOLIO_5"))
        .scalars()
        .all()
    )
    assert len(t125) == 125
    assert len(t5) == 5
    fdxf = [t for t in t125 if t.ticker == "FDXF"]
    assert len(fdxf) == 1 and fdxf[0].active is False and fdxf[0].target_dollars == 0


def test_five_stock_hydration_reconciles_to_500(seeded):
    db = seeded
    fake = FakeFMP(open_price=250.0)
    result = hydrate_account(db, "PORTFOLIO_5", client=fake)
    assert result.hydrated and result.fills == 5
    txns = (
        db.execute(
            select(Transaction).where(
                Transaction.account_id == "PORTFOLIO_5",
                Transaction.type == TransactionType.BUY,
            )
        )
        .scalars()
        .all()
    )
    total = sum(-t.cash_flow for t in txns)
    assert total == pytest.approx(500.0, abs=1e-9)
    for t in txns:
        assert t.shares == pytest.approx(100.0 / 250.0, rel=1e-9)  # full precision kept
        assert -t.cash_flow == pytest.approx(100.0, abs=1e-12)
    assert result.residual_cash == pytest.approx(0.0, abs=1e-9)


def test_125_hydration_two_decimal_shares_and_residual_cash(seeded):
    db = seeded
    fake = FakeFMP(open_price=97.0)
    result = hydrate_account(db, "PORTFOLIO_125", client=fake)
    assert result.hydrated and result.fills == 124  # FDXF excluded
    txns = (
        db.execute(
            select(Transaction).where(
                Transaction.account_id == "PORTFOLIO_125",
                Transaction.type == TransactionType.BUY,
            )
        )
        .scalars()
        .all()
    )
    assert len(txns) == 124
    assert all(t.ticker != "FDXF" for t in txns)
    for t in txns:
        assert round(t.shares, 2) == pytest.approx(t.shares)  # two-decimal quantities
        assert t.cash_flow == pytest.approx(-(t.shares * 97.0))
    deposit = db.execute(
        select(Transaction).where(
            Transaction.account_id == "PORTFOLIO_125",
            Transaction.type == TransactionType.DEPOSIT,
        )
    ).scalar_one()
    assert deposit.cash_flow == 5000.0
    assert result.residual_cash == pytest.approx(5000.0 - result.total_cost)
    assert db.execute(select(OfficialFill)).scalars().first() is not None


def test_hydration_is_idempotent(seeded):
    db = seeded
    fake = FakeFMP()
    r1 = hydrate_account(db, "PORTFOLIO_5", client=fake)
    n1 = len(db.execute(select(Transaction)).scalars().all())
    r2 = hydrate_account(db, "PORTFOLIO_5", client=fake)
    n2 = len(db.execute(select(Transaction)).scalars().all())
    assert r1.hydrated and r2.already_done
    assert n1 == n2


def test_hydration_all_or_nothing_on_missing_open(seeded):
    db = seeded

    class PartialFMP(FakeFMP):
        def historical_eod(self, symbol, start, end):
            if symbol == "IBKR":
                return []  # missing data for one symbol
            return super().historical_eod(symbol, start, end)

    result = hydrate_account(db, "PORTFOLIO_5", client=PartialFMP())
    assert not result.hydrated
    assert any("IBKR" in e for e in result.errors)
    assert (
        db.execute(select(Transaction)).scalars().first() is None
    )  # nothing committed


def test_fdxf_contributes_zero_to_all_statistics(seeded, spy_qqq):
    db = seeded
    hydrate_account(db, "PORTFOLIO_125", client=FakeFMP(open_price=100.0))
    # Price bars for every hydrated ticker over the fixture window
    from app.models import ModelTarget

    tickers = (
        db.execute(
            select(ModelTarget.ticker).where(
                ModelTarget.account_id == "PORTFOLIO_125", ModelTarget.active.is_(True)
            )
        )
        .scalars()
        .all()
    )
    for t in tickers:
        add_bars(
            db,
            t,
            {
                dt.date(2026, 7, 27): 102.0,
                dt.date(2026, 7, 28): 103.0,
                dt.date(2026, 7, 29): 104.0,
            },
        )
    db.commit()

    ctx = AccountContext(db, "PORTFOLIO_125")
    payload = holdings_payload(ctx)
    tickers_out = {h["ticker"] for h in payload["holdings"]}
    assert "FDXF" not in tickers_out
    assert any(r["ticker"] == "FDXF" for r in payload["inactive"])
    summary = summary_payload(ctx)
    assert summary["concentration"]["num_holdings"] == 124
    # weights are rounded to 6dp individually; allow that rounding to accumulate
    weights_sum = sum(h["weight"] for h in payload["holdings"])
    assert weights_sum == pytest.approx(1.0, abs=1e-4)


def test_csv_import_export_roundtrip_idempotent(db, spy_qqq):
    from .conftest import make_account

    make_account(db, "ACC")
    db.commit()
    csv_text = (
        "transaction_id,account_id,trade_date,ticker,transaction_type,shares,price,fees,cash_flow,source,notes\n"
        "t1,ACC,2026-07-24,,DEPOSIT,,,0,1000,TEST,funding\n"
        "t2,ACC,2026-07-24,AAA,BUY,10,50,0,,TEST,\n"
        "t3,ACC,2026-07-28,AAA,SELL,4,60,1,,TEST,\n"
    )
    r1 = import_transactions(db, csv_text)
    assert r1["committed"] and r1["created"] == 3
    r2 = import_transactions(db, csv_text)
    assert r2["created"] == 0 and r2["skipped"] == 3  # idempotent re-import

    txns = db.execute(select(Transaction)).scalars().all()
    assert len(txns) == 3
    buy_txn = next(t for t in txns if t.type == TransactionType.BUY)
    assert buy_txn.cash_flow == pytest.approx(-500.0)
    sell_txn = next(t for t in txns if t.type == TransactionType.SELL)
    assert sell_txn.cash_flow == pytest.approx(4 * 60 - 1)

    exported = export_transactions(db, ["ACC"])
    assert "t1" in exported and "BUY" in exported
    assert exported.count("\n") == 4  # header + 3 rows


def test_csv_import_rejects_bad_rows_atomically(db):
    from .conftest import make_account

    make_account(db, "ACC")
    db.commit()
    csv_text = (
        "transaction_id,account_id,trade_date,ticker,transaction_type,shares,price,fees,cash_flow,source,notes\n"
        "t1,ACC,2026-07-24,,DEPOSIT,,,0,1000,TEST,\n"
        "t2,ACC,2026-07-24,AAA,BUY,-5,50,0,,TEST,bad shares\n"
    )
    r = import_transactions(db, csv_text)
    assert not r["committed"] and r["errors"]
    assert db.execute(select(Transaction)).scalars().first() is None
