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


def test_sample_sector_matched_respects_per_sector_counts():
    rng = np.random.default_rng(1)
    universe = {
        "Information Technology": [f"IT{i}" for i in range(10)],
        "Financials": [f"FIN{i}" for i in range(10)],
    }
    counts = {"Information Technology": 3, "Financials": 2}
    draws = mc.sample_sector_matched(universe, counts, sims=4, rng=rng)
    assert len(draws) == 4
    for draw in draws:
        assert len(draw["Information Technology"]) == 3
        assert len(draw["Financials"]) == 2
        assert set(draw["Information Technology"]) <= set(universe["Information Technology"])


def test_market_cap_sector_weights_scale_to_sector_target():
    picks = {"Information Technology": ["AAA", "BBB"], "Financials": ["CCC"]}
    caps = {"AAA": 300.0, "BBB": 100.0, "CCC": 50.0}
    targets = {"Information Technology": 0.40, "Financials": 0.10}
    w = mc.market_cap_sector_weights(picks, caps, targets)
    assert round(w["AAA"], 6) == round(0.40 * 0.75, 6)  # 300/400 of the IT sleeve
    assert round(w["BBB"], 6) == round(0.40 * 0.25, 6)
    assert round(w["CCC"], 6) == 0.10
    assert round(w.sum(), 6) == 0.50


def test_cap_weights_redistributes_excess_and_sums_to_one():
    # cap=0.10 is only feasible with >= 10 names; mirrors the 125-stock case.
    others = {f"T{i}": 0.07 for i in range(10)}
    w = pd.Series({"HUGE": 0.30, **others})
    capped = mc.cap_weights(w, cap=0.10)
    assert round(capped.sum(), 6) == 1.0
    assert (capped <= 0.10 + 1e-9).all()
    assert round(capped["HUGE"], 6) == 0.10
    # excess from HUGE redistributes proportionally to the equal-weight rest
    assert round(capped["T0"], 6) == round(capped["T5"], 6) == 0.09


def test_cap_weights_noop_when_already_under_cap():
    w = pd.Series({f"T{i}": 1.0 for i in range(20)})  # 5% each once normalized
    capped = mc.cap_weights(w, cap=0.10)
    assert round(capped.sum(), 6) == 1.0
    assert all(round(v, 6) == 0.05 for v in capped)


def test_weighted_growth_of_100_matches_entry_weights():
    dates = pd.date_range("2026-07-24", periods=2, freq="D")
    adj = pd.DataFrame({"AAA": [10.0, 12.0], "BBB": [50.0, 45.0]}, index=dates)
    weights = pd.Series({"AAA": 0.8, "BBB": 0.2})
    curve = mc.weighted_growth_of_100(adj, weights)
    assert curve.iloc[0] == 100.0
    # day2: 80*1.2 + 20*0.9 = 96 + 18 = 114
    assert round(curve.iloc[1], 4) == 114.0


def test_weighted_growth_of_100_missing_ticker_returns_empty():
    dates = pd.date_range("2026-07-24", periods=2, freq="D")
    adj = pd.DataFrame({"AAA": [10.0, 11.0]}, index=dates)
    weights = pd.Series({"AAA": 0.5, "ZZZ": 0.5})
    assert mc.weighted_growth_of_100(adj, weights).empty


def test_summarize_mean_and_median_across_curves():
    dates = pd.date_range("2026-07-24", periods=2, freq="D")
    c1 = pd.Series([100.0, 110.0], index=dates)
    c2 = pd.Series([100.0, 90.0], index=dates)
    out = mc.summarize([c1, c2], dates)
    assert list(out["mean"]) == [100.0, 100.0]
    assert list(out["median"]) == [100.0, 100.0]
