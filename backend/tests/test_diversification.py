"""Unit tests for correlation matrix / PCA diversification analytics."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.analytics import diversification as div


def _returns(n=40, seed=0):
    rng = np.random.default_rng(seed)
    market = rng.normal(0, 0.01, n)
    idio = rng.normal(0, 0.005, (n, 3))
    # AAA and BBB track the market almost identically; CCC is independent noise.
    aaa = market + idio[:, 0] * 0.1
    bbb = market + idio[:, 1] * 0.1
    ccc = idio[:, 2]
    idx = pd.bdate_range("2026-01-02", periods=n)
    return pd.DataFrame({"AAA": aaa, "BBB": bbb, "CCC": ccc}, index=idx)


def test_correlation_matrix_shape_and_diagonal():
    rets = _returns()
    out = div.correlation_matrix(rets, ["AAA", "BBB", "CCC"], min_obs=5)
    assert out is not None
    assert out["tickers"] == ["AAA", "BBB", "CCC"]
    assert out["observations"] == len(rets)
    for i, row in enumerate(out["matrix"]):
        assert row[i] == pytest.approx(1.0)
    # AAA/BBB share the same market factor -> high correlation.
    i, j = out["tickers"].index("AAA"), out["tickers"].index("BBB")
    assert out["matrix"][i][j] > 0.8


def test_correlation_matrix_insufficient_history_returns_none():
    rets = _returns(n=3)
    assert div.correlation_matrix(rets, ["AAA", "BBB", "CCC"], min_obs=10) is None


def test_correlation_matrix_requires_two_tickers():
    rets = _returns()
    assert div.correlation_matrix(rets, ["AAA"], min_obs=5) is None


def test_pca_two_correlated_one_independent_gives_between_1_and_3_bets():
    rets = _returns()
    out = div.pca_diversification(rets, ["AAA", "BBB", "CCC"], min_obs=5)
    assert out is not None
    assert out["num_holdings"] == 3
    # Not fully redundant (>1) but not fully independent (<3): AAA/BBB share
    # a common factor while CCC is independent.
    assert 1.0 < out["effective_bets"] < 3.0
    pcts = [row["variance_pct"] for row in out["variance_explained"]]
    assert pytest.approx(sum(pcts), abs=1e-3) == 1.0
    # PC1 should load heavily on the two correlated names.
    top = {r["ticker"] for r in out["pc1_loadings"][:2]}
    assert top == {"AAA", "BBB"}


def test_pca_fully_correlated_holdings_gives_one_effective_bet():
    idx = pd.bdate_range("2026-01-02", periods=30)
    base = np.random.default_rng(1).normal(0, 0.01, 30)
    rets = pd.DataFrame({"AAA": base, "BBB": base * 2.0}, index=idx)
    out = div.pca_diversification(rets, ["AAA", "BBB"], min_obs=5)
    assert out["effective_bets"] == pytest.approx(1.0, abs=1e-6)


def test_pca_insufficient_history_returns_none():
    rets = _returns(n=3)
    assert div.pca_diversification(rets, ["AAA", "BBB", "CCC"], min_obs=10) is None
