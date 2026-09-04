"""Factor exposure, correlation matrix, and PCA diversification on the Risk payload."""

from __future__ import annotations

import datetime as dt

import pytest

from app.services import AccountContext, risk_payload

from .conftest import add_bars, buy, deposit, make_account

DAYS = [dt.date(2026, 7, 24) + dt.timedelta(days=i) for i in range(20)]
DAYS = [d for d in DAYS if d.weekday() < 5][:15]


def _walk(seed: float, n: int) -> list[float]:
    price = 100.0
    out = []
    for i in range(n):
        price *= 1 + 0.01 * ((i * seed) % 3 - 1)
        out.append(round(price, 4))
    return out


@pytest.fixture()
def market_data(db):
    spy = _walk(1.0, len(DAYS))
    aaa = spy  # AAA tracks SPY exactly -> beta/correlation should be ~1
    add_bars(db, "SPY", dict(zip(DAYS, spy)))
    add_bars(db, "QQQ", dict(zip(DAYS, [p * 0.8 for p in spy])))
    add_bars(db, "AAA", dict(zip(DAYS, aaa)))
    for etf, seed in {"MTUM": 1.0, "VLUE": 2.0, "QUAL": 1.0, "USMV": 3.0, "SIZE": 2.0}.items():
        add_bars(db, etf, dict(zip(DAYS, _walk(seed, len(DAYS)))))
    db.commit()


def test_factor_exposure_present_for_all_five_etfs(db, market_data):
    make_account(db)
    deposit(db, "ACC", DAYS[0], 1000.0)
    buy(db, "ACC", DAYS[0], "AAA", 10.0, 100.0)
    db.commit()

    ctx = AccountContext(db, "ACC")
    payload = risk_payload(ctx)

    tickers = {row["ticker"] for row in payload["factor_exposure"]}
    assert tickers == {"MTUM", "VLUE", "QUAL", "USMV", "SIZE"}
    labels = {row["ticker"]: row["label"] for row in payload["factor_exposure"]}
    assert labels["MTUM"] == "Momentum"
    # MTUM shares AAA's exact return path (same seed) -> beta and corr ~1.
    mtum = next(r for r in payload["factor_exposure"] if r["ticker"] == "MTUM")
    assert mtum["beta"] == pytest.approx(1.0, abs=1e-6)
    assert mtum["correlation"] == pytest.approx(1.0, abs=1e-6)


def test_correlation_matrix_and_diversification_for_multi_holding_book(db, market_data):
    make_account(db)
    deposit(db, "ACC", DAYS[0], 2000.0)
    buy(db, "ACC", DAYS[0], "AAA", 5.0, 100.0)
    add_bars(db, "BBB", dict(zip(DAYS, _walk(2.0, len(DAYS)))))
    buy(db, "ACC", DAYS[0], "BBB", 5.0, 100.0)
    db.commit()

    ctx = AccountContext(db, "ACC")
    payload = risk_payload(ctx)

    cm = payload["correlation_matrix"]
    assert cm is not None
    assert set(cm["tickers"]) == {"AAA", "BBB"}
    diversification = payload["diversification"]
    assert diversification is not None
    assert diversification["num_holdings"] == 2
    assert 1.0 <= diversification["effective_bets"] <= 2.0
