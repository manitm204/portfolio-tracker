"""Cross-sectional diversification analytics: correlation matrix and PCA.

Both operate on the common (no-NaN) history across a set of currently-held
tickers, independent of position weights — they answer "how redundant are
these return streams," not "how much does each position weigh." Everything
below a configurable minimum number of observations returns ``None``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _common_history(
    ticker_returns: pd.DataFrame, tickers: list[str]
) -> pd.DataFrame:
    cols = [t for t in tickers if t in ticker_returns.columns]
    if len(cols) < 2:
        return pd.DataFrame()
    return ticker_returns[cols].dropna(how="any")


def correlation_matrix(
    ticker_returns: pd.DataFrame, tickers: list[str], min_obs: int
) -> dict | None:
    """Pairwise Pearson correlation of daily returns over common history."""
    hist = _common_history(ticker_returns, tickers)
    if len(hist) < max(min_obs, 2):
        return None
    corr = hist.corr()
    return {
        "tickers": list(corr.columns),
        "matrix": [[round(float(v), 4) for v in row] for row in corr.values],
        "observations": int(len(hist)),
    }


def pca_diversification(
    ticker_returns: pd.DataFrame, tickers: list[str], min_obs: int
) -> dict | None:
    """PCA on the correlation matrix of held tickers' common-history returns.

    ``effective_bets`` is exp(Shannon entropy of the normalized eigenvalues) —
    1 means every holding moves together (one bet), N means N fully
    uncorrelated holdings (N independent bets). This is a property of the
    correlation structure alone, not of position sizing (see the
    weight-based "effective holdings" count on the Allocation page for that).
    """
    hist = _common_history(ticker_returns, tickers)
    n = hist.shape[1]
    if len(hist) < max(min_obs, 2) or n < 2:
        return None
    corr = hist.corr().to_numpy()
    eigvals, eigvecs = np.linalg.eigh(corr)
    order = np.argsort(eigvals)[::-1]
    eigvals = np.clip(eigvals[order], 0.0, None)
    eigvecs = eigvecs[:, order]

    total = eigvals.sum()
    if total <= 0:
        return None
    p = eigvals / total
    nz = p[p > 1e-12]
    entropy = float(-np.sum(nz * np.log(nz)))
    effective_bets = float(np.exp(entropy))

    top_k = min(10, n)
    variance_explained = [
        {"component": i + 1, "variance_pct": round(float(p[i]), 4)}
        for i in range(top_k)
    ]

    pc1 = eigvecs[:, 0]
    if pc1.sum() < 0:  # sign is arbitrary; orient so the dominant common move is positive
        pc1 = -pc1
    loadings = sorted(
        (
            {"ticker": t, "loading": round(float(w), 4)}
            for t, w in zip(hist.columns, pc1)
        ),
        key=lambda r: -abs(r["loading"]),
    )

    return {
        "tickers": list(hist.columns),
        "observations": int(len(hist)),
        "effective_bets": round(effective_bets, 2),
        "num_holdings": n,
        "variance_explained": variance_explained,
        "pc1_loadings": loadings,
    }
