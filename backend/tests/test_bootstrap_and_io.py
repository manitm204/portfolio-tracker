"""Acceptance tests: seed hydration, sleeve capital reconciliation, CSV io."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from app.bootstrap import hydrate_account, load_seed_book
from app.csv_io import export_transactions, import_transactions
from app.models import Transaction, TransactionType


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


def test_seed_book_loads_all_sleeves(seeded):
    from app.models import Account, ModelTarget

    db = seeded
    sleeves = db.execute(select(Account).order_by(Account.sleeve_number)).scalars().all()
    assert [a.id for a in sleeves] == ["SLEEVE_1", "SLEEVE_2", "SLEEVE_3", "SLEEVE_4"]
    assert len({a.starting_cash for a in sleeves}) == 1  # equal money per sleeve
    assert sleeves[0].start_date == dt.date(2026, 10, 1)
    assert sleeves[1].start_date == dt.date(2026, 11, 2)
    assert sleeves[2].start_date is None and sleeves[3].start_date is None
    counts = [
        len(
            db.execute(select(ModelTarget).where(ModelTarget.account_id == a.id))
            .scalars()
            .all()
        )
        for a in sleeves
    ]
    assert counts == [6, 5, 0, 0]


def test_sleeve_hydration_reconciles_to_capital(seeded):
    from app.models import Account

    db = seeded
    fake = FakeFMP(open_price=250.0)
    capital = db.get(Account, "SLEEVE_2").starting_cash
    result = hydrate_account(db, "SLEEVE_2", client=fake)
    assert result.hydrated and result.fills == 5
    txns = (
        db.execute(
            select(Transaction).where(
                Transaction.account_id == "SLEEVE_2",
                Transaction.type == TransactionType.BUY,
            )
        )
        .scalars()
        .all()
    )
    total = sum(-t.cash_flow for t in txns)
    assert total == pytest.approx(capital, abs=1e-9)
    for t in txns:
        assert t.shares == pytest.approx(capital / 5 / 250.0, rel=1e-9)  # full precision kept
        assert t.trade_date == dt.date(2026, 11, 2)
    assert result.residual_cash == pytest.approx(0.0, abs=1e-9)


def test_reloading_seed_keeps_a_sleeve_funded_in_the_app(seeded):
    from app.models import Account

    db = seeded
    db.get(Account, "SLEEVE_3").start_date = dt.date(2026, 12, 1)
    db.commit()
    load_seed_book(db)
    assert db.get(Account, "SLEEVE_3").start_date == dt.date(2026, 12, 1)


def test_hydration_is_idempotent(seeded):
    db = seeded
    fake = FakeFMP()
    r1 = hydrate_account(db, "SLEEVE_1", client=fake)
    n1 = len(db.execute(select(Transaction)).scalars().all())
    r2 = hydrate_account(db, "SLEEVE_1", client=fake)
    n2 = len(db.execute(select(Transaction)).scalars().all())
    assert r1.hydrated and r2.already_done
    assert n1 == n2


def test_hydration_all_or_nothing_on_missing_open(seeded):
    db = seeded

    class PartialFMP(FakeFMP):
        def historical_eod(self, symbol, start, end):
            if symbol == "VLO":
                return []  # missing data for one symbol
            return super().historical_eod(symbol, start, end)

    result = hydrate_account(db, "SLEEVE_1", client=PartialFMP())
    assert not result.hydrated
    assert any("VLO" in e for e in result.errors)
    assert (
        db.execute(select(Transaction)).scalars().first() is None
    )  # nothing committed


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
