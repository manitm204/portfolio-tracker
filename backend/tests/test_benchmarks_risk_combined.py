"""Acceptance tests: benchmarks, beta, combined view, missing-price policy."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.analytics import risk
from app.analytics.data import ffill_with_coverage, trading_calendar
from app.analytics.performance import twr_total, xirr
from app.services import AccountContext, account_contributions

from .conftest import D0, D1, D2, D3, add_bars, buy, deposit, make_account


def test_benchmarks_receive_identical_external_flows(db, spy_qqq):
    make_account(db)
    deposit(db, "ACC", D0, 1000.0)
    buy(db, "ACC", D0, "AAA", 10.0, 50.0)
    deposit(db, "ACC", D2, 500.0)
    add_bars(db, "AAA", {D0: 50.0, D1: 50.0, D2: 50.0, D3: 50.0})
    db.commit()

    ctx = AccountContext(db, "ACC")
    for b in ("SPY", "QQQ"):
        sim = ctx.bench_sims[b]
        assert sim["flow"].sum() == pytest.approx(1500.0)
        assert sim.loc[pd.Timestamp(D0), "flow"] == pytest.approx(1000.0)
        assert sim.loc[pd.Timestamp(D2), "flow"] == pytest.approx(500.0)
    # SPY sim: 1000/498 units at D0 open + 500/503 at D2 open, valued at close.
    units = 1000 / 498.0 + 500 / 503.0
    assert ctx.bench_sims["SPY"]["value"].iloc[-1] == pytest.approx(units * 510.0)


def test_portfolio_beta_matches_direct_covariance(db, spy_qqq):
    make_account(db)
    deposit(db, "ACC", D0, 1000.0)
    buy(db, "ACC", D0, "AAA", 10.0, 50.0)
    add_bars(db, "AAA", {D0: 50.0, D1: 51.5, D2: 50.4, D3: 52.0})
    db.commit()

    ctx = AccountContext(db, "ACC")
    spy = ctx.bench_price_returns["SPY"]
    b = risk.beta(ctx.returns, spy, min_obs=2)
    df = pd.concat({"p": ctx.returns, "b": spy}, axis=1).dropna()
    expected = np.cov(df["p"], df["b"], ddof=1)[0, 1] / np.var(df["b"], ddof=1)
    assert b == pytest.approx(expected)


def test_combined_equals_sum_of_accounts_every_date(db, spy_qqq):
    make_account(db, "A1", start=D0, cash=1000.0)
    make_account(db, "A2", start=D2, cash=500.0)  # later inception
    deposit(db, "A1", D0, 1000.0)
    buy(db, "A1", D0, "AAA", 10.0, 50.0)
    deposit(db, "A2", D2, 500.0)
    buy(db, "A2", D2, "BBB", 5.0, 40.0)
    add_bars(db, "AAA", {D0: 50.0, D1: 52.0, D2: 51.0, D3: 54.0})
    add_bars(db, "BBB", {D0: 40.0, D1: 41.0, D2: 40.0, D3: 42.0})
    db.commit()

    combined = AccountContext(db, "combined")
    a1 = AccountContext(db, "A1")
    a2 = AccountContext(db, "A2")
    total = a1.mv.reindex(combined.mv.index).fillna(0) + a2.mv.reindex(
        combined.mv.index
    ).fillna(0)
    pd.testing.assert_series_equal(combined.mv, total, check_names=False)

    # Combined benchmark respects each account's inception date.
    sim = combined.bench_sims["SPY"]
    assert sim.loc[pd.Timestamp(D0), "flow"] == pytest.approx(1000.0)
    assert sim.loc[pd.Timestamp(D2), "flow"] == pytest.approx(500.0)

    contrib = account_contributions(db)
    assert {c["account"] for c in contrib} == {"A1", "A2"}
    assert sum(c["value"] for c in contrib) == pytest.approx(
        float(combined.mv.iloc[-1]), abs=0.01
    )


def test_missing_price_forward_fill_never_fabricates_return(db, spy_qqq):
    make_account(db)
    deposit(db, "ACC", D0, 1000.0)
    buy(db, "ACC", D0, "AAA", 10.0, 50.0)
    # AAA has no bar on D1 (halted). Forward-fill keeps D0 close; return 0, not fabricated.
    add_bars(db, "AAA", {D0: 50.0, D2: 52.0, D3: 52.0})
    db.commit()

    ctx = AccountContext(db, "ACC")
    cal = trading_calendar(db, D0, D3)
    assert len(cal) == 4
    filled = ctx.closes["AAA"]
    assert filled.loc[pd.Timestamp(D1)] == 50.0  # ffilled
    assert bool(ctx.missing["AAA"].loc[pd.Timestamp(D1)]) is True  # surfaced as gap
    assert ctx.returns.loc[pd.Timestamp(D1)] == pytest.approx(0.0)


def test_ffill_reports_leading_gaps(db):
    m = pd.DataFrame({"X": [np.nan, 1.0]}, index=pd.to_datetime([D0, D1]))
    cal = pd.DatetimeIndex(pd.to_datetime([D0, D1]))
    filled, missing = ffill_with_coverage(m, cal)
    assert bool(missing["X"].iloc[0]) is True
    assert np.isnan(filled["X"].iloc[0])  # leading gap stays NaN, never zero


def test_xirr_simple_known_value():
    import datetime as dt

    flows = [(dt.date(2026, 1, 1), 1000.0)]
    terminal = (dt.date(2027, 1, 1), 1100.0)
    r = xirr(flows, terminal)
    assert r == pytest.approx(0.10, abs=1e-4)


def test_twr_insensitive_to_flow_timing_vs_mwr(db, spy_qqq):
    """TWR reflects only market performance; XIRR reflects flow timing."""
    make_account(db)
    deposit(db, "ACC", D0, 1000.0)
    buy(db, "ACC", D0, "AAA", 20.0, 50.0)
    add_bars(db, "AAA", {D0: 50.0, D1: 55.0, D2: 55.0, D3: 55.0})
    deposit(db, "ACC", D2, 10_000.0)  # big late deposit after the gain
    db.commit()

    ctx = AccountContext(db, "ACC")
    assert twr_total(ctx.returns) == pytest.approx(0.10, abs=1e-9)
    x = xirr(ctx.ext_flows, (D3, float(ctx.mv.iloc[-1])))
    assert x is not None and x > 0
