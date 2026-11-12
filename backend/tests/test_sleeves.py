"""Acceptance tests: sleeve lifecycle, position excess, risk window, heatmaps."""

from __future__ import annotations

import datetime as dt
import io
import json

import pandas as pd
import pytest
from openpyxl import Workbook
from sqlalchemy import select

from app import services
from app.analytics.performance import price_period_return
from app.ingestion import (
    TRAILING_LOOKBACK_CALENDAR_DAYS,
    earliest_needed_date,
    refresh_index_snapshot,
    symbol_universe,
)
from app.models import (
    Account,
    IndexConstituent,
    ModelTarget,
    Transaction,
    TransactionType,
)
from app.services import AccountContext
from app.sleeves import SleeveError, populate_sleeve, record_trade
from app.spy_holdings import parse_holdings

from .conftest import D0, D1, D2, D3, add_bars, buy, deposit, make_account, sell


def _sleeve(db, account_id: str, number: int, start: dt.date | None, cash: float = 1000.0):
    acct = make_account(db, account_id, start=start, cash=cash)
    acct.sleeve_number = number
    return acct


def _target(db, account_id: str, ticker: str, sector: str) -> None:
    db.add(
        ModelTarget(
            account_id=account_id,
            ticker=ticker,
            sector=sector,
            target_weight_pct=100.0,
            target_dollars=500.0,
        )
    )


class FakeClient:
    name = "fake"

    def __init__(self, missing: str | None = None):
        self.missing = missing

    def historical_eod(self, symbol, start, end):
        if symbol == self.missing:
            return []
        return [{"date": start.isoformat(), "open": 50.0, "close": 51.0}]

    def historical_eod_adjusted(self, symbol, start, end):
        if symbol == self.missing:
            return []
        return [
            {"date": "2026-07-27", "adjClose": 100.0},
            {"date": "2026-07-28", "adjClose": 110.0},
        ]

    def close(self):
        pass


def test_archived_account_stays_out_of_the_portfolio(db, spy_qqq):
    old = make_account(db, "OLD", start=D0)
    old.archived = True
    deposit(db, "OLD", D0, 500.0)
    buy(db, "OLD", D0, "ZZZ", 10.0, 50.0)
    _sleeve(db, "S1", 1, D0)
    deposit(db, "S1", D0, 1000.0)
    buy(db, "S1", D0, "AAA", 20.0, 50.0)
    add_bars(db, "AAA", {D0: 50.0, D3: 60.0})
    add_bars(db, "ZZZ", {D0: 50.0, D3: 500.0})
    db.commit()

    combined = AccountContext(db, "combined")
    assert combined.account_ids == ["S1"]
    assert float(combined.mv.iloc[-1]) == pytest.approx(1200.0)
    assert "ZZZ" not in symbol_universe(db)
    assert [a["id"] for a in services.list_accounts(db)] == ["S1"]
    # Still readable directly: archiving hides, it doesn't delete.
    assert AccountContext(db, "OLD").ledger


def test_unfunded_sleeve_is_pending_and_does_not_disturb_the_portfolio(db, spy_qqq):
    _sleeve(db, "S1", 1, D0)
    pending = _sleeve(db, "S3", 3, None)
    pending.planned_start = "2026-12"
    deposit(db, "S1", D0, 1000.0)
    buy(db, "S1", D0, "AAA", 20.0, 50.0)
    add_bars(db, "AAA", {D0: 50.0, D3: 55.0})
    db.commit()

    payload = services.sleeves_payload(db)
    by_id = {s["id"]: s for s in payload["sleeves"]}
    assert by_id["S1"]["status"] == "active" and by_id["S1"]["tickers"] == ["AAA"]
    assert by_id["S3"]["status"] == "pending"
    assert by_id["S3"]["planned_start"] == "2026-12"
    assert by_id["S1"]["portfolio_weight"] == pytest.approx(1.0)
    assert AccountContext(db, "combined").inception == D0
    assert services.heatmap_payload(AccountContext(db, "S3"))["tiles"] == []


def test_staggered_sleeves_flow_into_matched_portfolio_benchmark(db, spy_qqq):
    _sleeve(db, "S1", 1, D0)
    _sleeve(db, "S2", 2, D2)
    deposit(db, "S1", D0, 1000.0)
    buy(db, "S1", D0, "AAA", 20.0, 50.0)
    deposit(db, "S2", D2, 1000.0)
    buy(db, "S2", D2, "BBB", 20.0, 50.0)
    add_bars(db, "AAA", {D0: 50.0, D1: 50.0, D2: 50.0, D3: 50.0})
    add_bars(db, "BBB", {D2: 50.0, D3: 50.0})
    db.commit()

    combined = AccountContext(db, "combined")
    # The second sleeve's funding is a flow, not a 100% gain.
    assert combined.returns.abs().max() == pytest.approx(0.0)
    flows = combined.bench_sims["SPY"]["flow"]
    assert flows[pd.Timestamp(D0)] == pytest.approx(1000.0)
    assert flows[pd.Timestamp(D2)] == pytest.approx(1000.0)


def test_position_excess_uses_identical_window_from_the_open(db, spy_qqq):
    _sleeve(db, "S1", 1, D0)
    deposit(db, "S1", D0, 1000.0)
    buy(db, "S1", D0, "AAA", 10.0, 50.0)
    sell(db, "S1", D2, "AAA", 10.0, 60.0)
    buy(db, "S1", D2, "BBB", 10.0, 50.0)
    db.add(
        Transaction(
            account_id="S1",
            trade_date=D3,
            ticker="BBB",
            type=TransactionType.DIVIDEND,
            cash_flow=5.0,
            source="TEST",
        )
    )
    _target(db, "S1", "AAA", "Energy")
    _target(db, "S1", "BBB", "Energy")
    add_bars(db, "AAA", {D0: 50.0, D2: 60.0}, opens={D0: 50.0})
    add_bars(db, "BBB", {D2: 50.0, D3: 55.0})
    add_bars(db, "XLE", {D0: 100.0, D2: 110.0, D3: 121.0}, opens={D0: 100.0, D2: 110.0})
    db.commit()

    payload = services.history_payload(db, "S1")
    closed = payload["closed_positions"][0]
    assert closed["ticker"] == "AAA" and closed["status"] == "closed"
    assert closed["total_return"] == pytest.approx(0.2)
    # SPY entered at the D0 open (498), exited at the D2 close (500).
    assert closed["spy_return"] == pytest.approx(500.0 / 498.0 - 1.0, abs=1e-6)
    assert closed["excess_spy"] == pytest.approx(0.2 - (500.0 / 498.0 - 1.0), abs=1e-6)
    assert closed["sector_etf"] == "XLE"
    assert closed["excess_sector"] == pytest.approx(0.1, abs=1e-6)
    assert closed["cagr"] is None  # 4 days: annualizing it would only be noise

    still_open = payload["open_positions"][0]
    assert still_open["ticker"] == "BBB" and still_open["close_date"] is None
    assert still_open["market_value"] == pytest.approx(550.0)
    # Dividends count: (550 + 5) / 500 - 1, against the benchmark's total return.
    assert still_open["total_return"] == pytest.approx(0.11)


def test_rebuying_and_same_ticker_in_two_sleeves_are_separate_episodes(db, spy_qqq):
    _sleeve(db, "S1", 1, D0)
    _sleeve(db, "S2", 2, D0)
    deposit(db, "S1", D0, 1000.0)
    deposit(db, "S2", D0, 1000.0)
    buy(db, "S1", D0, "AAA", 5.0, 50.0)
    sell(db, "S1", D1, "AAA", 5.0, 50.0)
    buy(db, "S1", D2, "AAA", 5.0, 50.0)
    buy(db, "S2", D0, "AAA", 5.0, 50.0)
    add_bars(db, "AAA", {D0: 50.0, D1: 50.0, D2: 50.0, D3: 50.0})
    db.commit()

    payload = services.history_payload(db, "combined")
    assert len(payload["closed_positions"]) == 1
    assert sorted(r["account_id"] for r in payload["open_positions"]) == ["S1", "S2"]


def test_stock_attribution_sums_to_its_total_return(db, spy_qqq):
    _sleeve(db, "S1", 1, D0)
    deposit(db, "S1", D0, 500.0)
    buy(db, "S1", D0, "AAA", 10.0, 50.0)
    _target(db, "S1", "AAA", "Energy")
    add_bars(db, "AAA", {D0: 52.0, D1: 54.0, D2: 56.0, D3: 60.0}, opens={D0: 50.0})
    add_bars(
        db, "XLE", {D0: 100.0, D1: 101.0, D2: 102.0, D3: 110.0}, opens={D0: 100.0}
    )
    db.commit()

    stock = services.stocks_payload(AccountContext(db, "S1"))["stocks"][0]
    a = stock["attribution"]
    assert stock["total_return"] == pytest.approx(0.2)
    assert a["market"] + a["sector"] + a["selection"] == pytest.approx(0.2, abs=1e-5)
    assert a["selection"] == pytest.approx(0.1, abs=1e-6)  # stock minus XLE
    curves = stock["curves"]
    assert curves["stock"]["values"][-1] == pytest.approx(0.2)
    assert curves["sector_etf"]["values"][-1] == pytest.approx(0.1)
    assert len(curves["SPY"]["dates"]) == 4


def _daily_bars(db, ticker: str, start: dt.date, n: int) -> list[dt.date]:
    days = list(pd.bdate_range(start, periods=n).date)
    add_bars(db, ticker, {d: 100.0 + i + (i % 3) for i, d in enumerate(days)})
    return days


def test_purchase_risk_window_ends_before_the_buy(db):
    start = dt.date(2026, 1, 1)
    days = _daily_bars(db, "SPY", start, 60)
    _daily_bars(db, "QQQ", start, 60)
    _daily_bars(db, "AAA", start, 60)
    _daily_bars(db, "BBB", start, 60)
    entry = days[40]
    _sleeve(db, "S1", 1, entry)
    deposit(db, "S1", entry, 1000.0)
    buy(db, "S1", entry, "AAA", 5.0, 100.0)
    buy(db, "S1", entry, "BBB", 5.0, 100.0)
    _target(db, "S1", "AAA", "Energy")
    _target(db, "S1", "BBB", "Financials")
    db.commit()

    ctx = AccountContext(db, "S1")
    before = services.risk_payload(ctx, "purchase")["trailing_window"]
    assert before["mode"] == "purchase"
    assert before["anchor_date"] == entry.isoformat()
    assert before["end"] < entry.isoformat()
    after = services.risk_payload(ctx, "trailing")
    assert after["trailing_window"]["mode"] == "trailing"
    assert after["trailing_window"]["end"] > entry.isoformat()
    assert after["historical"]["observations"] >= 50
    assert after["historical"]["beta_spy"] == pytest.approx(1.0, abs=0.01)


def test_earliest_needed_date_reaches_a_year_before_first_purchase(db):
    _sleeve(db, "S1", 1, dt.date(2020, 3, 2))
    db.commit()
    assert earliest_needed_date(db) == dt.date(2020, 3, 2) - dt.timedelta(
        days=TRAILING_LOOKBACK_CALENDAR_DAYS
    )


def test_period_return_is_none_rather_than_shorter_than_its_label():
    idx = pd.bdate_range("2026-06-01", periods=30)
    ser = pd.Series(range(100, 130), index=idx, dtype=float)
    end = idx[-1]
    assert price_period_return(ser, "1Y", end) is None
    assert price_period_return(ser, "3M", end) is None
    assert price_period_return(ser, "1D", end) == pytest.approx(129 / 128 - 1)
    assert price_period_return(ser, "1W", end) == pytest.approx(129 / 124 - 1)
    # Nothing before January in the series.
    assert price_period_return(ser, "YTD", end) is None
    long = pd.Series(1.0, index=pd.bdate_range("2025-06-02", "2026-07-10"))
    long.iloc[-1] = 2.0
    assert price_period_return(long, "1Y", long.index[-1]) == pytest.approx(1.0)
    assert price_period_return(long, "YTD", long.index[-1]) == pytest.approx(1.0)


def test_holdings_heatmap_reports_every_period_and_sleeve(db, spy_qqq):
    _sleeve(db, "S1", 1, D0)
    deposit(db, "S1", D0, 1000.0)
    buy(db, "S1", D0, "AAA", 10.0, 50.0)
    _target(db, "S1", "AAA", "Energy")
    add_bars(db, "AAA", {D0: 50.0, D1: 51.0, D2: 52.0, D3: 55.0})
    db.commit()

    payload = services.heatmap_payload(AccountContext(db, "combined"), "SI")
    tile = payload["tiles"][0]
    assert tile["sleeves"] == ["S1"]
    assert tile["return"] == tile["returns"]["SI"] == pytest.approx(0.1)
    assert tile["returns"]["1D"] == pytest.approx(55 / 52 - 1, abs=1e-6)
    assert tile["returns"]["1Y"] is None  # four days of history can't fill a year
    assert {"1D", "1W", "1M", "MTD", "3M", "YTD", "1Y", "SI"} == set(payload["periods"])


def _spy_xlsx(rows: list[tuple]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(("Fund Name:", "SPDR"))
    ws.append(())
    ws.append(("Name", "Ticker", "Identifier", "SEDOL", "Weight", "Sector"))
    for row in rows:
        ws.append(row)
    ws.append(("US DOLLAR", "-", "-", "-", 0.1, "-"))
    ws.append(("Past performance is no guarantee",))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parse_spy_holdings_normalizes_tickers_and_weights():
    rows = [(f"CO {i}", f"T{i}", "x", "y", 0.2, "-") for i in range(450)]
    rows.append(("BERKSHIRE HATHAWAY", "BRK.B", "x", "y", 1.5, "-"))
    parsed = parse_holdings(_spy_xlsx(rows))
    assert len(parsed) == 451  # the cash line and footnote are dropped
    brk = next(p for p in parsed if p["ticker"] == "BRK-B")
    assert brk["weight"] == pytest.approx(0.015)
    assert brk["name"] == "Berkshire Hathaway"


def test_index_snapshot_stores_weights_and_returns(db, monkeypatch):
    for ticker, sector in (("AAA", "Energy"), ("OUT", "Energy")):
        db.add(
            IndexConstituent(
                index_name="sp500",
                ticker=ticker,
                sector=sector,
                fetched_at=dt.datetime.now(dt.timezone.utc),
            )
        )
    db.commit()
    monkeypatch.setattr(
        "app.ingestion.fetch_spy_holdings",
        lambda: [
            {"ticker": "AAA", "name": "Aaa", "weight": 0.6},
            {"ticker": "NEW", "name": "New", "weight": 0.4},
        ],
    )
    result = refresh_index_snapshot(db, FakeClient())
    assert result["updated"] == 2 and result["weights_ok"]

    payload = services.index_heatmap_payload(db, "1D")
    tiles = {t["ticker"]: t for t in payload["tiles"]}
    assert set(tiles) == {"AAA", "NEW"}  # OUT left the fund
    assert tiles["AAA"]["return"] == pytest.approx(0.1)
    assert tiles["NEW"]["sector"] == "Unknown"
    assert payload["as_of"] == dt.date(2026, 7, 28)
    energy = next(s for s in payload["sectors"] if s["sector"] == "Energy")
    assert energy["etf_ticker"] == "XLE"
    stored = db.execute(
        select(IndexConstituent).where(IndexConstituent.ticker == "AAA")
    ).scalar_one()
    assert json.loads(stored.period_returns)["1Y"] is None


def _pending(db) -> None:
    _sleeve(db, "S3", 3, None, cash=500.0)
    for t in ("AAA", "BBB", "CCC", "DDD"):
        db.add(IndexConstituent(index_name="sp500", ticker=t, sector="Energy"))
    db.commit()


def test_populate_funds_an_empty_sleeve_equally(db):
    _pending(db)
    tickers = [(t, None) for t in ("AAA", "BBB", "CCC", "DDD")]
    assert populate_sleeve(db, FakeClient(), "S3", D0, tickers) == 4
    assert db.get(Account, "S3").start_date == D0
    buys = db.execute(
        select(Transaction).where(Transaction.type == TransactionType.BUY)
    ).scalars().all()
    assert len(buys) == 4
    assert all(t.cash_flow == pytest.approx(-125.0) and t.price == 50.0 for t in buys)
    with pytest.raises(SleeveError, match="already funded"):
        populate_sleeve(db, FakeClient(), "S3", D0, tickers)


@pytest.mark.parametrize(
    "tickers, message",
    [
        (["AAA", "BBB", "CCC"], "4-6"),
        (["AAA", "AAA", "BBB", "CCC"], "once"),
        (["AAA", "BBB", "CCC", "NOPE"], "choose its sector"),
    ],
)
def test_populate_rejects_bad_requests(db, tickers, message):
    _pending(db)
    with pytest.raises(SleeveError, match=message):
        populate_sleeve(db, FakeClient(), "S3", D0, [(t, None) for t in tickers])


def test_populate_keeps_nothing_when_an_open_is_missing(db):
    _pending(db)
    tickers = [(t, None) for t in ("AAA", "BBB", "CCC", "DDD")]
    with pytest.raises(SleeveError, match="DDD"):
        populate_sleeve(db, FakeClient(missing="DDD"), "S3", D0, tickers)
    db.rollback()
    assert db.get(Account, "S3").start_date is None
    assert db.execute(select(Transaction)).scalars().first() is None
    assert db.execute(select(ModelTarget)).scalars().first() is None


def _funded(db) -> None:
    _sleeve(db, "S1", 1, D0)
    deposit(db, "S1", D0, 1000.0)
    buy(db, "S1", D0, "AAA", 20.0, 50.0)
    _target(db, "S1", "AAA", "Energy")
    db.add(IndexConstituent(index_name="sp500", ticker="BBB", sector="Financials"))
    db.commit()


def test_selling_all_closes_the_position_and_keeps_the_proceeds_as_cash(db):
    _funded(db)
    txn = record_trade(db, FakeClient(), "S1", "SELL", "AAA", D2)
    assert txn.shares == pytest.approx(20.0) and txn.cash_flow == pytest.approx(1000.0)
    target = db.execute(select(ModelTarget)).scalar_one()
    assert target.active is False and target.deactivated_date == D2

    record_trade(db, FakeClient(), "S1", "BUY", "BBB", D3, dollars=1000.0)
    bought = db.execute(
        select(Transaction).where(Transaction.ticker == "BBB")
    ).scalar_one()
    assert bought.shares == pytest.approx(20.0)
    assert db.execute(
        select(ModelTarget.sector).where(ModelTarget.ticker == "BBB")
    ).scalar() == "Financials"


def test_trades_cannot_overdraw_or_oversell(db):
    _funded(db)
    with pytest.raises(SleeveError, match="cash"):
        record_trade(db, FakeClient(), "S1", "BUY", "BBB", D2, dollars=1.0)
    with pytest.raises(SleeveError, match="Can't sell"):
        record_trade(db, FakeClient(), "S1", "SELL", "AAA", D2, shares=21.0)
    with pytest.raises(SleeveError, match="doesn't hold"):
        record_trade(db, FakeClient(), "S1", "SELL", "BBB", D2)


def test_stale_cached_history_is_not_covered(db):
    from app.ingestion import _adjusted_covers

    add_bars(db, "AAA", {dt.date(2026, 1, 2): 10.0, dt.date(2026, 8, 26): 11.0})
    db.commit()
    assert _adjusted_covers(db, "AAA", dt.date(2026, 1, 2), dt.date(2026, 8, 28))
    # Data stops before the window ends: must be refetched, not treated as covered.
    assert not _adjusted_covers(db, "AAA", dt.date(2026, 1, 2), dt.date(2026, 11, 5))
    assert not _adjusted_covers(db, "AAA", dt.date(2025, 6, 1), dt.date(2026, 8, 28))
