"""Assembles analytics into API-shaped payloads.

``account_key`` is either a real account id or the pseudo-account
``combined``, which merges the ledgers of every account (positions and cash
sum; the combined benchmark receives both accounts' external flows on their
own dates, so differing inceptions are respected).
"""

from __future__ import annotations

import datetime as dt
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
from .fmp_client import FMPClient
from .ingestion import FACTOR_ETFS, TRAILING_LOOKBACK_CALENDAR_DAYS
from .models import (
    Account,
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

# Accounts the Monte Carlo comparison can simulate: equal dollars across N
# randomly chosen S&P 500 tickers, same convention as the real portfolio.
MONTE_CARLO_ACCOUNTS = {"PORTFOLIO_5"}


class UnknownAccount(Exception):
    pass


class UnsupportedMonteCarlo(Exception):
    pass


def resolve_account_ids(db: Session, account_key: str) -> list[str]:
    ids = [a for (a,) in db.execute(select(Account.id))]
    if account_key == COMBINED:
        return ids
    if account_key in ids:
        return [account_key]
    raise UnknownAccount(account_key)


def list_accounts(db: Session) -> list[dict]:
    accounts = db.execute(select(Account).order_by(Account.start_date)).scalars().all()
    out = [
        {
            "id": a.id,
            "display_name": a.display_name,
            "start_date": a.start_date.isoformat(),
            "starting_cash": a.starting_cash,
            "benchmarks": [a.benchmark_1, a.benchmark_2],
        }
        for a in accounts
    ]
    if len(accounts) > 1:
        out.append(
            {
                "id": COMBINED,
                "display_name": "Combined",
                "start_date": min(a.start_date for a in accounts).isoformat(),
                "starting_cash": sum(a.starting_cash for a in accounts),
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
        self.inception: dt.date = min(a.start_date for a in accounts)
        self.benchmarks = ["SPY", "QQQ"]
        self.factor_etfs = list(FACTOR_ETFS)

        self.ledger = load_ledger(db, self.account_ids)
        self.today = dt.date.today()
        self.calendar = trading_calendar(db, self.inception, self.today)

        tickers = sorted(
            {t.ticker for t in self.ledger if t.ticker}
            | {t.new_ticker for t in self.ledger if t.new_ticker}
        )
        self.tickers = tickers
        frame = load_price_frame(
            db,
            tickers + self.benchmarks + self.factor_etfs,
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

        raw_closes = close_matrix(frame[frame["ticker"].isin(tickers)], "close")
        adj_closes = close_matrix(frame[frame["ticker"].isin(tickers)], "adj_close")
        self.closes, self.missing = ffill_with_coverage(raw_closes, self.calendar)
        self.adj_closes, _ = ffill_with_coverage(adj_closes, self.calendar)
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
        return {"account": ctx.key, "holdings": [], "inactive": _inactive_rows(targets)}

    last_shares = (
        ctx.shares.iloc[-1] if not ctx.shares.empty else pd.Series(dtype=float)
    )
    last_values = ctx.ticker_values.iloc[-1]
    active = last_values[last_shares.reindex(last_values.index).fillna(0.0) > 0]
    weights = alloc.weights_from_values(active)

    cost_basis = _cost_basis(ctx)
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
                "composite_score": targets[ticker].composite_score
                if ticker in targets
                else None,
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
    return {"account": ctx.key, "holdings": rows, "inactive": _inactive_rows(targets)}


def _inactive_rows(targets: dict[str, ModelTarget]) -> list[dict]:
    return [
        {
            "ticker": t.ticker,
            "sector": t.sector,
            "composite_score": t.composite_score,
            "note": "Inactive candidate — excluded from all portfolio statistics",
        }
        for t in targets.values()
        if not t.active
    ]


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


def risk_payload(ctx: AccountContext) -> dict:
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
    # correlation matrix, PCA) uses each held ticker's own trailing ~1-year
    # price history, never the account's short inception-to-date window — a
    # stock you bought 5 days ago still gets a real trailing-year beta/
    # correlation from its actual market history, not "insufficient history".
    trailing_universe = sorted(set(held_tickers) | {"SPY"} | set(FACTOR_ETFS))
    trailing_returns, trailing_obs = _trailing_returns(
        ctx.db, trailing_universe, ctx.today
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
        alloc.risk_contributions(ctx.ticker_returns, weights)
        if not ctx.ticker_returns.empty
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
        "trailing_window": {
            "target_trading_days": TRAILING_TRADING_DAYS,
            "observations": trailing_obs,
        },
    }


HEATMAP_PERIODS = ("1D", "1W", "1M", "SI")


def heatmap_payload(ctx: AccountContext, period: str = "1D") -> dict:
    if period not in HEATMAP_PERIODS:
        period = "1D"
    if ctx.ticker_values.empty:
        return {"account": ctx.key, "period": period, "tiles": []}
    sectors = ctx.sectors()
    last_shares = ctx.shares.iloc[-1]
    last_values = ctx.ticker_values.iloc[-1]
    active = last_values[last_shares.reindex(last_values.index).fillna(0.0) > 0]
    weights = alloc.weights_from_values(active)
    cost_basis = _cost_basis(ctx)

    end = ctx.adj_closes.index[-1] if not ctx.adj_closes.empty else None
    tiles = []
    for ticker, value in active.items():
        ret = None
        if period == "SI":
            cb = cost_basis.get(ticker)
            if cb and cb.get("cost"):
                ret = float(value) / cb["cost"] - 1.0
        elif end is not None and ticker in ctx.adj_closes.columns:
            ser = ctx.adj_closes[ticker].dropna()
            if len(ser) >= 2:
                if period == "1D":
                    ret = float(ser.iloc[-1] / ser.iloc[-2] - 1.0)
                else:
                    delta = {"1W": pd.Timedelta(days=7), "1M": pd.DateOffset(months=1)}[
                        period
                    ]
                    cutoff = end - delta
                    base = ser[ser.index <= cutoff]
                    base_val = base.iloc[-1] if len(base) else ser.iloc[0]
                    ret = float(ser.iloc[-1] / base_val - 1.0)
        tiles.append(
            {
                "ticker": ticker,
                "sector": sectors.get(ticker, "Unknown"),
                "weight": round(float(weights[ticker]), 6),
                "value": round(float(value), 2),
                "return": _round_or_none(ret),
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
    sector_rows = [
        {
            "sector": k,
            "weight": round(v["weight"], 6),
            "return": round(v["wret"] / v["weight"], 6) if v["weight"] > 0 else None,
        }
        for k, v in sorted(sector_perf.items(), key=lambda kv: -kv[1]["weight"])
    ]
    return {
        "account": ctx.key,
        "period": period,
        "periods": list(HEATMAP_PERIODS),
        "tiles": tiles,
        "sectors": sector_rows,
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
    philosophy as the real portfolio (see ``MONTE_CARLO_ACCOUNTS``)."""
    if ctx.key not in MONTE_CARLO_ACCOUNTS:
        raise UnsupportedMonteCarlo(
            f"Monte Carlo comparison is only available for: {', '.join(sorted(MONTE_CARLO_ACCOUNTS))}"
        )
    targets = [t for t in ctx.targets() if t.active]
    actual = perf.growth_of_100(ctx.returns)
    if not targets or actual.empty:
        return {"account": ctx.key, "empty": True}

    from .ingestion import ensure_adjusted_history, ensure_sp500_constituents

    rng = np.random.default_rng(seed)
    db = ctx.db

    method = "equal_weight"
    n = len(targets)
    with FMPClient() as client:
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
    db: Session, tickers: list[str], today: dt.date
) -> tuple[pd.DataFrame, int]:
    """Each ticker's own trailing ~1-year (up to 252 trading day) daily return
    series, independent of the account's inception date or how long a position
    has actually been held.

    Pure DB read — the ingestion job is responsible for keeping
    ``TRAILING_LOOKBACK_CALENDAR_DAYS`` of history cached for every tracked
    symbol (see ingestion.earliest_needed_date), so this never triggers a live
    fetch. Symbols missing that history simply reduce the observation count,
    same "insufficient history" degradation as every other risk stat.
    """
    if not tickers:
        return pd.DataFrame(), 0
    start = today - dt.timedelta(days=TRAILING_LOOKBACK_CALENDAR_DAYS)
    calendar = trading_calendar(db, start, today)[-TRAILING_TRADING_DAYS:]
    if len(calendar) == 0:
        return pd.DataFrame(), 0
    frame = load_price_frame(db, tickers, start, today)
    adj = close_matrix(frame, "adj_close")
    filled, _ = ffill_with_coverage(adj, calendar)
    returns = filled.pct_change().iloc[1:]
    return returns, int(len(calendar))


def account_contributions(db: Session) -> list[dict]:
    """Per-account share of the combined value and return (combined view)."""
    out = []
    for aid in resolve_account_ids(db, COMBINED):
        ctx = AccountContext(db, aid)
        if ctx.mv.empty:
            continue
        twr = perf.twr_total(ctx.returns)
        invested = float(sum(f for _, f in ctx.ext_flows))
        out.append(
            {
                "account": aid,
                "value": round(float(ctx.mv.iloc[-1]), 2),
                "invested": round(invested, 2),
                "gain": round(float(ctx.mv.iloc[-1]) - invested, 2),
                "twr": _round_or_none(twr),
            }
        )
    return out


def _realized_trades(ledger: list[Transaction]) -> list[dict]:
    """Closed positions (fully sold out): realized gain %, holding period, CAGR.

    Walks the ledger per ticker in chronological order using the same
    average-cost method as ``_cost_basis``. Each time a position returns to
    ~zero shares after being open, that closes a "trade episode" — buying the
    same ticker again later starts a new, separate episode.
    """
    episodes: list[dict] = []
    state: dict[str, dict] = {}
    for txn in ledger:
        if txn.ticker is None:
            continue
        st = state.setdefault(
            txn.ticker,
            {"shares": 0.0, "cost": 0.0, "total_cost": 0.0, "proceeds": 0.0, "open_date": None},
        )
        if txn.type == TransactionType.BUY:
            if st["shares"] <= 1e-9:
                st["open_date"] = txn.trade_date
                st["cost"] = 0.0
                st["total_cost"] = 0.0
                st["proceeds"] = 0.0
            buy_cost = (
                -(txn.cash_flow)
                if txn.cash_flow is not None
                else (txn.shares or 0) * (txn.price or 0)
            )
            st["cost"] += buy_cost
            st["total_cost"] += buy_cost
            st["shares"] += txn.shares or 0.0
        elif txn.type == TransactionType.SELL:
            if st["shares"] > 1e-9 and (txn.shares or 0) > 0:
                sell_shares = min(txn.shares, st["shares"])
                proceeds = (
                    txn.cash_flow
                    if txn.cash_flow is not None
                    else sell_shares * (txn.price or 0)
                )
                avg = st["cost"] / st["shares"]
                st["cost"] -= avg * sell_shares
                st["shares"] -= sell_shares
                st["proceeds"] += proceeds
                if st["shares"] <= 1e-6 and st["open_date"] is not None and st["total_cost"] > 0:
                    open_date = st["open_date"]
                    close_date = txn.trade_date
                    hold_days = (close_date - open_date).days
                    gain_pct = st["proceeds"] / st["total_cost"] - 1.0
                    cagr = (
                        (1.0 + gain_pct) ** (365.0 / hold_days) - 1.0
                        if hold_days > 0
                        else None
                    )
                    episodes.append(
                        {
                            "ticker": txn.ticker,
                            "open_date": open_date.isoformat(),
                            "close_date": close_date.isoformat(),
                            "hold_days": hold_days,
                            "total_cost": round(st["total_cost"], 2),
                            "total_proceeds": round(st["proceeds"], 2),
                            "gain_dollar": round(st["proceeds"] - st["total_cost"], 2),
                            "gain_pct": _round_or_none(gain_pct),
                            "cagr": _round_or_none(cagr),
                        }
                    )
                    st["open_date"] = None
        elif txn.type == TransactionType.SPLIT and txn.split_ratio:
            st["shares"] *= txn.split_ratio
        elif txn.type == TransactionType.SYMBOL_CHANGE and txn.new_ticker:
            state[txn.new_ticker] = state.pop(txn.ticker)
    episodes.sort(key=lambda e: e["close_date"], reverse=True)
    return episodes


def history_payload(db: Session, account_key: str) -> dict:
    from .ingestion import history_events

    account_ids = resolve_account_ids(db, account_key)
    ledger = load_ledger(db, account_ids)
    return {
        "account": account_key,
        "events": history_events(db, account_ids),
        "closed_positions": _realized_trades(ledger),
    }


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
    accounts = db.execute(select(Account)).scalars().all()
    start = min(a.start_date for a in accounts) if accounts else None
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
    txns = db.execute(select(Transaction)).scalars().all()
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
            }
            for r in runs
        ],
    }
