"""Allocation, concentration, and contribution analytics."""

from __future__ import annotations

import numpy as np
import pandas as pd


def weights_from_values(values: pd.Series) -> pd.Series:
    """Position weights from a per-ticker market-value snapshot (excludes cash)."""
    total = values.sum()
    if total <= 0:
        return values * 0.0
    return values / total


def concentration(weights: pd.Series) -> dict:
    w = weights.sort_values(ascending=False)
    out = {
        "largest_position": (
            {"ticker": w.index[0], "weight": float(w.iloc[0])} if len(w) else None
        ),
        "top5": float(w.head(5).sum()) if len(w) else None,
        "top10": float(w.head(10).sum()) if len(w) else None,
        "top20": float(w.head(20).sum()) if len(w) else None,
        "effective_holdings": float(1.0 / np.sum(np.square(w)))
        if len(w) and w.sum() > 0
        else None,
        "num_holdings": int((w > 0).sum()),
    }
    return out


def concentration_curve(weights: pd.Series) -> list[dict]:
    w = weights.sort_values(ascending=False)
    cum = w.cumsum()
    return [
        {
            "rank": i + 1,
            "ticker": t,
            "weight": float(w.iloc[i]),
            "cumulative": float(cum.iloc[i]),
        }
        for i, t in enumerate(w.index)
    ]


def sector_allocation(values: pd.Series, sectors: dict[str, str]) -> list[dict]:
    df = pd.DataFrame({"value": values})
    df["sector"] = [sectors.get(t, "Unknown") for t in df.index]
    grouped = df.groupby("sector")["value"].sum().sort_values(ascending=False)
    total = grouped.sum()
    return [
        {
            "sector": s,
            "value": float(v),
            "weight": float(v / total) if total > 0 else 0.0,
        }
        for s, v in grouped.items()
    ]


def drift_vs_target(
    weights: pd.Series, target_weights_pct: dict[str, float]
) -> list[dict]:
    rows = []
    tickers = set(weights.index) | set(target_weights_pct)
    for t in sorted(tickers):
        current = float(weights.get(t, 0.0))
        target = float(target_weights_pct.get(t, 0.0)) / 100.0
        rows.append(
            {
                "ticker": t,
                "current": current,
                "target": target,
                "drift": current - target,
            }
        )
    rows.sort(key=lambda r: abs(r["drift"]), reverse=True)
    return rows


def daily_contributions(
    ticker_values: pd.DataFrame, ticker_returns: pd.DataFrame, total_mv: pd.Series
) -> pd.DataFrame:
    """Per-ticker contribution to each day's portfolio return.

    Arithmetic attribution: contribution_t = weight_{t-1} × r_t where the
    weight uses the prior day's total account value (including cash). Summed
    over days this approximates cumulative contribution; documented as an
    arithmetic approximation of the geometrically-linked return.
    """
    if ticker_values.empty:
        return pd.DataFrame()
    prev_total = total_mv.shift(1)
    prev_weights = ticker_values.shift(1).div(prev_total, axis=0)
    contrib = prev_weights * ticker_returns
    return contrib.dropna(how="all")


def risk_contributions(
    ticker_returns: pd.DataFrame, weights: pd.Series, min_obs: int = 5
) -> list[dict]:
    """Contribution to portfolio volatility: w_i × cov(r_i, r_p) / σ_p.

    Uses the weighted portfolio return implied by current weights over the
    common history (marginal-contribution decomposition; contributions sum to
    total portfolio volatility).
    """
    common = [
        t for t in weights.index if t in ticker_returns.columns and weights[t] > 0
    ]
    if not common:
        return []
    rets = ticker_returns[common].dropna(how="any")
    if len(rets) < min_obs:
        return []
    w = weights[common] / weights[common].sum()
    port = rets @ w
    sigma_p = port.std(ddof=1)
    if sigma_p == 0 or np.isnan(sigma_p):
        return []
    out = []
    for t in common:
        cov = rets[t].cov(port)
        mcr = float(w[t] * cov / sigma_p)  # daily units
        out.append({"ticker": t, "contribution": mcr * np.sqrt(252)})
    out.sort(key=lambda r: abs(r["contribution"]), reverse=True)
    return out
