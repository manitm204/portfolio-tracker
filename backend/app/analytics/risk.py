"""Risk analytics on aligned daily return series.

Portfolio beta is estimated from the covariance of the portfolio's own daily
TWR returns against SPY daily returns — never as a weighted average of
vendor-supplied ticker betas. Security-level betas (for the separately
labelled contribution view) are estimated the same way per ticker.

All statistics require a configurable minimum number of observations and
return ``None`` (rendered as “insufficient history”) below it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import get_settings
from .performance import max_drawdown as _max_drawdown
from .performance import twr_total as _twr_total


def _aligned(a: pd.Series, b: pd.Series) -> pd.DataFrame:
    df = pd.concat({"a": a, "b": b}, axis=1, join="inner").dropna()
    return df


def beta(
    portfolio: pd.Series, benchmark: pd.Series, min_obs: int | None = None
) -> float | None:
    min_obs = min_obs if min_obs is not None else get_settings().min_obs_beta
    df = _aligned(portfolio, benchmark)
    if len(df) < max(min_obs, 2):
        return None
    var = df["b"].var(ddof=1)
    if var == 0 or np.isnan(var):
        return None
    return float(df["a"].cov(df["b"]) / var)


def alpha(
    returns: pd.Series, benchmark: pd.Series, min_obs: int | None = None
) -> float | None:
    """Annualized CAPM (Jensen's) alpha vs ``benchmark``.

    alpha = ann_mean(returns) − [rf + beta × (ann_mean(benchmark) − rf)],
    computed on the same aligned dates used for the beta estimate.
    """
    s = get_settings()
    b = beta(returns, benchmark, min_obs)
    if b is None:
        return None
    df = _aligned(returns, benchmark)
    ann_r = df["a"].mean() * s.trading_days_per_year
    ann_b = df["b"].mean() * s.trading_days_per_year
    rf = s.risk_free_rate_annual
    return float(ann_r - (rf + b * (ann_b - rf)))


def correlation(
    portfolio: pd.Series, benchmark: pd.Series, min_obs: int | None = None
) -> float | None:
    min_obs = min_obs if min_obs is not None else get_settings().min_obs_beta
    df = _aligned(portfolio, benchmark)
    if len(df) < max(min_obs, 2):
        return None
    c = df["a"].corr(df["b"])
    return None if pd.isna(c) else float(c)


def r_squared(
    portfolio: pd.Series, benchmark: pd.Series, min_obs: int | None = None
) -> float | None:
    """Fraction of the portfolio's variance explained by the benchmark (corr²)."""
    c = correlation(portfolio, benchmark, min_obs)
    return None if c is None else float(c**2)


def tracking_error(
    returns: pd.Series, benchmark: pd.Series, min_obs: int | None = None
) -> float | None:
    """Annualized stdev of (returns − benchmark), on aligned daily observations."""
    s = get_settings()
    min_obs = min_obs if min_obs is not None else s.min_obs_vol
    df = _aligned(returns, benchmark)
    if len(df) < max(min_obs, 2):
        return None
    excess = df["a"] - df["b"]
    return float(excess.std(ddof=1) * np.sqrt(s.trading_days_per_year))


def information_ratio(
    returns: pd.Series, benchmark: pd.Series, min_obs: int | None = None
) -> float | None:
    """Annualized mean excess return over ``benchmark`` / tracking error."""
    s = get_settings()
    te = tracking_error(returns, benchmark, min_obs)
    if te is None or te == 0:
        return None
    df = _aligned(returns, benchmark)
    ann_excess = (df["a"] - df["b"]).mean() * s.trading_days_per_year
    return float(ann_excess / te)


def annualized_volatility(
    returns: pd.Series, min_obs: int | None = None
) -> float | None:
    s = get_settings()
    min_obs = min_obs if min_obs is not None else s.min_obs_vol
    r = returns.dropna()
    if len(r) < max(min_obs, 2):
        return None
    return float(r.std(ddof=1) * np.sqrt(s.trading_days_per_year))


def downside_deviation(returns: pd.Series, min_obs: int | None = None) -> float | None:
    s = get_settings()
    min_obs = min_obs if min_obs is not None else s.min_obs_vol
    r = returns.dropna()
    if len(r) < max(min_obs, 2):
        return None
    rf_daily = s.risk_free_rate_annual / s.trading_days_per_year
    downside = np.minimum(r - rf_daily, 0.0)
    return float(np.sqrt(np.mean(downside**2)) * np.sqrt(s.trading_days_per_year))


def sharpe(returns: pd.Series, min_obs: int | None = None) -> float | None:
    s = get_settings()
    vol = annualized_volatility(returns, min_obs)
    if vol is None or vol == 0:
        return None
    r = returns.dropna()
    ann_mean = r.mean() * s.trading_days_per_year
    return float((ann_mean - s.risk_free_rate_annual) / vol)


def sortino(returns: pd.Series, min_obs: int | None = None) -> float | None:
    s = get_settings()
    dd = downside_deviation(returns, min_obs)
    if dd is None or dd == 0:
        return None
    r = returns.dropna()
    ann_mean = r.mean() * s.trading_days_per_year
    return float((ann_mean - s.risk_free_rate_annual) / dd)


def cagr(returns: pd.Series, min_obs: int | None = None) -> float | None:
    """Geometrically compounded annual growth rate over the full history span."""
    s = get_settings()
    min_obs = min_obs if min_obs is not None else s.min_obs_vol
    r = returns.dropna()
    if len(r) < max(min_obs, 2):
        return None
    total = _twr_total(r)
    if total is None:
        return None
    days = (r.index[-1] - r.index[0]).days
    if days <= 0:
        return None
    years = days / 365.25
    return float((1.0 + total) ** (1.0 / years) - 1.0)


def calmar(returns: pd.Series, min_obs: int | None = None) -> float | None:
    """CAGR / |max drawdown|, both computed over the full ``returns`` history."""
    r = returns.dropna()
    mdd, _ = _max_drawdown(r)
    if not mdd:
        return None
    c = cagr(r, min_obs)
    if c is None:
        return None
    return float(c / abs(mdd))


def var_cvar(
    returns: pd.Series, confidence: float = 0.95, min_obs: int | None = None
) -> tuple[float | None, float | None]:
    s = get_settings()
    min_obs = min_obs if min_obs is not None else s.min_obs_var
    r = returns.dropna()
    if len(r) < min_obs:
        return None, None
    var_q = float(np.quantile(r, 1.0 - confidence))
    tail = r[r <= var_q]
    cvar = float(tail.mean()) if len(tail) else var_q
    return var_q, cvar


def rolling_beta(portfolio: pd.Series, benchmark: pd.Series, window: int) -> pd.Series:
    df = _aligned(portfolio, benchmark)
    if len(df) < window:
        return pd.Series(dtype=float)
    cov = df["a"].rolling(window).cov(df["b"])
    var = df["b"].rolling(window).var()
    return (cov / var).dropna()


def rolling_volatility(returns: pd.Series, window: int) -> pd.Series:
    s = get_settings()
    r = returns.dropna()
    if len(r) < window:
        return pd.Series(dtype=float)
    return (r.rolling(window).std(ddof=1) * np.sqrt(s.trading_days_per_year)).dropna()


def rolling_correlation(
    portfolio: pd.Series, benchmark: pd.Series, window: int
) -> pd.Series:
    df = _aligned(portfolio, benchmark)
    if len(df) < window:
        return pd.Series(dtype=float)
    return df["a"].rolling(window).corr(df["b"]).dropna()


def security_betas(
    ticker_returns: pd.DataFrame, benchmark: pd.Series, min_obs: int | None = None
) -> dict[str, float | None]:
    return {
        t: beta(ticker_returns[t].dropna(), benchmark, min_obs)
        for t in ticker_returns.columns
    }
