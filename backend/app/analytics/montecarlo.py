"""Monte Carlo comparison: the actual equal-weight portfolio vs random picks
from the same index.

Each simulated portfolio invests equal dollars across N randomly chosen
tickers on the account's inception date and holds (buy-and-hold), priced on
adjusted close — the same convention already used for benchmark price
returns (``analytics/benchmarks.py``). There is no transaction ledger for
tickers the account never actually held, so adjusted close is the only
return series available; a ticker's own corporate actions are already baked
into FMP's adjustment.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _basket_growth_of_100(adj_closes: pd.DataFrame, weights: pd.Series) -> pd.Series:
    """Growth of $100 for a buy-and-hold basket, ``weights`` fractions of 1.0.

    Every ticker must have a real price on the *first* calendar row (the
    common entry date) — a ticker missing there fails the whole simulation
    rather than silently dropping out of the sum (which would understate
    early-date value and look like a fake dip/jump once its data arrives).
    """
    cols = [t for t in weights.index if t in adj_closes.columns]
    if len(cols) != len(weights) or adj_closes.empty:
        return pd.Series(dtype=float)
    sub = adj_closes[cols]
    first = sub.iloc[0]
    if first.isna().any() or (first <= 0).any():
        return pd.Series(dtype=float)
    normalized = sub.divide(first, axis=1)
    dollars = normalized.mul(weights[cols] * 100.0, axis=1)
    # No min_count=1: any remaining interior NaN must propagate as NaN, never
    # silently sum as if that ticker contributed zero.
    return dollars.sum(axis=1).dropna()


def equal_weight_growth_of_100(adj_closes: pd.DataFrame, tickers: list[str]) -> pd.Series:
    """Growth of $100 split equally across ``tickers`` at their first shared price."""
    if not tickers:
        return pd.Series(dtype=float)
    weights = pd.Series(1.0 / len(tickers), index=tickers)
    return _basket_growth_of_100(adj_closes, weights)


def sample_universe(
    universe: list[str], n: int, sims: int, rng: np.random.Generator
) -> list[list[str]]:
    """``sims`` draws of ``n`` distinct tickers each, without replacement per draw."""
    if n <= 0 or not universe:
        return []
    picks: list[list[str]] = []
    for _ in range(sims):
        chosen = rng.choice(universe, size=min(n, len(universe)), replace=False)
        picks.append(sorted(chosen.tolist()))
    return picks


def summarize(curves: list[pd.Series], calendar: pd.DatetimeIndex) -> dict[str, pd.Series]:
    """Per-date mean and median across simulated equity curves."""
    if not curves:
        empty = pd.Series(dtype=float)
        return {"mean": empty, "median": empty}
    mat = pd.concat([c.reindex(calendar) for c in curves], axis=1)
    return {"mean": mat.mean(axis=1), "median": mat.median(axis=1)}
