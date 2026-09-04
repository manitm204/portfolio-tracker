"""SQLAlchemy ORM models.

Design notes
------------
* ``transactions`` is an append-only ledger. Rows are never mutated by the
  application; corrections are new rows (type REVERSAL is not needed — a
  correcting SELL/BUY or an explicit user edit through import is a new row).
* ``price_bars`` stores BOTH raw OHLC and dividend/split-adjusted fields so
  raw fill prices and adjusted return series never get mixed silently.
* Numeric money/share columns use Float; SQLite has no fixed decimal type and
  all finance math happens in float64 pandas anyway. Share quantities for the
  five-stock account keep full float precision (>= 6 decimals guaranteed by
  construction).
"""

from __future__ import annotations

import datetime as dt
import enum

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class TransactionType(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"
    DIVIDEND = "DIVIDEND"
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    FEE = "FEE"
    SPLIT = "SPLIT"
    SYMBOL_CHANGE = "SYMBOL_CHANGE"


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(128))
    start_date: Mapped[dt.date] = mapped_column(Date)
    starting_cash: Mapped[float] = mapped_column(Float)
    benchmark_1: Mapped[str] = mapped_column(String(16), default="SPY")
    benchmark_2: Mapped[str] = mapped_column(String(16), default="QQQ")


class ModelTarget(Base):
    """Original model metadata from the seed book (immutable reference data)."""

    __tablename__ = "model_targets"
    __table_args__ = (UniqueConstraint("account_id", "ticker", name="uq_target"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"))
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    sector: Mapped[str] = mapped_column(String(64))
    composite_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_weight_pct: Mapped[float] = mapped_column(Float, default=0.0)
    target_dollars: Mapped[float] = mapped_column(Float, default=0.0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Effective dating for composition history. Null activated_date means
    # "since account inception" (the original seed book).
    activated_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    deactivated_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)


class RebalanceEvent(Base):
    """One composition-change event for an account (e.g. swapping holdings).

    Snapshots are captured at execution time rather than recomputed later so
    the recorded sector allocation reflects the actual decision even if
    prices or sector mappings drift afterward.
    """

    __tablename__ = "rebalance_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True)
    event_date: Mapped[dt.date] = mapped_column(Date, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON-encoded: {"holdings": [{ticker, sector, shares, value, weight}, ...],
    #                "sector_allocation": [{sector, weight}, ...], "cash": float}
    before_snapshot: Mapped[str] = mapped_column(Text)
    after_snapshot: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        # Idempotency key for machine-generated rows (bootstrap, dividends, splits)
        UniqueConstraint("source_key", name="uq_txn_source_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True)
    trade_date: Mapped[dt.date] = mapped_column(Date, index=True)
    ticker: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    type: Mapped[TransactionType] = mapped_column(Enum(TransactionType), index=True)
    shares: Mapped[float | None] = mapped_column(Float, nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    fees: Mapped[float] = mapped_column(Float, default=0.0)
    # Signed cash movement for the account (negative = cash out, e.g. a BUY).
    cash_flow: Mapped[float | None] = mapped_column(Float, nullable=True)
    # For SPLIT rows: split ratio numerator/denominator e.g. 2-for-1 => 2.0
    split_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    # For SYMBOL_CHANGE rows: new ticker
    new_ticker: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source: Mapped[str] = mapped_column(String(64), default="USER")
    source_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class PriceBar(Base):
    __tablename__ = "price_bars"
    __table_args__ = (UniqueConstraint("ticker", "date", name="uq_price_bar"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    open: Mapped[float | None] = mapped_column(Float, nullable=True)
    high: Mapped[float | None] = mapped_column(Float, nullable=True)
    low: Mapped[float | None] = mapped_column(Float, nullable=True)
    close: Mapped[float | None] = mapped_column(Float, nullable=True)
    adj_open: Mapped[float | None] = mapped_column(Float, nullable=True)
    adj_close: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    # True while the bar may still change (fetched intraday before the close).
    provisional: Mapped[bool] = mapped_column(Boolean, default=False)
    fetched_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class OfficialFill(Base):
    """Immutable cache of the official opening prices used for bootstrap fills.

    Fetched exactly once; never recomputed from newer price data.
    """

    __tablename__ = "official_fills"
    __table_args__ = (
        UniqueConstraint("account_id", "ticker", "fill_date", name="uq_fill"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"))
    ticker: Mapped[str] = mapped_column(String(16))
    fill_date: Mapped[dt.date] = mapped_column(Date)
    official_open: Mapped[float] = mapped_column(Float)
    shares: Mapped[float] = mapped_column(Float)
    cost: Mapped[float] = mapped_column(Float)
    fetched_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class SymbolSyncState(Base):
    __tablename__ = "symbol_sync_state"

    ticker: Mapped[str] = mapped_column(String(16), primary_key=True)
    last_success_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    last_attempt_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_success_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), default="ok")  # ok | error | stale
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    corporate_actions_synced_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class RefreshRun(Base):
    __tablename__ = "refresh_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    finished_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    trigger: Mapped[str] = mapped_column(
        String(16), default="manual"
    )  # manual | scheduled
    status: Mapped[str] = mapped_column(String(16), default="running")
    # running | success | partial | error
    symbols_total: Mapped[int] = mapped_column(Integer, default=0)
    symbols_ok: Mapped[int] = mapped_column(Integer, default=0)
    symbols_failed: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class IndexConstituent(Base):
    """Cached membership list for an index (e.g. the S&P 500), used to draw
    random tickers for the Monte Carlo comparison. Refreshed periodically —
    see ``ingestion.ensure_sp500_constituents``."""

    __tablename__ = "index_constituents"
    __table_args__ = (UniqueConstraint("index_name", "ticker", name="uq_index_member"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    index_name: Mapped[str] = mapped_column(String(16), default="sp500")
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    # GICS-style sector, normalized to the same vocabulary as ModelTarget.sector
    # (FMP's own sector field uses a different taxonomy — see ingestion.SECTOR_MAP).
    sector: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fetched_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class MarketCapCache(Base):
    """Cached market capitalization per ticker, used to market-cap-weight the
    125-stock Monte Carlo simulations. Refreshed periodically."""

    __tablename__ = "market_cap_cache"

    ticker: Mapped[str] = mapped_column(String(16), primary_key=True)
    market_cap: Mapped[float] = mapped_column(Float)
    fetched_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class BootstrapState(Base):
    """Tracks one-time hydration completion per account."""

    __tablename__ = "bootstrap_state"

    account_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hydrated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
