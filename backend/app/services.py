"""Assembles analytics into API-shaped payloads.

``account_key`` is either a sleeve's account id or the pseudo-account
``combined``: the whole portfolio, which merges every live sleeve's ledger
(positions and cash sum; the combined benchmark receives each sleeve's external
flows on their own dates, so staggered sleeve starts are respected).
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from .analytics import allocation as alloc
from .analytics import benchmarks as bench
from .analytics import montecarlo as mc
from .analytics import performance as perf
from .analytics import risk
from .analytics.data import (
    close_matrix,
    ffill_with_coverage,
    load_price_frame,
    trading_calendar,
)
from .analytics import diversification as div
from .analytics.positions import daily_positions, external_flow_list, load_ledger
from .config import get_settings
from .market_data import get_market_data_client
from .ingestion import (
    FACTOR_ETFS,
    INDEX_PERIODS,
    SECTOR_ETFS,
    TRAILING_LOOKBACK_CALENDAR_DAYS,
)
from .models import (
    Account,
    IndexConstituent,
    ModelTarget,
    PriceBar,
    RefreshRun,
    SymbolSyncState,
    Transaction,
    TransactionType,
)

COMBINED = "combined"

ROLLING_WINDOWS = (30, 90, 252)

# Cross-sectional style stats (security beta, factor exposure, correlation
# matrix, PCA) use each held ticker's own trailing ~1-year price history —
# never bounded by the account's inception date or how long the position has
# actually been held. A stock owned for 5 days still gets a real beta/
# correlation estimate from its last 252 trading days of market data: the
# ingestion job keeps ``TRAILING_LOOKBACK_CALENDAR_DAYS`` of history cached
# for every tracked symbol regardless of account age (see
# ingestion.earliest_needed_date), so this is a pure read, never a live
# on-demand fetch — see ``_trailing_returns``.
TRAILING_TRADING_DAYS = 252

# Below this many calendar days a holding-period CAGR only amplifies noise
# (the position-level match for the min_obs_vol sessions used by risk.cagr).
MIN_CAGR_HOLD_DAYS = 7


class UnknownAccount(Exception):
    pass


class UnsupportedMonteCarlo(Exception):
    pass


def resolve_account_ids(db: Session, account_key: str) -> list[str]:
    rows = db.execute(select(Account.id, Account.archived)).all()
    if account_key == COMBINED:
        return [a for a, archived in rows if not archived]
    if any(a == account_key for a, _ in rows):
        return [account_key]
    raise UnknownAccount(account_key)


def _live_accounts(db: Session) -> list[Account]:
    accounts = db.execute(select(Account).where(Account.archived.is_(False))).scalars()
    return sorted(accounts, key=lambda a: (a.sleeve_number or 0, a.id))


def list_accounts(db: Session) -> list[dict]:
    accounts = _live_accounts(db)
    out = [
        {
            "id": a.id,
            "display_name": a.display_name,
            "sleeve_number": a.sleeve_number,
            "start_date": a.start_date.isoformat() if a.start_date else None,
            "planned_start": a.planned_start,
            "starting_cash": a.starting_cash,
            "benchmarks": [a.benchmark_1, a.benchmark_2],
        }
        for a in accounts
    ]
    starts = [a.start_date for a in accounts if a.start_date]
    if len(accounts) > 1 and starts:
        out.append(
            {
                "id": COMBINED,
                "display_name": "Portfolio",
                "sleeve_number": None,
                "start_date": min(starts).isoformat(),
                "planned_start": None,
                "starting_cash": sum(a.starting_cash for a in accounts if a.start_date),
                "benchmarks": ["SPY", "QQQ"],
            }
        )
    return out


# ---------------------------------------------------------------------------
# Core context: everything downstream endpoints need, computed once.
# ---------------------------------------------------------------------------
class AccountContext:
    def __init__(self, db: Session, account_key: str):
        self.db = db
        self.key = account_key
        self.account_ids = resolve_account_ids(db, account_key)
        accounts = [db.get(Account, a) for a in self.account_ids]
        self.today = dt.date.today()
        # An unfunded sleeve has no start date: its context is simply empty.
        self.inception: dt.date = min(
            (a.start_date for a in accounts if a.start_date), default=self.today
        )
        self.benchmarks = ["SPY", "QQQ"]
        self.factor_etfs = list(FACTOR_ETFS)
        self.sector_etfs = SECTOR_ETFS

        self.ledger = load_ledger(db, self.account_ids)
        self.calendar = trading_calendar(db, self.inception, self.today)

        tickers = sorted(
            {t.ticker for t in self.ledger if t.ticker}
            | {t.new_ticker for t in self.ledger if t.new_ticker}
        )
        self.tickers = tickers
        frame = load_price_frame(
            db,
            tickers + self.benchmarks + self.factor_etfs + list(self.sector_etfs.values()),
            self.inception,
            self.today,
        )
        self.price_frame = frame
        self.bench_frames = {
            b: frame[frame["ticker"] == b].copy() for b in self.benchmarks
        }
        self.factor_frames = {
            f: frame[frame["ticker"] == f].copy() for f in self.factor_etfs
        }
        sector_etf_adj = close_matrix(
            frame[frame["ticker"].isin(self.sector_etfs.values())], "adj_close"
        )

        raw_closes = close_matrix(frame[frame["ticker"].isin(tickers)], "close")
        adj_closes = close_matrix(frame[frame["ticker"].isin(tickers)], "adj_close")
        self.closes, self.missing = ffill_with_coverage(raw_closes, self.calendar)
        self.adj_closes, _ = ffill_with_coverage(adj_closes, self.calendar)
        self.sector_etf_closes, _ = ffill_with_coverage(sector_etf_adj, self.calendar)
        # adjusted daily returns per ticker (corporate-action safe)
        self.ticker_returns = (
            self.adj_closes.pct_change()
            if not self.adj_closes.empty
            else pd.DataFrame()
        )

        self.shares, self.cash, self.flows = daily_positions(self.ledger, self.calendar)
        self.mv, self.ticker_values = perf.market_value_series(
            self.shares, self.cash, self.closes
        )
        self.returns = perf.daily_twr_returns(self.mv, self.flows)
        self.ext_flows = external_flow_list(self.ledger)

        self.bench_sims = {
            b: bench.simulate_benchmark(
                self.ext_flows, self.bench_frames[b], self.calendar
            )
            for b in self.benchmarks
        }
        self.bench_returns = {
            b: bench.benchmark_daily_returns(sim) for b, sim in self.bench_sims.items()
        }
        self.bench_price_returns = {
            b: bench.benchmark_price_returns(self.bench_frames[b], self.calendar)
            for b in self.benchmarks
        }
        self.factor_price_returns = {
            f: bench.benchmark_price_returns(self.factor_frames[f], self.calendar)
            for f in self.factor_etfs
        }

    # ------------------------------------------------------------------
    def window(self, start: dt.date | None, end: dt.date | None) -> "WindowView":
        return WindowView(self, start, end)

    def sectors(self) -> dict[str, str]:
        rows = self.db.execute(
            select(ModelTarget.ticker, ModelTarget.sector).where(
                ModelTarget.account_id.in_(self.account_ids)
            )
        ).all()
        return {t: s for t, s in rows}

    def targets(self) -> list[ModelTarget]:
        return list(
            self.db.execute(
                select(ModelTarget).where(ModelTarget.account_id.in_(self.account_ids))
            ).scalars()
        )

    def freshness(self) -> dict:
        db = self.db
        last_run = (
            db.execute(select(RefreshRun).order_by(RefreshRun.started_at.desc()))
            .scalars()
            .first()
        )
        states = (
            db.execute(
                select(SymbolSyncState).where(
                    SymbolSyncState.ticker.in_(self.tickers + self.benchmarks)
                )
            )
            .scalars()
            .all()
        )
        total = len(self.tickers) + len(self.benchmarks)
        ok = sum(1 for s in states if s.status == "ok")
        errors = [
            {"ticker": s.ticker, "error": (s.error or "")[:200]}
            for s in states
            if s.status == "error"
        ]
        last_bar_date = (
            self.calendar[-1].date().isoformat() if len(self.calendar) else None
        )
        provisional = False
        if len(self.calendar):
            provisional = bool(
                db.execute(
                    select(PriceBar.id).where(
                        PriceBar.date == self.calendar[-1].date(),
                        PriceBar.provisional.is_(True),
                        PriceBar.ticker.in_(self.tickers),
                    )
                ).first()
            )
        return {
            "last_refresh_at": last_run.finished_at.isoformat()
            if last_run and last_run.finished_at
            else None,
            "last_refresh_status": last_run.status if last_run else None,
            "as_of_date": last_bar_date,
            "as_of_provisional": provisional,
            "symbols_tracked": total,
            "symbols_ok": ok,
            "symbol_errors": errors,
            "coverage_pct": round(100.0 * ok / total, 1) if total else None,
        }


class WindowView:
    """Analytics restricted to a [start, end] date window."""

    def __init__(self, ctx: AccountContext, start: dt.date | None, end: dt.date | None):
        self.ctx = ctx
        cal = ctx.calendar
        if start is not None:
            cal = cal[cal >= pd.Timestamp(start)]
        if end is not None:
            cal = cal[cal <= pd.Timestamp(end)]
        self.calendar = cal
        self.mv = ctx.mv.reindex(cal).dropna()
        self.returns = ctx.returns.reindex(cal).dropna()
        self.bench_returns = {
            b: r.reindex(cal).dropna() for b, r in ctx.bench_returns.items()
        }
        self.bench_values = {
            b: sim["value"].reindex(cal).dropna() for b, sim in ctx.bench_sims.items()
        }


# ---------------------------------------------------------------------------
def _iso(index: pd.Index) -> list[str]:
    return [ts.date().isoformat() for ts in index]


def _round_or_none(v: float | None, nd: int = 6) -> float | None:
    if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
        return None
    return round(float(v), nd)


def _series_payload(s: pd.Series, nd: int = 6) -> dict:
    s = s.dropna()
    return {"dates": _iso(s.index), "values": [round(float(v), nd) for v in s]}


def summary_payload(ctx: AccountContext) -> dict:
    mv = ctx.mv
    if mv.empty:
        return {"account": ctx.key, "empty": True, "freshness": ctx.freshness()}
    current_value = float(mv.iloc[-1])
    cash = float(ctx.cash.iloc[-1]) if not ctx.cash.empty else 0.0
    invested = float(sum(f for _, f in ctx.ext_flows))

    today_ret = float(ctx.returns.iloc[-1]) if not ctx.returns.empty else None
    prev_mv = float(mv.iloc[-2]) if len(mv) > 1 else None
    today_flow = float(ctx.flows.iloc[-1]) if not ctx.flows.empty else 0.0
    today_dollar = current_value - prev_mv - today_flow if prev_mv is not None else None

    twr = perf.twr_total(ctx.returns)
    x = (
        perf.xirr(ctx.ext_flows, (ctx.calendar[-1].date(), current_value))
        if len(ctx.calendar)
        else None
    )

    bench_stats = {}
    for b in ctx.benchmarks:
        br = ctx.bench_returns[b]
        btwr = perf.twr_total(br)
        bench_stats[b] = {
            "twr": _round_or_none(btwr),
            "excess": _round_or_none(twr - btwr)
            if twr is not None and btwr is not None
            else None,
            "value": _round_or_none(
                float(ctx.bench_sims[b]["value"].iloc[-1])
                if not ctx.bench_sims[b].empty
                else None,
                2,
            ),
        }

    last_values = (
        ctx.ticker_values.iloc[-1].replace(0.0, np.nan).dropna()
        if not ctx.ticker_values.empty
        else pd.Series(dtype=float)
    )
    weights = alloc.weights_from_values(last_values)
    conc = alloc.concentration(weights)

    spy_ret = ctx.bench_returns["SPY"]
    mdd, _ = perf.max_drawdown(ctx.returns)
    s = get_settings()
    return {
        "account": ctx.key,
        "inception": ctx.inception.isoformat(),
        "current_value": round(current_value, 2),
        "invested_capital": round(invested, 2),
        "cash": round(cash, 2),
        "positions_value": round(current_value - cash, 2),
        "today": {
            "dollar": _round_or_none(today_dollar, 2),
            "pct": _round_or_none(today_ret),
        },
        "total": {
            "dollar": round(current_value - invested, 2),
            "pct": _round_or_none(current_value / invested - 1.0)
            if invested > 0
            else None,
        },
        "twr": _round_or_none(twr),
        "xirr": _round_or_none(x),
        "benchmarks": bench_stats,
        "risk": {
            "beta": _round_or_none(risk.beta(ctx.returns, spy_ret)),
            "beta_min_obs": s.min_obs_beta,
            "cagr": _round_or_none(risk.cagr(ctx.returns)),
            "alpha": _round_or_none(risk.alpha(ctx.returns, spy_ret)),
            "volatility": _round_or_none(risk.annualized_volatility(ctx.returns)),
            "sharpe": _round_or_none(risk.sharpe(ctx.returns)),
            "sortino": _round_or_none(risk.sortino(ctx.returns)),
            "max_drawdown": _round_or_none(mdd),
            "observations": int(len(ctx.returns)),
        },
        "concentration": {
            "largest_position": conc["largest_position"],
            "top5": _round_or_none(conc["top5"]),
            "top10": _round_or_none(conc["top10"]),
            "top20": _round_or_none(conc["top20"]),
            "effective_holdings": _round_or_none(conc["effective_holdings"], 2),
            "num_holdings": conc["num_holdings"],
        },
        "freshness": ctx.freshness(),
    }


def performance_payload(
    ctx: AccountContext, start: dt.date | None, end: dt.date | None
) -> dict:
    w = ctx.window(start, end)
    out: dict[str, Any] = {
        "account": ctx.key,
        "inception": ctx.inception.isoformat(),
        "value": _series_payload(w.mv, 2),
        "daily_returns": _series_payload(w.returns),
    }
    cum = perf.link_returns(w.returns) - 1.0
    out["cumulative_returns"] = _series_payload(cum)
    out["growth_of_100"] = {
        "portfolio": _series_payload(perf.growth_of_100(w.returns), 3)
    }
    out["benchmark_values"] = {}
    for b in ctx.benchmarks:
        out["growth_of_100"][b] = _series_payload(
            perf.growth_of_100(w.bench_returns[b]), 3
        )
        out["benchmark_values"][b] = _series_payload(w.bench_values[b], 2)

    _, dd = perf.max_drawdown(w.returns)
    out["drawdown"] = _series_payload(dd)
    bench_dd = {}
    for b in ctx.benchmarks:
        _, bdd = perf.max_drawdown(w.bench_returns[b])
        bench_dd[b] = _series_payload(bdd)
    out["benchmark_drawdown"] = bench_dd

    rolling: dict[str, Any] = {}
    spy_pr = w.bench_returns.get("SPY", pd.Series(dtype=float))
    qqq_pr = w.bench_returns.get("QQQ", pd.Series(dtype=float))
    for win in ROLLING_WINDOWS:
        rolling[str(win)] = {
            "beta_spy": _series_payload(risk.rolling_beta(w.returns, spy_pr, win), 4),
            "volatility": _series_payload(risk.rolling_volatility(w.returns, win), 4),
            "corr_spy": _series_payload(
                risk.rolling_correlation(w.returns, spy_pr, win), 4
            ),
            "corr_qqq": _series_payload(
                risk.rolling_correlation(w.returns, qqq_pr, win), 4
            ),
        }
    out["rolling"] = rolling

    table = {
        "portfolio": {
            k: _round_or_none(v)
            for k, v in perf.period_returns_table(w.returns).items()
        }
    }
    for b in ctx.benchmarks:
        table[b] = {
            k: _round_or_none(v)
            for k, v in perf.period_returns_table(w.bench_returns[b]).items()
        }
    out["period_returns"] = table

    out["calendar_heatmap"] = _series_payload(w.returns)
    monthly = {}
    if not w.returns.empty:
        m = (1.0 + w.returns).groupby(
            [w.returns.index.year, w.returns.index.month]
        ).prod() - 1.0
        monthly = [
            {"year": int(y), "month": int(mo), "return": round(float(v), 6)}
            for (y, mo), v in m.items()
        ]
    out["monthly_heatmap"] = monthly
    return out


def holdings_payload(ctx: AccountContext) -> dict:
    targets = {t.ticker: t for t in ctx.targets()}
    sectors = ctx.sectors()
    rows: list[dict] = []
    if ctx.ticker_values.empty or ctx.mv.empty:
        return {"account": ctx.key, "holdings": []}

    last_shares = (
        ctx.shares.iloc[-1] if not ctx.shares.empty else pd.Series(dtype=float)
    )
    last_values = ctx.ticker_values.iloc[-1]
    active = last_values[last_shares.reindex(last_values.index).fillna(0.0) > 0]
    weights = alloc.weights_from_values(active)

    cost_basis = _cost_basis(ctx)
    sleeves = _sleeve_labels(ctx)
    s = get_settings()
    # Trailing ~1-year beta per holding (its own market history, independent
    # of account inception), matching the methodology used on the Risk page.
    trailing_universe = sorted(set(active.index) | {"SPY"})
    trailing_returns, _ = _trailing_returns(ctx.db, trailing_universe, ctx.today)
    trailing_spy = (
        trailing_returns["SPY"] if "SPY" in trailing_returns.columns else pd.Series(dtype=float)
    )
    sec_betas = (
        risk.security_betas(
            trailing_returns[[t for t in active.index if t in trailing_returns.columns]],
            trailing_spy,
            s.min_obs_beta,
        )
        if not trailing_returns.empty
        else {}
    )

    for ticker in active.index:
        shares = float(last_shares.get(ticker, 0.0))
        value = float(active[ticker])
        price = value / shares if shares else None
        cb = cost_basis.get(ticker, {})
        cost = cb.get("cost")
        day_ret = None
        if (
            ticker in ctx.ticker_returns.columns
            and not ctx.ticker_returns[ticker].dropna().empty
        ):
            day_ret = float(ctx.ticker_returns[ticker].dropna().iloc[-1])
        total_ret = (value / cost - 1.0) if cost else None
        b = sec_betas.get(ticker)
        weight = float(weights.get(ticker, 0.0))
        price_dates = (
            ctx.closes[ticker].dropna()
            if ticker in ctx.closes.columns
            else pd.Series(dtype=float)
        )
        missing_today = bool(
            ticker in ctx.missing.columns
            and len(ctx.missing)
            and bool(ctx.missing[ticker].iloc[-1])
        )
        rows.append(
            {
                "ticker": ticker,
                "sector": sectors.get(ticker, "Unknown"),
                "sleeves": sleeves.get(ticker, []),
                "shares": round(shares, 6),
                "cost_basis": _round_or_none(cost, 2),
                "avg_cost": _round_or_none(cb.get("avg_cost"), 4),
                "fill_price": _round_or_none(cb.get("fill_price"), 4),
                "price": _round_or_none(price, 4),
                "price_as_of": price_dates.index[-1].date().isoformat()
                if len(price_dates)
                else None,
                "price_stale": missing_today,
                "market_value": round(value, 2),
                "weight": round(weight, 6),
                "day_return": _round_or_none(day_ret),
                "day_dollar": _round_or_none(value * day_ret / (1 + day_ret), 2)
                if day_ret is not None and day_ret > -1
                else None,
                "unrealized_dollar": _round_or_none(value - cost, 2)
                if cost is not None
                else None,
                "unrealized_pct": _round_or_none(total_ret),
                "beta": _round_or_none(b, 3),
                "beta_contribution": _round_or_none(weight * b, 4)
                if b is not None
                else None,
                "target_weight": (targets[ticker].target_weight_pct / 100.0)
                if ticker in targets
                else None,
            }
        )
    rows.sort(key=lambda r: r["market_value"], reverse=True)
    return {"account": ctx.key, "holdings": rows}


def _sleeve_labels(ctx: AccountContext) -> dict[str, list[str]]:
    """Ticker → names of the sleeves currently holding it."""
    names = {a.id: a.display_name for a in _live_accounts(ctx.db)}
    held: dict[str, list[str]] = {}
    for ep in _walk_positions(ctx.ledger):
        if ep["close_date"] is None:
            held.setdefault(ep["ticker"], []).append(
                names.get(ep["account_id"], ep["account_id"])
            )
    return {t: sorted(v) for t, v in held.items()}


def _cost_basis(ctx: AccountContext) -> dict[str, dict]:
    """Average-cost basis per ticker from the ledger (documented method)."""
    out: dict[str, dict] = {}
    state: dict[str, dict] = {}
    for txn in ctx.ledger:
        if txn.ticker is None:
            continue
        st = state.setdefault(
            txn.ticker, {"shares": 0.0, "cost": 0.0, "fill_price": None}
        )
        if txn.type == TransactionType.BUY:
            st["cost"] += (
                -(txn.cash_flow)
                if txn.cash_flow is not None
                else (txn.shares or 0) * (txn.price or 0)
            )
            st["shares"] += txn.shares or 0.0
            if st["fill_price"] is None:
                st["fill_price"] = txn.price
        elif txn.type == TransactionType.SELL:
            if st["shares"] > 0 and (txn.shares or 0) > 0:
                avg = st["cost"] / st["shares"]
                st["cost"] -= avg * min(txn.shares, st["shares"])
                st["shares"] -= txn.shares
        elif txn.type == TransactionType.SPLIT and txn.split_ratio:
            st["shares"] *= txn.split_ratio
        elif txn.type == TransactionType.SYMBOL_CHANGE and txn.new_ticker:
            state[txn.new_ticker] = state.pop(txn.ticker)
    for ticker, st in state.items():
        if st["shares"] > 1e-12:
            out[ticker] = {
                "cost": st["cost"],
                "avg_cost": st["cost"] / st["shares"],
                "fill_price": st["fill_price"],
            }
    return out


def allocation_payload(ctx: AccountContext) -> dict:
    if ctx.ticker_values.empty or ctx.mv.empty:
        return {"account": ctx.key, "empty": True}
    sectors = ctx.sectors()
    last_shares = ctx.shares.iloc[-1]
    last_values = ctx.ticker_values.iloc[-1]
    active = last_values[last_shares.reindex(last_values.index).fillna(0.0) > 0]
    weights = alloc.weights_from_values(active)
    targets = {t.ticker: t.target_weight_pct for t in ctx.targets() if t.active}
    contrib = alloc.daily_contributions(ctx.ticker_values, ctx.ticker_returns, ctx.mv)
    daily_c = contrib.iloc[-1].dropna() if not contrib.empty else pd.Series(dtype=float)
    # Cumulative contribution since inception, restricted to tickers still
    # held today — a fully closed-out position (e.g. sold to zero) no longer
    # shows up here, even though it contributed on the days it was held.
    cum_c = (
        contrib[[t for t in active.index if t in contrib.columns]].sum()
        if not contrib.empty
        else pd.Series(dtype=float)
    )
    def sector_of(t: str) -> str:
        return sectors.get(t, "Unknown")

    def _contrib_rows(s: pd.Series) -> list[dict]:
        return [
            {"ticker": t, "sector": sector_of(t), "contribution": round(float(v), 6)}
            for t, v in s.sort_values(ascending=False).items()
            if abs(v) > 0
        ]

    def _sector_contrib(s: pd.Series) -> list[dict]:
        df = pd.DataFrame({"c": s})
        df["sector"] = [sector_of(t) for t in df.index]
        g = df.groupby("sector")["c"].sum().sort_values(ascending=False)
        return [{"sector": k, "contribution": round(float(v), 6)} for k, v in g.items()]

    return {
        "account": ctx.key,
        "sector_allocation": alloc.sector_allocation(active, sectors),
        "concentration_curve": alloc.concentration_curve(weights),
        "drift": alloc.drift_vs_target(weights, targets),
        "top_holdings": [
            {
                "ticker": t,
                "value": round(float(v), 2),
                "weight": round(float(weights[t]), 6),
            }
            for t, v in active.sort_values(ascending=False).head(20).items()
        ],
        "contribution": {
            "daily": _contrib_rows(daily_c),
            "cumulative": _contrib_rows(cum_c),
            "daily_by_sector": _sector_contrib(daily_c),
            "cumulative_by_sector": _sector_contrib(cum_c),
        },
        "cash": round(float(ctx.cash.iloc[-1]), 2) if not ctx.cash.empty else 0.0,
    }


def _risk_window_end(ctx: AccountContext, window: str) -> tuple[dt.date, dt.date | None]:
    """(last day of the cross-sectional window, purchase date it is anchored to).

    ``purchase`` ends the day before the most recent buy of a current holding,
    so every stat describes what was knowable when the position was opened and
    no look-ahead from the holding period leaks in. ``trailing`` ends today.
    """
    if window == "purchase":
        entries = [
            dt.date.fromisoformat(ep["open_date"])
            for ep in _walk_positions(ctx.ledger)
            if ep["close_date"] is None
        ]
        if entries:
            anchor = max(entries)
            return anchor - dt.timedelta(days=1), anchor
    return ctx.today, None


def _historical_profile(
    returns: pd.DataFrame, weights: pd.Series, tickers: list[str]
) -> dict | None:
    """Risk of today's weights replayed over the window — the sleeve as if it
    had been held throughout, so a days-old sleeve still has a real profile."""
    s = get_settings()
    cols = [t for t in tickers if t in returns.columns]
    hist = returns[cols].dropna(how="any") if cols else pd.DataFrame()
    if len(hist) < max(s.min_obs_beta, 2):
        return None
    w = weights.reindex(cols) / weights.reindex(cols).sum()
    port = hist @ w
    spy = returns["SPY"] if "SPY" in returns.columns else pd.Series(dtype=float)
    qqq = returns["QQQ"] if "QQQ" in returns.columns else pd.Series(dtype=float)
    mdd, _ = perf.max_drawdown(port)
    spy_mdd, _ = perf.max_drawdown(spy.dropna())
    var95, cvar95 = risk.var_cvar(port, 0.95)
    var99, cvar99 = risk.var_cvar(port, 0.99)
    vol = risk.annualized_volatility(port)
    weighted_vol = float((hist.std(ddof=1) * np.sqrt(s.trading_days_per_year) * w).sum())
    corr = hist.corr().to_numpy() if len(cols) > 1 else None
    pairs = corr[np.triu_indices_from(corr, k=1)] if corr is not None else None
    return {
        "observations": int(len(hist)),
        "total_return": _round_or_none(perf.twr_total(port)),
        "spy_total_return": _round_or_none(perf.twr_total(spy.dropna())),
        "beta_spy": _round_or_none(risk.beta(port, spy), 4),
        "beta_qqq": _round_or_none(risk.beta(port, qqq), 4),
        "correlation_spy": _round_or_none(risk.correlation(port, spy), 4),
        "correlation_qqq": _round_or_none(risk.correlation(port, qqq), 4),
        "volatility": _round_or_none(vol, 4),
        "spy_volatility": _round_or_none(risk.annualized_volatility(spy), 4),
        "sharpe": _round_or_none(risk.sharpe(port), 4),
        "sortino": _round_or_none(risk.sortino(port), 4),
        "max_drawdown": _round_or_none(mdd, 4),
        "spy_max_drawdown": _round_or_none(spy_mdd, 4),
        "var_95": _round_or_none(var95),
        "cvar_95": _round_or_none(cvar95),
        "var_99": _round_or_none(var99),
        "cvar_99": _round_or_none(cvar99),
        "average_correlation": _round_or_none(float(pairs.mean()), 4)
        if pairs is not None and len(pairs)
        else None,
        "diversification_ratio": _round_or_none(weighted_vol / vol, 3) if vol else None,
    }


def _sector_vs_index(
    db: Session, values: pd.Series, sectors: dict[str, str]
) -> list[dict]:
    """Current sector weights next to the S&P 500's, from the cached fund weights."""
    rows = db.execute(
        select(IndexConstituent.sector, IndexConstituent.weight).where(
            IndexConstituent.index_name == "sp500", IndexConstituent.weight.isnot(None)
        )
    ).all()
    index_weights: dict[str, float] = {}
    for sector, weight in rows:
        if sector and sector != "Unknown":
            index_weights[sector] = index_weights.get(sector, 0.0) + weight
    mine = {r["sector"]: r["weight"] for r in alloc.sector_allocation(values, sectors)}
    out = [
        {
            "sector": sector,
            "weight": round(mine.get(sector, 0.0), 6),
            "index_weight": round(index_weights[sector], 6)
            if sector in index_weights
            else None,
            "etf_ticker": SECTOR_ETFS.get(sector),
        }
        for sector in sorted(set(mine) | set(index_weights))
    ]
    out.sort(key=lambda r: -r["weight"])
    return out


def risk_payload(ctx: AccountContext, window: str = "purchase") -> dict:
    s = get_settings()
    spy_pr = ctx.bench_returns["SPY"]
    qqq_pr = ctx.bench_returns["QQQ"]
    var95, cvar95 = risk.var_cvar(ctx.returns, 0.95)
    var99, cvar99 = risk.var_cvar(ctx.returns, 0.99)
    mdd, _ = perf.max_drawdown(ctx.returns)

    last_shares = (
        ctx.shares.iloc[-1] if not ctx.shares.empty else pd.Series(dtype=float)
    )
    last_values = (
        ctx.ticker_values.iloc[-1][
            last_shares.reindex(ctx.ticker_values.columns).fillna(0) > 0
        ]
        if not ctx.ticker_values.empty
        else pd.Series(dtype=float)
    )
    weights = alloc.weights_from_values(last_values)
    held_tickers = [t for t in weights.index if weights[t] > 0]
    held_ranked = weights.reindex(held_tickers).sort_values(ascending=False)
    matrix_tickers = list(held_ranked.head(30).index)

    # Every cross-sectional style stat below (security beta, factor exposure,
    # correlation matrix, PCA, risk contribution) uses each held ticker's own
    # ~1-year price history, never the account's short inception-to-date window
    # — a stock you bought 5 days ago still gets a real beta/correlation from
    # its actual market history, not "insufficient history".
    window_end, anchor = _risk_window_end(ctx, window)
    trailing_universe = sorted(set(held_tickers) | {"SPY", "QQQ"} | set(FACTOR_ETFS))
    trailing_returns, trailing_obs = _trailing_returns(
        ctx.db, trailing_universe, window_end
    )
    trailing_spy = (
        trailing_returns["SPY"] if "SPY" in trailing_returns.columns else pd.Series(dtype=float)
    )

    sec_betas = (
        risk.security_betas(
            trailing_returns[[t for t in held_tickers if t in trailing_returns.columns]],
            trailing_spy,
            s.min_obs_beta,
        )
        if not trailing_returns.empty
        else {}
    )
    covered = {
        t: b for t, b in sec_betas.items() if b is not None and t in weights.index
    }
    beta_contrib = [
        {
            "ticker": t,
            "weight": round(float(weights[t]), 6),
            "beta": round(b, 3),
            "contribution": round(float(weights[t]) * b, 4),
        }
        for t, b in sorted(
            covered.items(), key=lambda kv: -abs(weights.get(kv[0], 0) * kv[1])
        )
    ]
    weighted_beta = (
        sum(r["contribution"] for r in beta_contrib) if beta_contrib else None
    )
    correlation_matrix = (
        div.correlation_matrix(trailing_returns, matrix_tickers, s.min_obs_beta)
        if not trailing_returns.empty
        else None
    )
    diversification = (
        div.pca_diversification(trailing_returns, matrix_tickers, s.min_obs_beta)
        if not trailing_returns.empty
        else None
    )

    def _weighted_factor_stat(fn) -> float | None:
        total_w = 0.0
        acc = 0.0
        for t in held_tickers:
            if t not in trailing_returns.columns:
                continue
            v = fn(trailing_returns[t].dropna())
            if v is None:
                continue
            w = float(weights[t])
            acc += w * v
            total_w += w
        return acc / total_w if total_w > 0 else None

    factor_exposure = [
        {
            "ticker": f,
            "label": FACTOR_ETFS[f],
            "beta": _round_or_none(
                _weighted_factor_stat(
                    lambda r, f=f: risk.beta(r, trailing_returns[f], s.min_obs_beta)
                    if f in trailing_returns.columns
                    else None
                ),
                4,
            ),
            "correlation": _round_or_none(
                _weighted_factor_stat(
                    lambda r, f=f: risk.correlation(r, trailing_returns[f], s.min_obs_beta)
                    if f in trailing_returns.columns
                    else None
                ),
                4,
            ),
        }
        for f in ctx.factor_etfs
    ]

    sectors = ctx.sectors()
    rc = (
        alloc.risk_contributions(trailing_returns, weights)
        if not trailing_returns.empty
        else []
    )
    rc_sector: dict[str, float] = {}
    for r in rc:
        rc_sector[sectors.get(r["ticker"], "Unknown")] = (
            rc_sector.get(sectors.get(r["ticker"], "Unknown"), 0.0) + r["contribution"]
        )

    def _comparison_row(returns: pd.Series) -> dict:
        mdd_r, _ = perf.max_drawdown(returns)
        return {
            "beta_spy": _round_or_none(risk.beta(returns, spy_pr), 4),
            "alpha_spy": _round_or_none(risk.alpha(returns, spy_pr), 4),
            "r_squared_spy": _round_or_none(risk.r_squared(returns, spy_pr), 4),
            "correlation_spy": _round_or_none(risk.correlation(returns, spy_pr), 4),
            "information_ratio_spy": _round_or_none(
                risk.information_ratio(returns, spy_pr), 4
            ),
            "cagr": _round_or_none(risk.cagr(returns), 4),
            "volatility": _round_or_none(risk.annualized_volatility(returns), 4),
            "sharpe": _round_or_none(risk.sharpe(returns), 4),
            "sortino": _round_or_none(risk.sortino(returns), 4),
            "calmar": _round_or_none(risk.calmar(returns), 4),
            "max_drawdown": _round_or_none(mdd_r, 4),
            "observations": int(returns.dropna().shape[0]),
        }

    comparison = {
        "portfolio": _comparison_row(ctx.returns),
        "spy": _comparison_row(spy_pr),
        "qqq": _comparison_row(qqq_pr),
    }

    return {
        "account": ctx.key,
        "observations": int(len(ctx.returns)),
        "min_obs": {
            "beta": s.min_obs_beta,
            "volatility": s.min_obs_vol,
            "var": s.min_obs_var,
        },
        "comparison": comparison,
        # Trailing ~1-year (not full since-inception history) portfolio beta/
        # correlation vs SPY and QQQ, using the portfolio's own daily TWR
        # returns over the last min(TRAILING_TRADING_DAYS, history) sessions.
        "beta_spy": _round_or_none(
            risk.beta(
                ctx.returns.tail(TRAILING_TRADING_DAYS),
                spy_pr.tail(TRAILING_TRADING_DAYS),
                s.min_obs_beta,
            ),
            4,
        ),
        "beta_qqq": _round_or_none(
            risk.beta(
                ctx.returns.tail(TRAILING_TRADING_DAYS),
                qqq_pr.tail(TRAILING_TRADING_DAYS),
                s.min_obs_beta,
            ),
            4,
        ),
        "correlation_spy": _round_or_none(
            risk.correlation(
                ctx.returns.tail(TRAILING_TRADING_DAYS),
                spy_pr.tail(TRAILING_TRADING_DAYS),
                s.min_obs_beta,
            ),
            4,
        ),
        "correlation_qqq": _round_or_none(
            risk.correlation(
                ctx.returns.tail(TRAILING_TRADING_DAYS),
                qqq_pr.tail(TRAILING_TRADING_DAYS),
                s.min_obs_beta,
            ),
            4,
        ),
        "volatility": _round_or_none(risk.annualized_volatility(ctx.returns), 4),
        "downside_deviation": _round_or_none(risk.downside_deviation(ctx.returns), 4),
        "sharpe": _round_or_none(risk.sharpe(ctx.returns), 4),
        "sortino": _round_or_none(risk.sortino(ctx.returns), 4),
        "max_drawdown": _round_or_none(mdd, 4),
        "var_95": _round_or_none(var95),
        "cvar_95": _round_or_none(cvar95),
        "var_99": _round_or_none(var99),
        "cvar_99": _round_or_none(cvar99),
        "risk_free_rate": s.risk_free_rate_annual,
        "weighted_security_beta": _round_or_none(weighted_beta, 4),
        "beta_contributions": beta_contrib,
        "risk_contributions": rc,
        "risk_contributions_by_sector": [
            {"sector": k, "contribution": round(v, 6)}
            for k, v in sorted(rc_sector.items(), key=lambda kv: -abs(kv[1]))
        ],
        "factor_exposure": factor_exposure,
        "correlation_matrix": correlation_matrix,
        "diversification": diversification,
        "historical": _historical_profile(trailing_returns, weights, held_tickers)
        if not trailing_returns.empty
        else None,
        "sector_vs_index": _sector_vs_index(ctx.db, last_values, sectors)
        if not last_values.empty
        else [],
        "trailing_window": {
            "mode": "purchase" if anchor else "trailing",
            "anchor_date": anchor.isoformat() if anchor else None,
            "start": trailing_returns.index[0].date().isoformat()
            if not trailing_returns.empty
            else None,
            "end": trailing_returns.index[-1].date().isoformat()
            if not trailing_returns.empty
            else None,
            "target_trading_days": TRAILING_TRADING_DAYS,
            "observations": trailing_obs,
        },
    }


HEATMAP_PERIODS = (*INDEX_PERIODS, "SI")


def _long_adj_closes(ctx: AccountContext, tickers: list[str]) -> pd.DataFrame:
    """Adjusted closes reaching back past inception: a stock's 1Y return isn't
    limited by how long it has been owned."""
    start = ctx.today - dt.timedelta(days=TRAILING_LOOKBACK_CALENDAR_DAYS)
    adj = close_matrix(load_price_frame(ctx.db, tickers, start, ctx.today), "adj_close")
    filled, _ = ffill_with_coverage(adj, trading_calendar(ctx.db, start, ctx.today))
    return filled


def _period_returns(
    closes: pd.DataFrame, ticker: str, end: pd.Timestamp | None
) -> dict[str, float | None]:
    if end is None or ticker not in closes.columns:
        return {p: None for p in INDEX_PERIODS}
    return {
        p: _round_or_none(perf.price_period_return(closes[ticker], p, end))
        for p in INDEX_PERIODS
    }


def heatmap_payload(ctx: AccountContext, period: str = "1D") -> dict:
    if period not in HEATMAP_PERIODS:
        period = "1D"
    empty = {
        "account": ctx.key,
        "period": period,
        "periods": list(HEATMAP_PERIODS),
        "tiles": [],
        "sectors": [],
    }
    if ctx.ticker_values.empty:
        return empty
    sectors = ctx.sectors()
    last_shares = ctx.shares.iloc[-1]
    last_values = ctx.ticker_values.iloc[-1]
    active = last_values[last_shares.reindex(last_values.index).fillna(0.0) > 0]
    if active.empty:
        return empty
    weights = alloc.weights_from_values(active)
    cost_basis = _cost_basis(ctx)
    sleeves = _sleeve_labels(ctx)

    closes = _long_adj_closes(
        ctx, [*active.index, *ctx.benchmarks, *ctx.sector_etfs.values()]
    )
    end = closes.index[-1] if not closes.empty else None
    tiles = []
    for ticker, value in active.items():
        returns: dict[str, float | None] = _period_returns(closes, ticker, end)
        cb = cost_basis.get(ticker)
        returns["SI"] = (
            _round_or_none(float(value) / cb["cost"] - 1.0)
            if cb and cb.get("cost")
            else None
        )
        tiles.append(
            {
                "ticker": ticker,
                "sector": sectors.get(ticker, "Unknown"),
                "sleeves": sleeves.get(ticker, []),
                "weight": round(float(weights[ticker]), 6),
                "value": round(float(value), 2),
                "return": returns[period],
                "returns": returns,
            }
        )
    tiles.sort(key=lambda t: (t["sector"], -t["weight"]))

    sector_perf = {}
    for t in tiles:
        if t["return"] is None:
            continue
        sp = sector_perf.setdefault(t["sector"], {"weight": 0.0, "wret": 0.0})
        sp["weight"] += t["weight"]
        sp["wret"] += t["weight"] * t["return"]
    sector_rows = []
    for k, v in sorted(sector_perf.items(), key=lambda kv: -kv[1]["weight"]):
        my_ret = round(v["wret"] / v["weight"], 6) if v["weight"] > 0 else None
        etf_ticker = ctx.sector_etfs.get(k)
        etf_ret = None
        if end is not None and etf_ticker:
            # "SI" must mean this account's inception, not the start of the
            # long history; sector_etf_closes begins there.
            source = ctx.sector_etf_closes if period == "SI" else closes
            if etf_ticker in source.columns:
                etf_ret = perf.price_period_return(source[etf_ticker], period, end)
        sector_rows.append(
            {
                "sector": k,
                "weight": round(v["weight"], 6),
                "return": my_ret,
                "etf_ticker": etf_ticker,
                "etf_return": _round_or_none(etf_ret),
                "excess_return": _round_or_none(my_ret - etf_ret)
                if my_ret is not None and etf_ret is not None
                else None,
            }
        )
    benchmarks = {
        b: {
            **_period_returns(closes, b, end),
            "SI": _round_or_none(perf.twr_total(ctx.bench_returns[b])),
        }
        for b in ctx.benchmarks
    }
    return {**empty, "tiles": tiles, "sectors": sector_rows, "benchmarks": benchmarks}


def index_heatmap_payload(db: Session, period: str = "1D") -> dict:
    """S&P 500 map from the stored snapshot, sized by SPY's published weights."""
    if period not in INDEX_PERIODS:
        period = "1D"
    rows = (
        db.execute(
            select(IndexConstituent).where(
                IndexConstituent.index_name == "sp500",
                IndexConstituent.period_returns.isnot(None),
                IndexConstituent.weight.isnot(None),
            )
        )
        .scalars()
        .all()
    )
    unpriced = db.execute(
        select(IndexConstituent.ticker).where(
            IndexConstituent.index_name == "sp500",
            IndexConstituent.period_returns.is_(None),
            IndexConstituent.weight.isnot(None),
        )
    ).scalars().all()
    tiles = []
    sector_acc: dict[str, dict[str, float]] = {}
    for r in rows:
        ret = json.loads(r.period_returns).get(period)
        sector = r.sector or "Unknown"
        tiles.append(
            {
                "ticker": r.ticker,
                "name": r.name,
                "sector": sector,
                "weight": round(r.weight, 6),
                "return": _round_or_none(ret),
            }
        )
        if ret is not None:
            acc = sector_acc.setdefault(sector, {"weight": 0.0, "wret": 0.0})
            acc["weight"] += r.weight
            acc["wret"] += r.weight * ret
    tiles.sort(key=lambda t: (t["sector"], -t["weight"]))
    return {
        "period": period,
        "periods": list(INDEX_PERIODS),
        "as_of": max((r.returns_as_of for r in rows), default=None),
        "unpriced": sorted(unpriced),
        "tiles": tiles,
        "sectors": [
            {
                "sector": k,
                "weight": round(v["weight"], 6),
                "return": round(v["wret"] / v["weight"], 6),
                "etf_ticker": SECTOR_ETFS.get(k),
            }
            for k, v in sorted(sector_acc.items(), key=lambda kv: -kv[1]["weight"])
            if v["weight"] > 0
        ],
    }


def transactions_payload(ctx: AccountContext) -> dict:
    rows = [
        {
            "id": t.id,
            "account_id": t.account_id,
            "trade_date": t.trade_date.isoformat(),
            "ticker": t.ticker,
            "type": t.type.value,
            "shares": t.shares,
            "price": t.price,
            "fees": t.fees,
            "cash_flow": t.cash_flow,
            "split_ratio": t.split_ratio,
            "new_ticker": t.new_ticker,
            "source": t.source,
            "notes": t.notes,
        }
        for t in sorted(ctx.ledger, key=lambda t: (t.trade_date, t.id), reverse=True)
    ]
    return {"account": ctx.key, "transactions": rows}


def monte_carlo_payload(
    ctx: AccountContext, sims: int = 50, seed: int | None = None
) -> dict:
    """Actual portfolio vs ``sims`` random same-size picks from the S&P 500,
    invested at the account's inception date using the same weighting
    philosophy as the real portfolio. Sleeve-level only: the whole portfolio
    has no single inception date to invest a random basket on."""
    if ctx.key == COMBINED:
        raise UnsupportedMonteCarlo("Monte Carlo comparison is per sleeve")
    targets = [t for t in ctx.targets() if t.active]
    actual = perf.growth_of_100(ctx.returns)
    if not targets or actual.empty:
        return {"account": ctx.key, "empty": True}

    from .ingestion import ensure_adjusted_history, ensure_sp500_constituents

    rng = np.random.default_rng(seed)
    db = ctx.db

    method = "equal_weight"
    n = len(targets)
    with get_market_data_client() as client:
        universe = sorted(set(ensure_sp500_constituents(db, client)) - {"SPY", "QQQ"})
        picks = mc.sample_universe(universe, n, sims, rng)
        needed = sorted({t for pick in picks for t in pick})
        ensure_adjusted_history(db, client, needed, ctx.inception, ctx.today)

    adj_filled = _adj_close_matrix(db, needed, ctx)
    curves = [mc.equal_weight_growth_of_100(adj_filled, pick) for pick in picks]
    sim_tickers = picks
    universe_size = len(universe)

    stats = mc.summarize(curves, ctx.calendar)
    sims_payload = [
        {"tickers": pick, **_series_payload(curve, 3)}
        for pick, curve in zip(sim_tickers, curves)
        if not curve.empty
    ]
    final_actual = float(actual.iloc[-1])
    final_sims = [s["values"][-1] for s in sims_payload if s["values"]]
    percentile = (
        float(np.mean([1.0 if fv <= final_actual else 0.0 for fv in final_sims]))
        if final_sims
        else None
    )

    return {
        "account": ctx.key,
        "method": method,
        "inception": ctx.inception.isoformat(),
        "n_holdings": len(targets),
        "universe_size": universe_size,
        "sims_requested": sims,
        "sims_run": len(sims_payload),
        "actual": {
            "tickers": sorted(t.ticker for t in targets),
            **_series_payload(actual, 3),
        },
        "simulations": sims_payload,
        "mean": _series_payload(stats["mean"], 3),
        "median": _series_payload(stats["median"], 3),
        "percentile_rank": _round_or_none(percentile, 4),
        "final_values": {
            "actual": _round_or_none(final_actual, 2),
            "sims": [round(v, 2) for v in final_sims],
        },
    }


def _adj_close_matrix(db: Session, tickers: list[str], ctx: AccountContext) -> pd.DataFrame:
    frame = load_price_frame(db, tickers, ctx.inception, ctx.today)
    adj = close_matrix(frame, "adj_close")
    filled, _ = ffill_with_coverage(adj, ctx.calendar)
    return filled


def _trailing_returns(
    db: Session, tickers: list[str], end: dt.date
) -> tuple[pd.DataFrame, int]:
    """Each ticker's own ~1-year (up to 252 trading day) daily return series
    ending at ``end``, independent of the account's inception date or how long
    a position has actually been held.

    Pure DB read — the ingestion job is responsible for keeping
    ``TRAILING_LOOKBACK_CALENDAR_DAYS`` of history cached for every tracked
    symbol (see ingestion.earliest_needed_date), so this never triggers a live
    fetch. Symbols missing that history simply reduce the observation count,
    same "insufficient history" degradation as every other risk stat.
    """
    if not tickers:
        return pd.DataFrame(), 0
    start = end - dt.timedelta(days=TRAILING_LOOKBACK_CALENDAR_DAYS)
    calendar = trading_calendar(db, start, end)[-TRAILING_TRADING_DAYS:]
    if len(calendar) == 0:
        return pd.DataFrame(), 0
    frame = load_price_frame(db, tickers, start, end)
    adj = close_matrix(frame, "adj_close")
    filled, _ = ffill_with_coverage(adj, calendar)
    returns = filled.pct_change().iloc[1:]
    return returns, int(len(calendar))


def _bench_bars(
    db: Session, tickers: list[str], start: dt.date, end: dt.date
) -> dict[str, pd.DataFrame]:
    """Per-ticker frame of ``adj_open``/``adj_close``, the same fallback as the
    benchmark simulator when a provider has no adjusted open."""
    frame = load_price_frame(db, sorted(set(tickers)), start, end)
    out: dict[str, pd.DataFrame] = {}
    for ticker, g in frame.groupby("ticker"):
        g = g.set_index("date").sort_index()
        factor = g["adj_close"] / g["close"]
        out[ticker] = pd.DataFrame(
            {
                "adj_open": g["adj_open"].astype(float).fillna(g["open"] * factor),
                "adj_close": g["adj_close"].astype(float),
            }
        ).dropna(subset=["adj_close"])
    return out


def _entry_price(bars: pd.DataFrame, open_date: dt.date) -> float | None:
    """Adjusted open on the purchase date, matching a fill at the open."""
    ts = pd.Timestamp(open_date)
    if ts in bars.index and pd.notna(bars.at[ts, "adj_open"]):
        return float(bars.at[ts, "adj_open"])
    price = bars["adj_close"].asof(ts)
    return None if pd.isna(price) else float(price)


def _window_return(
    bars: pd.DataFrame | None, open_date: dt.date, close_date: dt.date
) -> float | None:
    """Total return from the open of ``open_date`` to the close of ``close_date``."""
    if bars is None or bars.empty:
        return None
    entry = _entry_price(bars, open_date)
    exit_price = bars["adj_close"].asof(pd.Timestamp(close_date))
    if entry is None or entry <= 0 or pd.isna(exit_price):
        return None
    return float(exit_price) / entry - 1.0


def _annualize(total: float | None, hold_days: int) -> float | None:
    if total is None or hold_days < MIN_CAGR_HOLD_DAYS or total <= -1.0:
        return None
    return (1.0 + total) ** (365.0 / hold_days) - 1.0


def _walk_positions(ledger: list[Transaction]) -> list[dict]:
    """Every position episode in the ledger, open and closed.

    Walks each sleeve's ticker chronologically with the same average-cost
    method as ``_cost_basis``. A position returning to ~zero shares closes its
    episode; buying the ticker again starts a new one.
    """
    episodes: list[dict] = []
    state: dict[tuple[str, str], dict] = {}

    def fresh(account_id: str, ticker: str, open_date: dt.date) -> dict:
        return {
            "account_id": account_id,
            "ticker": ticker,
            "open_date": open_date.isoformat(),
            "close_date": None,
            "shares": 0.0,
            "total_cost": 0.0,
            "proceeds": 0.0,
            "dividends": 0.0,
        }

    for txn in ledger:
        if txn.ticker is None:
            continue
        key = (txn.account_id, txn.ticker)
        ep = state.get(key)
        if txn.type == TransactionType.BUY:
            if ep is None:
                ep = state[key] = fresh(txn.account_id, txn.ticker, txn.trade_date)
                episodes.append(ep)
            ep["total_cost"] += (
                -(txn.cash_flow)
                if txn.cash_flow is not None
                else (txn.shares or 0) * (txn.price or 0)
            )
            ep["shares"] += txn.shares or 0.0
        elif ep is None:
            continue
        elif txn.type == TransactionType.SELL and (txn.shares or 0) > 0:
            sold = min(txn.shares, ep["shares"])
            ep["proceeds"] += (
                txn.cash_flow if txn.cash_flow is not None else sold * (txn.price or 0)
            )
            ep["shares"] -= sold
            if ep["shares"] <= 1e-6:
                ep["shares"] = 0.0
                ep["close_date"] = txn.trade_date.isoformat()
                del state[key]
        elif txn.type == TransactionType.DIVIDEND:
            ep["dividends"] += txn.cash_flow or 0.0
        elif txn.type == TransactionType.SPLIT and txn.split_ratio:
            ep["shares"] *= txn.split_ratio
        elif txn.type == TransactionType.SYMBOL_CHANGE and txn.new_ticker:
            ep["ticker"] = txn.new_ticker
            state[(txn.account_id, txn.new_ticker)] = state.pop(key)
    return episodes


def _position_rows(
    db: Session,
    ledger: list[Transaction],
    sectors: dict[str, str],
    as_of: dt.date,
) -> tuple[list[dict], dict[str, pd.DataFrame]]:
    """Episodes with each one's return against SPY, QQQ and its sector ETF over
    the identical window, plus the price frames they were measured on.

    Position return includes dividends received, so it is compared like for
    like with the benchmarks' adjusted total returns. An open position's window
    ends at the latest close; a closed one's at the close on its sale date.
    """
    episodes = _walk_positions(ledger)
    if not episodes:
        return [], {}
    start = min(dt.date.fromisoformat(e["open_date"]) for e in episodes)
    tickers = ["SPY", "QQQ", *SECTOR_ETFS.values(), *(e["ticker"] for e in episodes)]
    bars = _bench_bars(db, tickers, start, as_of)
    raw_closes = close_matrix(
        load_price_frame(db, sorted({e["ticker"] for e in episodes}), start, as_of),
        "close",
    )
    names = {a.id: a.display_name for a in db.execute(select(Account)).scalars()}

    rows = []
    for ep in episodes:
        open_date = dt.date.fromisoformat(ep["open_date"])
        is_open = ep["close_date"] is None
        end_date = as_of if is_open else dt.date.fromisoformat(ep["close_date"])
        price = None
        if is_open and ep["ticker"] in raw_closes.columns:
            series = raw_closes[ep["ticker"]].dropna()
            price = float(series.iloc[-1]) if len(series) else None
        market_value = ep["shares"] * price if price is not None else None
        hold_days = (end_date - open_date).days
        cost = ep["total_cost"]
        ending = ep["proceeds"] + (market_value or 0.0)
        priced = cost > 0 and (not is_open or market_value is not None)
        gain_pct = ending / cost - 1.0 if priced else None
        total_return = (ending + ep["dividends"]) / cost - 1.0 if priced else None

        sector = sectors.get(ep["ticker"])
        sector_etf = SECTOR_ETFS.get(sector) if sector else None
        spy = _window_return(bars.get("SPY"), open_date, end_date)
        qqq = _window_return(bars.get("QQQ"), open_date, end_date)
        etf = _window_return(bars.get(sector_etf), open_date, end_date) if sector_etf else None
        cagr = _annualize(total_return, hold_days)

        def diff(a: float | None, b: float | None) -> float | None:
            return _round_or_none(a - b) if a is not None and b is not None else None

        spy_cagr = _annualize(spy, hold_days)
        qqq_cagr = _annualize(qqq, hold_days)
        etf_cagr = _annualize(etf, hold_days)
        rows.append(
            {
                "account_id": ep["account_id"],
                "sleeve": names.get(ep["account_id"], ep["account_id"]),
                "ticker": ep["ticker"],
                "status": "open" if is_open else "closed",
                "sector": sector,
                "sector_etf": sector_etf,
                "open_date": ep["open_date"],
                "close_date": ep["close_date"],
                "as_of": end_date.isoformat(),
                "hold_days": hold_days,
                "shares": round(ep["shares"], 6),
                "price": _round_or_none(price, 4),
                "market_value": _round_or_none(market_value, 2),
                "total_cost": round(cost, 2),
                "total_proceeds": round(ep["proceeds"], 2),
                "dividends": round(ep["dividends"], 2),
                "gain_dollar": _round_or_none(ending + ep["dividends"] - cost, 2)
                if priced
                else None,
                "gain_pct": _round_or_none(gain_pct),
                "total_return": _round_or_none(total_return),
                "spy_return": _round_or_none(spy),
                "qqq_return": _round_or_none(qqq),
                "sector_etf_return": _round_or_none(etf),
                "excess_spy": diff(total_return, spy),
                "excess_qqq": diff(total_return, qqq),
                "excess_sector": diff(total_return, etf),
                "cagr": _round_or_none(cagr),
                "spy_cagr": _round_or_none(spy_cagr),
                "qqq_cagr": _round_or_none(qqq_cagr),
                "sector_etf_cagr": _round_or_none(etf_cagr),
                "cagr_excess_spy": diff(cagr, spy_cagr),
                "cagr_excess_qqq": diff(cagr, qqq_cagr),
                "cagr_excess_sector": diff(cagr, etf_cagr),
            }
        )
    return rows, bars


def history_payload(db: Session, account_key: str) -> dict:
    from .ingestion import history_events

    account_ids = resolve_account_ids(db, account_key)
    ledger = load_ledger(db, account_ids)
    sectors = {
        t: s
        for t, s in db.execute(
            select(ModelTarget.ticker, ModelTarget.sector).where(
                ModelTarget.account_id.in_(account_ids)
            )
        ).all()
    }
    rows, _ = _position_rows(db, ledger, sectors, dt.date.today())
    return {
        "account": account_key,
        "events": history_events(db, account_ids),
        "open_positions": sorted(
            (r for r in rows if r["status"] == "open"),
            key=lambda r: r["total_return"] if r["total_return"] is not None else -9.0,
            reverse=True,
        ),
        "closed_positions": sorted(
            (r for r in rows if r["status"] == "closed"),
            key=lambda r: r["close_date"],
            reverse=True,
        ),
    }


def _rebased_curve(
    bars: pd.DataFrame | None, entry: float | None, calendar: pd.DatetimeIndex
) -> dict:
    """Cumulative return from ``entry`` on the calendar (0.05 = +5%)."""
    if bars is None or entry is None or entry <= 0:
        return {"dates": [], "values": []}
    series = bars["adj_close"].reindex(calendar).ffill()
    return _series_payload(series / entry - 1.0)


def stocks_payload(ctx: AccountContext) -> dict:
    """Each current holding against SPY, QQQ and its own sector ETF since entry.

    ``attribution`` splits the holding-period return into what the market
    delivered, what the sector added on top of the market, and what is left
    for the stock itself — so a stock that rose only with its sector shows a
    near-zero ``selection``.
    """
    s = get_settings()
    sectors = ctx.sectors()
    rows, bars = _position_rows(ctx.db, ctx.ledger, sectors, ctx.today)
    rows = [r for r in rows if r["status"] == "open"]

    universe = sorted(
        {"SPY", *(r["ticker"] for r in rows), *(r["sector_etf"] for r in rows if r["sector_etf"])}
    )
    trailing, _ = _trailing_returns(ctx.db, universe, ctx.today)

    def trailing_stat(fn, ticker: str, other: str | None):
        if other is None or ticker not in trailing.columns or other not in trailing.columns:
            return None
        return _round_or_none(fn(trailing[ticker], trailing[other], s.min_obs_beta), 4)

    stocks = []
    for r in rows:
        open_date = dt.date.fromisoformat(r["open_date"])
        calendar = ctx.calendar[ctx.calendar >= pd.Timestamp(open_date)]
        curves = {}
        for label, symbol in (
            ("stock", r["ticker"]),
            ("SPY", "SPY"),
            ("QQQ", "QQQ"),
            ("sector_etf", r["sector_etf"]),
        ):
            b = bars.get(symbol) if symbol else None
            entry = _entry_price(b, open_date) if b is not None else None
            curves[label] = _rebased_curve(b, entry, calendar)
        total, spy, etf = r["total_return"], r["spy_return"], r["sector_etf_return"]
        stocks.append(
            {
                **r,
                "curves": curves,
                "attribution": {
                    "market": spy,
                    "sector": _round_or_none(etf - spy)
                    if etf is not None and spy is not None
                    else None,
                    "selection": _round_or_none(total - etf)
                    if total is not None and etf is not None
                    else None,
                },
                "beta_spy": trailing_stat(risk.beta, r["ticker"], "SPY"),
                "beta_sector": trailing_stat(risk.beta, r["ticker"], r["sector_etf"]),
                "r_squared_spy": trailing_stat(risk.r_squared, r["ticker"], "SPY"),
                "r_squared_sector": trailing_stat(
                    risk.r_squared, r["ticker"], r["sector_etf"]
                ),
            }
        )
    stocks.sort(
        key=lambda x: x["total_return"] if x["total_return"] is not None else -9.0,
        reverse=True,
    )
    return {"account": ctx.key, "stocks": stocks}


def sleeves_payload(db: Session) -> dict:
    """All sleeves at a glance, funded or not, for the portfolio page and nav."""
    sleeves = []
    total_value = 0.0
    for acct in _live_accounts(db):
        base = {
            "id": acct.id,
            "name": acct.display_name,
            "number": acct.sleeve_number,
            "planned_start": acct.planned_start,
            "capital": acct.starting_cash,
            "start_date": acct.start_date.isoformat() if acct.start_date else None,
        }
        ctx = AccountContext(db, acct.id)
        if not ctx.ledger or ctx.mv.empty:
            sleeves.append({**base, "status": "pending", "tickers": []})
            continue
        summary = summary_payload(ctx)
        total_value += summary["current_value"]
        cum = perf.link_returns(ctx.returns) - 1.0
        last = ctx.shares.iloc[-1]
        sleeves.append(
            {
                **base,
                "status": "active",
                "tickers": sorted(last[last > 0].index),
                "value": summary["current_value"],
                "invested": summary["invested_capital"],
                "cash": summary["cash"],
                "today": summary["today"],
                "total": summary["total"],
                "twr": summary["twr"],
                "cagr": summary["risk"]["cagr"],
                "benchmarks": summary["benchmarks"],
                "curve": _series_payload(cum),
            }
        )
    for sleeve in sleeves:
        if sleeve["status"] == "active" and total_value > 0:
            sleeve["portfolio_weight"] = round(sleeve["value"] / total_value, 6)
    return {"sleeves": sleeves, "total_value": round(total_value, 2)}


def _active_provider_or_none() -> str | None:
    from .market_data import MarketDataError, active_provider

    try:
        return active_provider()
    except MarketDataError:
        return None


def data_quality_payload(db: Session) -> dict:
    from .ingestion import symbol_universe

    symbols = symbol_universe(db)
    states = {s.ticker: s for s in db.execute(select(SymbolSyncState)).scalars()}
    runs = (
        db.execute(select(RefreshRun).order_by(RefreshRun.started_at.desc()).limit(10))
        .scalars()
        .all()
    )

    # Missing prices per symbol on the SPY calendar
    accounts = _live_accounts(db)
    start = min((a.start_date for a in accounts if a.start_date), default=None)
    issues: list[dict] = []
    if start:
        cal = trading_calendar(db, start, dt.date.today())
        cal_dates = {d.date() for d in cal}
        for sym in symbols:
            have = {
                d
                for (d,) in db.execute(
                    select(PriceBar.date).where(
                        PriceBar.ticker == sym, PriceBar.date >= start
                    )
                )
            }
            missing = sorted(cal_dates - have)
            if missing:
                issues.append(
                    {
                        "type": "missing_prices",
                        "ticker": sym,
                        "detail": f"{len(missing)} missing dates: {', '.join(d.isoformat() for d in missing[:10])}",
                    }
                )

    # Duplicate transactions (same account/date/ticker/type/shares/price, different ids)
    txns = (
        db.execute(
            select(Transaction).where(
                Transaction.account_id.in_([a.id for a in accounts])
            )
        )
        .scalars()
        .all()
    )
    seen: dict[tuple, int] = {}
    for t in txns:
        k = (
            t.account_id,
            t.trade_date,
            t.ticker,
            t.type.value,
            t.shares,
            t.price,
            t.cash_flow,
        )
        seen[k] = seen.get(k, 0) + 1
    for k, n in seen.items():
        if n > 1:
            issues.append(
                {
                    "type": "duplicate_transactions",
                    "ticker": k[2],
                    "detail": f"{n} identical rows for {k[0]} {k[1]} {k[3]}",
                }
            )

    # Negative holdings + reconciliation
    for acct in accounts:
        ctx = AccountContext(db, acct.id)
        if not ctx.shares.empty:
            neg = ctx.shares.iloc[-1]
            for tick, v in neg[neg < -1e-9].items():
                issues.append(
                    {
                        "type": "negative_holdings",
                        "ticker": tick,
                        "detail": f"{acct.id} holds {v:.4f} shares",
                    }
                )
        if not ctx.cash.empty and float(ctx.cash.iloc[-1]) < -1e-6:
            issues.append(
                {
                    "type": "negative_cash",
                    "ticker": None,
                    "detail": f"{acct.id} cash balance {float(ctx.cash.iloc[-1]):.2f}",
                }
            )

    # Combined reconciliation: combined value equals sum of accounts
    if len(accounts) > 1:
        combined = AccountContext(db, COMBINED)
        parts = [AccountContext(db, a.id) for a in accounts]
        if not combined.mv.empty:
            total = None
            for p in parts:
                aligned = p.mv.reindex(combined.mv.index).fillna(0.0)
                total = aligned if total is None else total + aligned
            diff = (combined.mv - total).abs().max()
            if diff > 0.01:
                issues.append(
                    {
                        "type": "reconciliation",
                        "ticker": None,
                        "detail": f"combined vs sum-of-accounts max diff ${diff:.4f}",
                    }
                )

    stale = [
        {
            "ticker": t,
            "last_success_date": s.last_success_date.isoformat()
            if s.last_success_date
            else None,
            "status": s.status,
            "error": (s.error or "")[:200] or None,
        }
        for t, s in sorted(states.items())
        if s.status != "ok"
    ]
    return {
        "symbols": len(symbols),
        "provider": _active_provider_or_none(),
        "issues": issues,
        "stale_symbols": stale,
        "refresh_runs": [
            {
                "id": r.id,
                "trigger": r.trigger,
                "status": r.status,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "symbols_ok": r.symbols_ok,
                "symbols_failed": r.symbols_failed,
                "detail": r.detail,
                "provider": r.provider,
            }
            for r in runs
        ],
    }
