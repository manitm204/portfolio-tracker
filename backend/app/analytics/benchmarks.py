"""Cash-flow-matched SPY/QQQ benchmark simulation.

Every EXTERNAL cash flow of the account (deposits and withdrawals, including
each account's inception funding) is invested into the benchmark on the same
date. Purchases execute at the benchmark's ADJUSTED open of that date
(adj_open = raw open scaled by adj_close/close), and the position is valued at
the adjusted close — so benchmark distributions are reinvested consistently
with the adjusted-price methodology. For the inception date this is the same
session's opening price, matching the account's own official-open fills.

The combined benchmark simply receives both accounts' flows on their own
inception dates, so differing inception dates are respected by construction.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from .performance import daily_twr_returns


def simulate_benchmark(
    flows: list[tuple[dt.date, float]],
    bars: pd.DataFrame,
    calendar: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Simulate investing the dated external flows into one benchmark symbol.

    Parameters
    ----------
    flows : (date, amount) external flows; deposits positive.
    bars : price frame for the benchmark with columns date/open/close/adj_close
        (rows only for the benchmark ticker).
    calendar : trading calendar to evaluate on.

    Returns
    -------
    DataFrame indexed by calendar with columns:
      value  — market value of the simulated benchmark account
      flow   — external flow applied that day
      units  — cumulative adjusted units held
    """
    if bars.empty or len(calendar) == 0:
        return pd.DataFrame(columns=["value", "flow", "units"])

    b = bars.copy()
    b["date"] = pd.to_datetime(b["date"])
    b = b.set_index("date").sort_index()
    # Adjusted open: scale raw open by the day's adjustment factor.
    factor = b["adj_close"] / b["close"]
    b["eff_adj_open"] = np.where(
        b["adj_open"].notna(), b["adj_open"], b["open"] * factor
    )
    b = b[["eff_adj_open", "adj_close"]].astype(float).reindex(calendar).ffill()

    flow_series = pd.Series(0.0, index=calendar)
    for d, amount in flows:
        ts = pd.Timestamp(d)
        slot = calendar[calendar >= ts]
        if len(slot) == 0:
            continue  # flow after calendar end — not in this window
        flow_series[slot[0]] += amount

    units = 0.0
    values, unit_list = [], []
    for ts in calendar:
        f = flow_series[ts]
        if f != 0.0:
            entry = b.at[ts, "eff_adj_open"]
            if pd.isna(entry) or entry <= 0:
                entry = b.at[ts, "adj_close"]
            if pd.notna(entry) and entry > 0:
                units += f / float(entry)
        adj_close = b.at[ts, "adj_close"]
        values.append(units * float(adj_close) if pd.notna(adj_close) else np.nan)
        unit_list.append(units)

    out = pd.DataFrame(
        {"value": values, "flow": flow_series, "units": unit_list}, index=calendar
    )
    out["value"] = out["value"].ffill()
    return out


def benchmark_daily_returns(sim: pd.DataFrame) -> pd.Series:
    """TWR daily returns of the simulated benchmark (start-of-day flows)."""
    if sim.empty:
        return pd.Series(dtype=float)
    return daily_twr_returns(sim["value"], sim["flow"])


def benchmark_price_returns(
    bars: pd.DataFrame, calendar: pd.DatetimeIndex
) -> pd.Series:
    """Plain adjusted-close daily returns of the benchmark (for beta/correlation)."""
    if bars.empty:
        return pd.Series(dtype=float)
    b = bars.copy()
    b["date"] = pd.to_datetime(b["date"])
    ser = b.set_index("date").sort_index()["adj_close"].reindex(calendar).ffill()
    return ser.pct_change().dropna()
