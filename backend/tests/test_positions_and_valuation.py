"""Acceptance tests: ledger reconstruction and valuation."""

from __future__ import annotations


import pandas as pd
import pytest

from app.analytics.data import trading_calendar
from app.analytics.positions import daily_positions, load_ledger
from app.models import Transaction, TransactionType
from app.services import AccountContext

from .conftest import D0, D1, D2, D3, add_bars, buy, deposit, make_account, sell


def _ctx(db, account_id="ACC"):
    return AccountContext(db, account_id)


def test_one_stock_value_is_shares_times_price_plus_cash(db, spy_qqq):
    make_account(db, cash=1000.0)
    deposit(db, "ACC", D0, 1000.0)
    buy(db, "ACC", D0, "AAA", 10.0, 50.0)  # $500 -> cash 500
    add_bars(db, "AAA", {D0: 52.0, D1: 53.0, D2: 51.0, D3: 55.0})
    db.commit()

    ctx = _ctx(db)
    assert ctx.mv.iloc[0] == pytest.approx(10 * 52.0 + 500.0)
    assert ctx.mv.iloc[-1] == pytest.approx(10 * 55.0 + 500.0)


def test_buy_sell_alter_shares_and_cash_on_correct_dates(db, spy_qqq):
    make_account(db)
    deposit(db, "ACC", D0, 1000.0)
    buy(db, "ACC", D0, "AAA", 10.0, 50.0)
    sell(db, "ACC", D2, "AAA", 4.0, 60.0)
    add_bars(db, "AAA", {D0: 50.0, D1: 55.0, D2: 60.0, D3: 60.0})
    db.commit()

    ledger = load_ledger(db, ["ACC"])
    cal = trading_calendar(db, D0, D3)
    shares, cash, _ = daily_positions(ledger, cal)
    assert shares.loc[pd.Timestamp(D0), "AAA"] == 10.0
    assert shares.loc[pd.Timestamp(D1), "AAA"] == 10.0
    assert shares.loc[pd.Timestamp(D2), "AAA"] == 6.0
    assert cash.loc[pd.Timestamp(D0)] == pytest.approx(500.0)
    assert cash.loc[pd.Timestamp(D2)] == pytest.approx(500.0 + 240.0)


def test_dividend_and_fee_affect_cash_and_returns(db, spy_qqq):
    make_account(db)
    deposit(db, "ACC", D0, 1000.0)
    buy(db, "ACC", D0, "AAA", 10.0, 50.0)
    add_bars(db, "AAA", {D0: 50.0, D1: 50.0, D2: 50.0, D3: 50.0})
    db.add(
        Transaction(
            account_id="ACC",
            trade_date=D1,
            ticker="AAA",
            type=TransactionType.DIVIDEND,
            shares=10,
            price=1.0,
            cash_flow=10.0,
            source="TEST",
        )
    )
    db.add(
        Transaction(
            account_id="ACC",
            trade_date=D2,
            type=TransactionType.FEE,
            cash_flow=-5.0,
            source="TEST",
        )
    )
    db.commit()

    ctx = _ctx(db)
    # Flat price: only the dividend (+10) and fee (−5) move value.
    assert ctx.mv.loc[pd.Timestamp(D0)] == pytest.approx(1000.0)
    assert ctx.mv.loc[pd.Timestamp(D1)] == pytest.approx(1010.0)
    assert ctx.mv.loc[pd.Timestamp(D2)] == pytest.approx(1005.0)
    r = ctx.returns
    assert r.loc[pd.Timestamp(D1)] == pytest.approx(0.01)  # dividend is return
    assert r.loc[pd.Timestamp(D2)] == pytest.approx(-5 / 1010)  # fee is negative return


def test_split_changes_shares_without_false_return(db, spy_qqq):
    make_account(db)
    deposit(db, "ACC", D0, 1000.0)
    buy(db, "ACC", D0, "AAA", 10.0, 100.0)
    # 2-for-1 split effective D2: price halves, shares double.
    add_bars(
        db,
        "AAA",
        {D0: 100.0, D1: 100.0, D2: 50.0, D3: 50.0},
        adj={D0: 50.0, D1: 50.0, D2: 50.0, D3: 50.0},
    )
    db.add(
        Transaction(
            account_id="ACC",
            trade_date=D2,
            ticker="AAA",
            type=TransactionType.SPLIT,
            split_ratio=2.0,
            source="TEST",
        )
    )
    db.commit()

    ctx = _ctx(db)
    assert ctx.shares.loc[pd.Timestamp(D1), "AAA"] == 10.0
    assert ctx.shares.loc[pd.Timestamp(D2), "AAA"] == 20.0
    # No economic return across the split: value stays 1000 every day.
    assert ctx.mv.loc[pd.Timestamp(D2)] == pytest.approx(1000.0)
    assert ctx.returns.loc[pd.Timestamp(D2)] == pytest.approx(0.0)


def test_symbol_change_moves_position(db, spy_qqq):
    make_account(db)
    deposit(db, "ACC", D0, 1000.0)
    buy(db, "ACC", D0, "OLD", 10.0, 50.0)
    add_bars(db, "OLD", {D0: 50.0, D1: 50.0})
    add_bars(db, "NEW", {D2: 51.0, D3: 52.0})
    db.add(
        Transaction(
            account_id="ACC",
            trade_date=D2,
            ticker="OLD",
            type=TransactionType.SYMBOL_CHANGE,
            new_ticker="NEW",
            source="TEST",
        )
    )
    db.commit()

    ctx = _ctx(db)
    assert "NEW" in ctx.shares.columns
    assert ctx.shares.loc[pd.Timestamp(D3), "NEW"] == 10.0
    assert ctx.shares.loc[pd.Timestamp(D3)].get("OLD", 0.0) == 0.0
    assert ctx.mv.loc[pd.Timestamp(D3)] == pytest.approx(10 * 52.0 + 500.0)


def test_same_day_external_flow_creates_no_false_twr(db, spy_qqq):
    make_account(db)
    deposit(db, "ACC", D0, 1000.0)
    buy(db, "ACC", D0, "AAA", 10.0, 50.0)
    add_bars(db, "AAA", {D0: 50.0, D1: 50.0, D2: 50.0, D3: 50.0})
    # Big deposit on D2, flat prices -> daily TWR must be exactly 0.
    deposit(db, "ACC", D2, 50_000.0)
    db.commit()

    ctx = _ctx(db)
    assert ctx.returns.loc[pd.Timestamp(D2)] == pytest.approx(0.0, abs=1e-12)
    from app.analytics.performance import twr_total

    assert twr_total(ctx.returns) == pytest.approx(0.0, abs=1e-12)
