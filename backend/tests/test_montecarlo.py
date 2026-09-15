from __future__ import annotations

import numpy as np
import pandas as pd

from app.analytics import montecarlo as mc


def test_equal_weight_growth_of_100_averages_normalized_paths():
    dates = pd.date_range("2026-07-24", periods=3, freq="D")
    adj = pd.DataFrame(
        {
            "AAA": [10.0, 11.0, 12.0],  # +10%, +20% cum
            "BBB": [50.0, 45.0, 55.0],  # -10%, +10% cum
        },
        index=dates,
    )
    curve = mc.equal_weight_growth_of_100(adj, ["AAA", "BBB"])
    assert curve.iloc[0] == 100.0
    # day 2: 50*1.1 + 50*0.9 = 100
    assert round(curve.iloc[1], 4) == 100.0
    # day 3: 50*1.2 + 50*1.1 = 115
    assert round(curve.iloc[2], 4) == 115.0


def test_equal_weight_growth_of_100_missing_ticker_returns_empty():
    dates = pd.date_range("2026-07-24", periods=2, freq="D")
    adj = pd.DataFrame({"AAA": [10.0, 11.0]}, index=dates)
    assert mc.equal_weight_growth_of_100(adj, ["AAA", "ZZZ"]).empty


def test_sample_universe_draws_distinct_tickers_per_pick():
    rng = np.random.default_rng(42)
    universe = [f"T{i}" for i in range(20)]
    picks = mc.sample_universe(universe, n=5, sims=10, rng=rng)
    assert len(picks) == 10
    for pick in picks:
        assert len(pick) == 5
        assert len(set(pick)) == 5


def test_summarize_mean_and_median_across_curves():
    dates = pd.date_range("2026-07-24", periods=2, freq="D")
    c1 = pd.Series([100.0, 110.0], index=dates)
    c2 = pd.Series([100.0, 90.0], index=dates)
    out = mc.summarize([c1, c2], dates)
    assert list(out["mean"]) == [100.0, 100.0]
    assert list(out["median"]) == [100.0, 100.0]
