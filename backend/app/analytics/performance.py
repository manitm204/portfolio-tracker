"""Valuation, time-weighted return, and money-weighted return (XIRR).

Conventions (documented in the methodology page)
------------------------------------------------
* Daily market value = Σ shares × raw close + cash. Shares are actual shares
  (splits arrive as SPLIT ledger rows), so raw closes are the correct price.
* External flows are treated as START-of-day flows (the initial deposit funds
  the same-morning open purchases), so the daily TWR return is
      r_t = MV_t / (MV_{t-1} + F_t) − 1
  which means same-day external cash flows create no false performance.
* TWR over a window is the geometric link of daily returns.
* XIRR solves Σ CF_i (1+r)^{-(t_i-t_0)/365} = 0 with the terminal market value
  as a final positive flow; investment outflows are negative flows.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd


def market_value_series(
    shares: pd.DataFrame,
    cash: pd.Series,
    closes: pd.DataFrame,
) -> tuple[pd.Series, pd.DataFrame]:
    """Daily total account value and per-ticker market-value frame.

    ``closes`` must already be aligned/forward-filled onto the same calendar.
    """
    if shares.empty:
        mv = cash.copy() if not cash.empty else pd.Series(dtype=float)
        return mv, pd.DataFrame(index=cash.index)
    tickers = [t for t in shares.columns if t in closes.columns]
    values = shares[tickers] * closes[tickers]
    position_value = values.sum(axis=1)
    total = position_value.add(cash, fill_value=0.0)
    return total, values


def daily_twr_returns(mv: pd.Series, flows: pd.Series) -> pd.Series:
    """Daily time-weighted returns with start-of-day external flows."""
    if mv.empty:
        return pd.Series(dtype=float)
    prev = mv.shift(1).fillna(0.0)
    denom = prev + flows.reindex(mv.index).fillna(0.0)
    r = pd.Series(np.nan, index=mv.index)
    mask = denom > 0
    r[mask] = mv[mask] / denom[mask] - 1.0
    return r.dropna()


def link_returns(returns: pd.Series) -> pd.Series:
    """Cumulative growth index (starts at the first day's 1+r)."""
    return (1.0 + returns).cumprod()


def twr_total(returns: pd.Series) -> float | None:
    if returns.empty:
        return None
    return float((1.0 + returns).prod() - 1.0)


def growth_of_100(returns: pd.Series) -> pd.Series:
    return 100.0 * link_returns(returns)


def xirr(
    flows: list[tuple[dt.date, float]], terminal: tuple[dt.date, float]
) -> float | None:
    """Annualized money-weighted return. Returns None when not solvable.

    ``flows``: investor perspective — money invested is NEGATIVE, money
    received is POSITIVE. ``terminal``: (date, ending market value), positive.
    """
    cfs = [(d, -amount) for d, amount in flows]  # deposits are outflows from investor
    cfs.append(terminal)
    cfs = [(d, a) for d, a in cfs if abs(a) > 1e-12]
    if len(cfs) < 2:
        return None
    has_neg = any(a < 0 for _, a in cfs)
    has_pos = any(a > 0 for _, a in cfs)
    if not (has_neg and has_pos):
        return None
    t0 = min(d for d, _ in cfs)
    times = np.array([(d - t0).days / 365.0 for d, _ in cfs])
    amounts = np.array([a for _, a in cfs])

    def npv(rate: float) -> float:
        return float(np.sum(amounts / np.power(1.0 + rate, times)))

    lo, hi = -0.9999, 100.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2.0
        f_mid = npv(mid)
        if abs(f_mid) < 1e-9:
            return mid
        if f_lo * f_mid <= 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2.0


def period_slice(
    series: pd.Series, start: dt.date | None, end: dt.date | None
) -> pd.Series:
    out = series
    if start is not None:
        out = out[out.index >= pd.Timestamp(start)]
    if end is not None:
        out = out[out.index <= pd.Timestamp(end)]
    return out


def period_returns_table(returns: pd.Series) -> dict[str, float | None]:
    """Standard period returns computed from the daily TWR series."""
    if returns.empty:
        return {}
    end = returns.index[-1]
    start = returns.index[0]

    def since(ts: pd.Timestamp) -> float | None:
        """Return None (not partial) when the lookback predates the history."""
        if ts < start:
            return None
        sub = returns[returns.index > ts]
        return twr_total(sub) if not sub.empty else None

    out: dict[str, float | None] = {
        "1D": float(returns.iloc[-1]),
        "1W": since(end - pd.Timedelta(days=7)),
        "1M": since(end - pd.DateOffset(months=1)),
        "3M": since(end - pd.DateOffset(months=3)),
        "6M": since(end - pd.DateOffset(months=6)),
        "1Y": since(end - pd.DateOffset(years=1)),
        "YTD": twr_total(returns[returns.index > pd.Timestamp(end.year - 1, 12, 31)]),
        "SI": twr_total(returns),
    }
    return out


def max_drawdown(returns: pd.Series) -> tuple[float | None, pd.Series]:
    """(max drawdown as a negative fraction, drawdown series)."""
    if returns.empty:
        return None, pd.Series(dtype=float)
    idx = link_returns(returns)
    peak = idx.cummax()
    dd = idx / peak - 1.0
    return float(dd.min()), dd
