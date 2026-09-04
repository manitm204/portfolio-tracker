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


def weighted_growth_of_100(adj_closes: pd.DataFrame, weights: pd.Series) -> pd.Series:
    """Growth of $100 for a buy-and-hold basket at arbitrary entry weights.

    ``weights`` should sum to 1.0. Like ``equal_weight_growth_of_100``, a
    ticker missing from ``adj_closes`` fails the whole simulation rather than
    silently reweighting the survivors.
    """
    return _basket_growth_of_100(adj_closes, weights)


def sample_sector_matched(
    universe_by_sector: dict[str, list[str]],
    sector_counts: dict[str, int],
    sims: int,
    rng: np.random.Generator,
) -> list[dict[str, list[str]]]:
    """``sims`` draws that replicate the real portfolio's per-sector holding
    counts, each sector's tickers drawn without replacement from that
    sector's S&P 500 pool."""
    picks: list[dict[str, list[str]]] = []
    for _ in range(sims):
        draw: dict[str, list[str]] = {}
        for sector, n in sector_counts.items():
            pool = universe_by_sector.get(sector, [])
            if n <= 0 or not pool:
                continue
            chosen = rng.choice(pool, size=min(n, len(pool)), replace=False)
            draw[sector] = sorted(chosen.tolist())
        picks.append(draw)
    return picks


def market_cap_sector_weights(
    picks_by_sector: dict[str, list[str]],
    market_caps: dict[str, float],
    sector_target_weights: dict[str, float],
) -> pd.Series:
    """Raw market-cap weights within each sector, scaled so each sector's
    total matches ``sector_target_weights`` (fractions summing to ~1.0)."""
    rows: dict[str, float] = {}
    for sector, tickers in picks_by_sector.items():
        caps = {t: market_caps.get(t, 0.0) for t in tickers}
        total_cap = sum(caps.values())
        target = sector_target_weights.get(sector, 0.0)
        if total_cap <= 0 or target <= 0:
            continue
        for t, cap in caps.items():
            if cap > 0:
                rows[t] = (cap / total_cap) * target
    return pd.Series(rows, dtype=float)


def cap_weights(weights: pd.Series, cap: float = 0.10, max_iter: int = 50) -> pd.Series:
    """Normalize to fractions summing to 1.0, then cap any position at
    ``cap``, redistributing the excess proportionally among uncapped
    positions.

    Standard iterative water-filling: capping one name can push another over
    the limit, so this repeats until stable or ``max_iter`` is reached. The
    result always sums to 1.0 (each redistribution preserves total weight).
    """
    if weights.empty or weights.sum() <= 0:
        return weights
    w = weights / weights.sum()
    capped = pd.Series(False, index=w.index)
    for _ in range(max_iter):
        over = (w > cap + 1e-12) & ~capped
        if not over.any():
            break
        excess = (w[over] - cap).sum()
        w[over] = cap
        capped[over] = True
        free = ~capped
        free_total = w[free].sum()
        if free_total <= 0:
            break
        w[free] = w[free] + excess * (w[free] / free_total)
    return w


def summarize(curves: list[pd.Series], calendar: pd.DatetimeIndex) -> dict[str, pd.Series]:
    """Per-date mean and median across simulated equity curves."""
    if not curves:
        empty = pd.Series(dtype=float)
        return {"mean": empty, "median": empty}
    mat = pd.concat([c.reindex(calendar) for c in curves], axis=1)
    return {"mean": mat.mean(axis=1), "median": mat.median(axis=1)}
