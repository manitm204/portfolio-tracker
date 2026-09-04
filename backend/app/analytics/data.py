"""Shared data-access helpers for analytics: price frames and trading calendar.

Market-calendar policy (documented): the trading calendar is the set of dates
for which SPY has a price bar. SPY trades every NYSE session, so this handles
weekends and market holidays without a separate holiday table. Symbols missing
a price on a calendar date are forward-filled from their last known close and
reported as coverage gaps — a missing price is never treated as zero and never
fabricates a return (forward-fill produces a 0% return for that symbol only,
and the gap is surfaced in data-quality reporting).
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import PriceBar


def load_price_frame(
    db: Session,
    tickers: list[str],
    start: dt.date | None = None,
    end: dt.date | None = None,
) -> pd.DataFrame:
    """Long frame of price bars for the tickers: one row per (ticker, date)."""
    if not tickers:
        return pd.DataFrame(
            columns=[
                "ticker",
                "date",
                "open",
                "close",
                "adj_open",
                "adj_close",
                "provisional",
            ]
        )
    q = select(
        PriceBar.ticker,
        PriceBar.date,
        PriceBar.open,
        PriceBar.high,
        PriceBar.low,
        PriceBar.close,
        PriceBar.adj_open,
        PriceBar.adj_close,
        PriceBar.volume,
        PriceBar.provisional,
    ).where(PriceBar.ticker.in_(tickers))
    if start is not None:
        q = q.where(PriceBar.date >= start)
    if end is not None:
        q = q.where(PriceBar.date <= end)
    rows = db.execute(q).all()
    df = pd.DataFrame(
        rows,
        columns=[
            "ticker",
            "date",
            "open",
            "high",
            "low",
            "close",
            "adj_open",
            "adj_close",
            "volume",
            "provisional",
        ],
    )
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def close_matrix(price_frame: pd.DataFrame, field: str = "close") -> pd.DataFrame:
    """Pivot to a date × ticker matrix (no filling)."""
    if price_frame.empty:
        return pd.DataFrame()
    return price_frame.pivot_table(
        index="date", columns="ticker", values=field, aggfunc="last"
    )


def trading_calendar(
    db: Session, start: dt.date, end: dt.date, anchor: str = "SPY"
) -> pd.DatetimeIndex:
    rows = (
        db.execute(
            select(PriceBar.date)
            .where(
                PriceBar.ticker == anchor, PriceBar.date >= start, PriceBar.date <= end
            )
            .order_by(PriceBar.date)
        )
        .scalars()
        .all()
    )
    return pd.DatetimeIndex(pd.to_datetime(rows))


def ffill_with_coverage(
    matrix: pd.DataFrame, calendar: pd.DatetimeIndex
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Reindex onto the calendar and forward-fill.

    Returns (filled_matrix, was_missing) where ``was_missing`` is True where a
    value had to be forward-filled (or is still absent).
    """
    if matrix.empty:
        return matrix, matrix
    aligned = matrix.reindex(calendar)
    missing = aligned.isna()
    return aligned.ffill(), missing
