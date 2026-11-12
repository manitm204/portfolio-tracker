"""Incremental, idempotent market-data ingestion and corporate-action sync.

* Fetches only missing dates per symbol (plus any still-provisional bars).
* Stores raw OHLC and dividend-adjusted fields side by side.
* Adjusted history is re-fetched over the full account window on every refresh
  because adjusted closes change retroactively on new distributions; with
  inception in July 2026 this window is small. Raw bars are immutable.
* Detects dividends and splits for held tickers and materializes DIVIDEND and
  SPLIT ledger rows with unique source keys, so re-running never duplicates.
* Bars fetched during the trading session are marked provisional and are
  re-fetched on the next refresh.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .analytics.performance import price_period_return
from .market_data import (
    MarketDataClient,
    MarketDataError,
    get_market_data_client,
    prefetch,
    provider_name,
)
from .models import (
    Account,
    IndexConstituent,
    ModelTarget,
    PriceBar,
    RebalanceEvent,
    RefreshRun,
    SymbolSyncState,
    Transaction,
    TransactionType,
    utcnow,
)
from .spy_holdings import fetch_spy_holdings

# FMP's sp500-constituent "sector" field uses its own (Morningstar-style)
# taxonomy, not GICS; the Yahoo provider's Wikipedia list is already GICS.
# Normalize both to the vocabulary already used by ModelTarget.sector (the
# seed book) so sector-matched Monte Carlo sampling can compare like with like.
GICS_SECTORS = (
    "Information Technology",
    "Industrials",
    "Financials",
    "Health Care",
    "Consumer Discretionary",
    "Consumer Staples",
    "Utilities",
    "Real Estate",
    "Communication Services",
    "Energy",
    "Materials",
)
SECTOR_MAP = {
    **{s: s for s in GICS_SECTORS},
    "Technology": "Information Technology",
    "Industrials": "Industrials",
    "Financial Services": "Financials",
    "Healthcare": "Health Care",
    "Consumer Cyclical": "Consumer Discretionary",
    "Consumer Defensive": "Consumer Staples",
    "Utilities": "Utilities",
    "Real Estate": "Real Estate",
    "Communication Services": "Communication Services",
    "Energy": "Energy",
    "Basic Materials": "Materials",
}

log = logging.getLogger(__name__)

NY = ZoneInfo("America/New_York")
MARKET_CLOSE = dt.time(16, 15)  # bars fetched before this NY time are provisional

# Single-factor iShares MSCI USA ETFs used as style-factor proxies on the Risk
# page (momentum/value/quality/low-vol/size regressions). Never transacted or
# held, so they never receive corporate-action ledger rows — only their
# adjusted price series is used (see AccountContext.factor_price_returns).
FACTOR_ETFS: dict[str, str] = {
    "MTUM": "Momentum",
    "VLUE": "Value",
    "QUAL": "Quality",
    "USMV": "Low volatility",
    "SIZE": "Size (small-cap)",
}

# Select Sector SPDR ETFs, one per sector in the same vocabulary as
# ModelTarget.sector / SECTOR_MAP above. Used on the Heatmap page as a
# "how did my sector picks do vs. just buying the sector" yardstick — never
# transacted or held, only their adjusted price series is used (see
# AccountContext.sector_etf_closes).
SECTOR_ETFS: dict[str, str] = {
    "Information Technology": "XLK",
    "Industrials": "XLI",
    "Financials": "XLF",
    "Health Care": "XLV",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
    "Energy": "XLE",
    "Materials": "XLB",
}

# Every tracked symbol keeps at least this much history before both today and
# the earliest sleeve start, so risk stats (security beta, factor exposure,
# correlation matrix, PCA — see services._trailing_returns) never depend on how
# long a position has actually been held, and the year BEFORE each purchase
# stays available as the sleeve ages.
TRAILING_LOOKBACK_CALENDAR_DAYS = 400

# A cached series ending within this many days of today counts as current, so
# weekends and market holidays don't force a refetch.
COVERAGE_SLACK_DAYS = 5

# Periods stored per S&P 500 constituent for the index heatmap.
INDEX_PERIODS = ("1D", "1W", "1M", "MTD", "3M", "YTD", "1Y")


def ny_today() -> dt.date:
    return dt.datetime.now(NY).date()


def is_intraday_now() -> bool:
    now = dt.datetime.now(NY)
    return now.time() < MARKET_CLOSE


def live_account_ids(db: Session) -> list[str]:
    return list(
        db.execute(select(Account.id).where(Account.archived.is_(False))).scalars()
    )


def symbol_universe(db: Session) -> list[str]:
    """Every symbol we must track: transacted tickers, active targets, benchmarks, factor ETFs, sector ETFs."""
    tickers: set[str] = set(FACTOR_ETFS) | set(SECTOR_ETFS.values())
    account_ids = live_account_ids(db)
    for (t,) in db.execute(
        select(Transaction.ticker)
        .where(Transaction.ticker.isnot(None), Transaction.account_id.in_(account_ids))
        .distinct()
    ):
        tickers.add(t)
    for (t,) in db.execute(
        select(ModelTarget.ticker)
        .where(ModelTarget.active.is_(True), ModelTarget.account_id.in_(account_ids))
        .distinct()
    ):
        tickers.add(t)
    for acct in db.execute(select(Account).where(Account.archived.is_(False))).scalars():
        tickers.add(acct.benchmark_1)
        tickers.add(acct.benchmark_2)
    return sorted(tickers)


def earliest_needed_date(db: Session) -> dt.date:
    today = ny_today()
    dates = db.execute(
        select(Account.start_date).where(
            Account.archived.is_(False), Account.start_date.isnot(None)
        )
    ).scalars().all()
    first_start = min(dates, default=today)
    return min(first_start, today) - dt.timedelta(days=TRAILING_LOOKBACK_CALENDAR_DAYS)


@dataclass
class RefreshReport:
    run_id: int
    status: str = "running"
    symbols_total: int = 0
    symbols_ok: int = 0
    symbols_failed: int = 0
    failures: list[str] = field(default_factory=list)
    dividends_created: int = 0
    splits_created: int = 0


def refresh_market_data(
    db: Session, trigger: str = "manual", client: MarketDataClient | None = None
) -> RefreshReport:
    run = RefreshRun(trigger=trigger, status="running")
    db.add(run)
    db.commit()

    own_client = client is None
    client = client or get_market_data_client()
    start_date = earliest_needed_date(db)
    today = ny_today()
    symbols = symbol_universe(db)
    report = RefreshReport(run_id=run.id, symbols_total=len(symbols))
    run.provider = provider_name(client)
    db.commit()
    log.info("Refreshing %d symbols via %s", len(symbols), run.provider)

    try:
        prefetch(client, symbols, start_date, today)
        for symbol in symbols:
            state = db.merge(
                db.get(SymbolSyncState, symbol) or SymbolSyncState(ticker=symbol)
            )
            state.last_attempt_at = utcnow()
            db.flush()
            try:
                _sync_symbol_prices(db, client, symbol, state, start_date, today)
                state.status = "ok"
                state.error = None
                state.last_success_at = utcnow()
                report.symbols_ok += 1
            except MarketDataError as err:
                state.status = "error"
                state.error = str(err)
                report.symbols_failed += 1
                report.failures.append(f"{symbol}: {err}")
                log.warning("Refresh failed for %s: %s", symbol, err)
            db.commit()

        # Corporate actions for held (non-benchmark) tickers
        held = _transacted_tickers(db)
        for symbol in held:
            try:
                s, d = _sync_corporate_actions(db, client, symbol, start_date)
                report.splits_created += s
                report.dividends_created += d
            except MarketDataError as err:
                report.failures.append(f"{symbol} corporate actions: {err}")
            db.commit()

        if report.symbols_failed == 0:
            report.status = "success"
        elif report.symbols_ok > 0:
            report.status = "partial"
        else:
            report.status = "error"
    except Exception as err:  # unexpected — record and re-raise
        report.status = "error"
        report.failures.append(f"fatal: {err}")
        raise
    finally:
        run = db.get(RefreshRun, report.run_id)
        run.finished_at = utcnow()
        run.status = report.status
        run.symbols_total = report.symbols_total
        run.symbols_ok = report.symbols_ok
        run.symbols_failed = report.symbols_failed
        run.detail = "; ".join(report.failures[:50]) or None
        db.commit()
        if own_client:
            client.close()
    return report


# ---------------------------------------------------------------------------
def _transacted_tickers(db: Session) -> list[str]:
    return sorted(
        t
        for (t,) in db.execute(
            select(Transaction.ticker)
            .where(
                Transaction.ticker.isnot(None),
                Transaction.account_id.in_(live_account_ids(db)),
                Transaction.type.in_([TransactionType.BUY, TransactionType.SELL]),
            )
            .distinct()
        )
    )


def _sync_symbol_prices(
    db: Session,
    client: MarketDataClient,
    symbol: str,
    state: SymbolSyncState,
    window_start: dt.date,
    today: dt.date,
) -> None:
    # Raw incremental start: day after last success, pulled back to cover any
    # provisional bars that must be finalized.
    fetch_start = window_start
    if state.last_success_date:
        fetch_start = state.last_success_date + dt.timedelta(days=1)
    first_provisional = (
        db.execute(
            select(PriceBar.date)
            .where(PriceBar.ticker == symbol, PriceBar.provisional.is_(True))
            .order_by(PriceBar.date)
        )
        .scalars()
        .first()
    )
    if first_provisional is not None:
        fetch_start = min(fetch_start, first_provisional)
    fetch_start = max(fetch_start, window_start)

    intraday = is_intraday_now()

    if fetch_start <= today:
        raw = client.historical_eod(symbol, fetch_start, today)
        for bar in raw:
            bar_date = dt.date.fromisoformat(bar["date"])
            provisional = intraday and bar_date == today
            _upsert_bar_raw(db, symbol, bar_date, bar, provisional)
        db.flush()  # make new bars visible to the adjusted-pass lookups

    # Adjusted series: always refresh the whole window (retroactive changes).
    adj = client.historical_eod_adjusted(symbol, window_start, today)
    for bar in adj:
        bar_date = dt.date.fromisoformat(bar["date"])
        _upsert_bar_adjusted(db, symbol, bar_date, bar)
    db.flush()

    last_final = (
        db.execute(
            select(PriceBar.date)
            .where(PriceBar.ticker == symbol, PriceBar.provisional.is_(False))
            .order_by(PriceBar.date.desc())
        )
        .scalars()
        .first()
    )
    state.last_success_date = last_final


def _get_bar(db: Session, symbol: str, date: dt.date) -> PriceBar | None:
    return db.execute(
        select(PriceBar).where(PriceBar.ticker == symbol, PriceBar.date == date)
    ).scalar_one_or_none()


def _upsert_bar_raw(
    db: Session, symbol: str, date: dt.date, bar: dict, provisional: bool
) -> None:
    row = _get_bar(db, symbol, date)
    if row is None:
        row = PriceBar(ticker=symbol, date=date)
        db.add(row)
    row.open = bar.get("open")
    row.high = bar.get("high")
    row.low = bar.get("low")
    row.close = bar.get("close")
    row.volume = bar.get("volume")
    row.provisional = provisional
    row.fetched_at = utcnow()


def _upsert_bar_adjusted(db: Session, symbol: str, date: dt.date, bar: dict) -> None:
    row = _get_bar(db, symbol, date)
    if row is None:
        # Adjusted-only row (raw fetch may have failed); keep fields we have.
        row = PriceBar(ticker=symbol, date=date, provisional=False)
        db.add(row)
    row.adj_open = bar.get("adjOpen")
    row.adj_close = bar.get("adjClose")
    if row.close is None:
        row.close = bar.get("adjClose")
    if row.open is None:
        row.open = bar.get("adjOpen")


# ---------------------------------------------------------------------------
# Monte Carlo support: on-demand price backfill for tickers the account never
# transacted (random SPY picks), and a cached S&P 500 membership list.
# ---------------------------------------------------------------------------
def ensure_adjusted_history(
    db: Session, client: MarketDataClient, symbols: list[str], start: dt.date, end: dt.date
) -> list[str]:
    """Backfill adjusted price history for symbols not already covered.

    Cheaper than the full raw+adjusted refresh in ``_sync_symbol_prices``:
    the Monte Carlo comparison only ever reads ``adj_close``. Returns symbols
    that failed to fetch (caller decides whether that's fatal).
    """
    failed: list[str] = []
    missing = [s for s in symbols if not _adjusted_covers(db, s, start, end)]
    prefetch(client, missing, start, end)
    for symbol in missing:
        try:
            adj = client.historical_eod_adjusted(symbol, start, end)
            for bar in adj:
                bar_date = dt.date.fromisoformat(bar["date"])
                _upsert_bar_adjusted(db, symbol, bar_date, bar)
            db.commit()
        except MarketDataError:
            db.rollback()
            failed.append(symbol)
    return failed


def _adjusted_covers(db: Session, symbol: str, start: dt.date, end: dt.date) -> bool:
    # Must check the EARLIEST cached bar, not just "any bar near start":
    # a ticker fetched for a different (later) account inception window
    # can have real data starting after ``start``, which would otherwise
    # look "covered" and silently leave an early-date gap. The LATEST bar
    # matters the same way: these symbols aren't refreshed daily, so a cache
    # ending before a sleeve's start would fail every simulation using it.
    earliest, latest = db.execute(
        select(func.min(PriceBar.date), func.max(PriceBar.date)).where(
            PriceBar.ticker == symbol, PriceBar.adj_close.isnot(None)
        )
    ).one()
    return (
        earliest is not None
        and earliest <= start + dt.timedelta(days=1)
        and latest >= end - dt.timedelta(days=COVERAGE_SLACK_DAYS)
    )


def ensure_sp500_constituents(
    db: Session, client: MarketDataClient, max_age_days: int = 30
) -> list[str]:
    """Cached S&P 500 membership, refreshed from the provider when stale or empty."""
    latest = db.execute(
        select(func.max(IndexConstituent.fetched_at)).where(
            IndexConstituent.index_name == "sp500"
        )
    ).scalar()
    if latest is not None and latest.tzinfo is None:
        # SQLite drops tzinfo on round-trip; utcnow() always writes UTC.
        latest = latest.replace(tzinfo=dt.timezone.utc)
    missing_sector = db.execute(
        select(IndexConstituent.id)
        .where(IndexConstituent.index_name == "sp500", IndexConstituent.sector.is_(None))
        .limit(1)
    ).first()
    stale = (
        latest is None
        or (utcnow() - latest) > dt.timedelta(days=max_age_days)
        or missing_sector is not None
    )
    if stale:
        rows = client.index_constituents("sp500")
        # One spelling for share classes (BRK-B), whatever the source uses.
        by_symbol = {
            r["symbol"].replace(".", "-"): r for r in rows if r.get("symbol")
        }
        if by_symbol:
            # Update in place: rows also carry the heatmap snapshot.
            db.execute(
                delete(IndexConstituent).where(
                    IndexConstituent.index_name == "sp500",
                    IndexConstituent.ticker.notin_(list(by_symbol)),
                )
            )
            existing = _index_rows(db)
            now = utcnow()
            for sym, r in sorted(by_symbol.items()):
                row = existing.get(sym)
                if row is None:
                    row = IndexConstituent(index_name="sp500", ticker=sym)
                    db.add(row)
                row.sector = SECTOR_MAP.get(r.get("sector", ""))
                row.fetched_at = now
            db.commit()
    return sorted(
        t
        for (t,) in db.execute(
            select(IndexConstituent.ticker)
            .where(IndexConstituent.index_name == "sp500")
            .distinct()
        )
    )


def _index_rows(db: Session) -> dict[str, IndexConstituent]:
    return {
        r.ticker: r
        for r in db.execute(
            select(IndexConstituent).where(IndexConstituent.index_name == "sp500")
        ).scalars()
    }


def refresh_index_snapshot(db: Session, client: MarketDataClient) -> dict:
    """Refresh the S&P 500 heatmap: fund weights plus per-period returns.

    Stores a few numbers per constituent rather than ~500 full price
    histories. Weight and sector failures keep the last good values; the
    heatmap reports the snapshot's as-of date so staleness stays visible.
    """
    try:
        ensure_sp500_constituents(db, client)
    except MarketDataError as err:
        db.rollback()
        log.warning("S&P 500 sector refresh failed: %s", err)

    rows = _index_rows(db)
    weights_ok = True
    try:
        holdings = fetch_spy_holdings()
    except MarketDataError as err:
        log.warning("SPY holdings fetch failed: %s", err)
        weights_ok = False
    else:
        held = {h["ticker"] for h in holdings}
        for ticker, row in rows.items():
            if ticker not in held:
                row.weight = None
        for h in holdings:
            row = rows.get(h["ticker"])
            if row is None:
                row = IndexConstituent(
                    index_name="sp500", ticker=h["ticker"], sector="Unknown"
                )
                db.add(row)
                rows[h["ticker"]] = row
            row.name = h["name"]
            row.weight = h["weight"]
        db.commit()

    tickers = sorted(t for t, r in rows.items() if r.weight is not None) or sorted(rows)
    today = ny_today()
    start = today - dt.timedelta(days=TRAILING_LOOKBACK_CALENDAR_DAYS)
    prefetch(client, tickers, start, today)
    updated = 0
    failed: list[str] = []
    for ticker in tickers:
        try:
            bars = client.historical_eod_adjusted(ticker, start, today)
        except MarketDataError:
            failed.append(ticker)
            continue
        closes = pd.Series(
            {pd.Timestamp(b["date"]): b.get("adjClose") for b in bars}, dtype=float
        ).sort_index().dropna()
        if len(closes) < 2:
            failed.append(ticker)
            continue
        rows[ticker].period_returns = json.dumps(
            {
                p: price_period_return(closes, p, closes.index[-1])
                for p in INDEX_PERIODS
            }
        )
        rows[ticker].returns_as_of = closes.index[-1].date()
        updated += 1
    db.commit()
    log.info("Index snapshot: %d updated, %d failed", updated, len(failed))
    return {"updated": updated, "failed": failed, "weights_ok": weights_ok}


# ---------------------------------------------------------------------------
def _shares_held_before(
    db: Session, account_id: str, ticker: str, date: dt.date
) -> float:
    """Shares held at the close of the day before ``date`` (record holder at ex-date)."""
    txns = (
        db.execute(
            select(Transaction)
            .where(
                Transaction.account_id == account_id,
                Transaction.trade_date < date,
                Transaction.ticker.isnot(None),
            )
            .order_by(Transaction.trade_date, Transaction.id)
        )
        .scalars()
        .all()
    )
    shares: dict[str, float] = {}
    for t in txns:
        if t.type == TransactionType.BUY:
            shares[t.ticker] = shares.get(t.ticker, 0.0) + (t.shares or 0.0)
        elif t.type == TransactionType.SELL:
            shares[t.ticker] = shares.get(t.ticker, 0.0) - (t.shares or 0.0)
        elif t.type == TransactionType.SPLIT and t.split_ratio:
            if t.ticker in shares:
                shares[t.ticker] *= t.split_ratio
        elif t.type == TransactionType.SYMBOL_CHANGE and t.new_ticker:
            if t.ticker in shares:
                shares[t.new_ticker] = shares.get(t.new_ticker, 0.0) + shares.pop(
                    t.ticker
                )
    return shares.get(ticker, 0.0)


def _sync_corporate_actions(
    db: Session, client: MarketDataClient, symbol: str, window_start: dt.date
) -> tuple[int, int]:
    """Materialize SPLIT then DIVIDEND ledger rows for every account holding
    the symbol. Returns (splits_created, dividends_created)."""
    account_ids = live_account_ids(db)
    splits_created = dividends_created = 0
    source = f"{provider_name(client).upper()}_CORPORATE_ACTIONS"

    today = ny_today()
    for split in client.splits(symbol):
        s_date = _parse_date(split.get("date"))
        # Skip announced-but-not-yet-effective splits: positions may change
        # before the effective date.
        if s_date is None or s_date < window_start or s_date > today:
            continue
        num = float(split.get("numerator") or 0)
        den = float(split.get("denominator") or 0)
        if num <= 0 or den <= 0:
            continue
        ratio = num / den
        for account_id in account_ids:
            held = _shares_held_before(db, account_id, symbol, s_date)
            if held <= 0:
                continue
            key = f"split:{account_id}:{symbol}:{s_date.isoformat()}"
            if _txn_exists(db, key):
                continue
            db.add(
                Transaction(
                    account_id=account_id,
                    trade_date=s_date,
                    ticker=symbol,
                    type=TransactionType.SPLIT,
                    split_ratio=ratio,
                    source=source,
                    source_key=key,
                    notes=f"{num:g}-for-{den:g} split",
                )
            )
            splits_created += 1
    db.flush()

    for div in client.dividends(symbol):
        ex_date = _parse_date(div.get("date"))
        # Only ex-dates that have occurred; declared future dividends are not
        # yet earned by the holder.
        if ex_date is None or ex_date < window_start or ex_date > today:
            continue
        amount = float(div.get("dividend") or 0)
        if amount <= 0:
            continue
        pay_date = _parse_date(div.get("paymentDate")) or ex_date
        if pay_date > ny_today():
            pay_date = ex_date  # accrue on ex-date until payment date arrives
        for account_id in account_ids:
            held = _shares_held_before(db, account_id, symbol, ex_date)
            if held <= 0:
                continue
            key = f"div:{account_id}:{symbol}:{ex_date.isoformat()}"
            if _txn_exists(db, key):
                continue
            db.add(
                Transaction(
                    account_id=account_id,
                    trade_date=pay_date,
                    ticker=symbol,
                    type=TransactionType.DIVIDEND,
                    shares=held,
                    price=amount,
                    cash_flow=held * amount,
                    source=source,
                    source_key=key,
                    notes=f"${amount:g}/share, ex {ex_date.isoformat()}",
                )
            )
            dividends_created += 1
    return splits_created, dividends_created


def _txn_exists(db: Session, source_key: str) -> bool:
    return (
        db.execute(
            select(Transaction.id).where(Transaction.source_key == source_key)
        ).first()
        is not None
    )


def _parse_date(value) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Composition changes ("rebalance"): swap some holdings for others while
# preserving the continuous transaction ledger everything else derives from.
# ---------------------------------------------------------------------------
def _positions_before(
    db: Session, account_id: str, date: dt.date
) -> tuple[dict[str, float], float]:
    """Shares per ticker and cash balance from the ledger, strictly before
    ``date`` (i.e. the starting position for an event dated ``date``)."""
    txns = (
        db.execute(
            select(Transaction)
            .where(Transaction.account_id == account_id, Transaction.trade_date < date)
            .order_by(Transaction.trade_date, Transaction.id)
        )
        .scalars()
        .all()
    )
    shares: dict[str, float] = {}
    cash = 0.0
    for t in txns:
        if t.cash_flow:
            cash += t.cash_flow
        if t.ticker is None:
            continue
        if t.type == TransactionType.BUY:
            shares[t.ticker] = shares.get(t.ticker, 0.0) + (t.shares or 0.0)
        elif t.type == TransactionType.SELL:
            shares[t.ticker] = shares.get(t.ticker, 0.0) - (t.shares or 0.0)
        elif t.type == TransactionType.SPLIT and t.split_ratio:
            if t.ticker in shares:
                shares[t.ticker] *= t.split_ratio
        elif t.type == TransactionType.SYMBOL_CHANGE and t.new_ticker:
            if t.ticker in shares:
                shares[t.new_ticker] = shares.get(t.new_ticker, 0.0) + shares.pop(
                    t.ticker
                )
    return shares, cash


def _weights_by_value(values: dict[str, float]) -> dict[str, float]:
    total = sum(values.values())
    if total <= 0:
        return {t: 0.0 for t in values}
    return {t: v / total for t, v in values.items()}


def _sector_alloc(values: dict[str, float], sectors: dict[str, str]) -> list[dict]:
    weights = _weights_by_value(values)
    by_sector: dict[str, float] = {}
    for t, w in weights.items():
        s = sectors.get(t, "Unknown")
        by_sector[s] = by_sector.get(s, 0.0) + w
    return [
        {"sector": s, "weight": round(w, 6)}
        for s, w in sorted(by_sector.items(), key=lambda kv: -kv[1])
    ]


def execute_equal_weight_rebalance(
    db: Session,
    client: MarketDataClient,
    account_id: str,
    new_composition: list[tuple[str, str]],
    event_date: dt.date | None = None,
    notes: str = "",
) -> RebalanceEvent:
    """Rebalance ``account_id`` to an equal-weight book of ``new_composition``
    (list of ``(ticker, sector)``), executed at ``event_date``'s official
    opening price for every ticker touched.

    Sells whatever isn't in the new composition, trims/tops-up continuing
    holdings, and buys new names — all self-funded from proceeds + existing
    cash. Writes one ledger transaction per adjustment (never mutates
    existing rows), updates ``model_targets`` effective dating, and records a
    ``RebalanceEvent`` snapshot. All-or-nothing: raises before writing
    anything if any required official open is unavailable.
    """
    event_date = event_date or ny_today()
    shares_before, cash_before = _positions_before(db, account_id, event_date)
    held_before = {t: s for t, s in shares_before.items() if s > 1e-9}

    current_targets = {
        t.ticker: t
        for t in db.execute(
            select(ModelTarget).where(
                ModelTarget.account_id == account_id, ModelTarget.active.is_(True)
            )
        ).scalars()
    }
    sectors_before = {t: row.sector for t, row in current_targets.items()}

    new_tickers = [t for t, _ in new_composition]
    sector_by_new_ticker = dict(new_composition)
    needed = sorted(set(held_before) | set(new_tickers))

    opens: dict[str, float] = {}
    errors: list[str] = []
    for ticker in needed:
        try:
            bars = client.historical_eod(ticker, event_date, event_date)
            bar = next((b for b in bars if b.get("date") == event_date.isoformat()), None)
            if bar is None or bar.get("open") in (None, 0):
                errors.append(f"{ticker}: no official open for {event_date}")
                continue
            opens[ticker] = float(bar["open"])
            row = _get_bar(db, ticker, event_date)
            if row is None:
                _upsert_bar_raw(db, ticker, event_date, bar, provisional=False)
        except MarketDataError as err:
            errors.append(f"{ticker}: {err}")
    if errors:
        db.rollback()
        raise ValueError("Rebalance aborted, missing official opens: " + "; ".join(errors))
    db.flush()

    values_before = {t: s * opens[t] for t, s in held_before.items()}
    total_value = sum(values_before.values()) + cash_before
    n = len(new_composition)
    target_value_each = total_value / n

    def _txn(ticker: str, ttype: TransactionType, shares: float, price: float, action: str) -> None:
        cash_flow = -shares * price if ttype == TransactionType.BUY else shares * price
        db.add(
            Transaction(
                account_id=account_id,
                trade_date=event_date,
                ticker=ticker,
                type=ttype,
                shares=shares,
                price=price,
                fees=0.0,
                cash_flow=cash_flow,
                source="REBALANCE",
                source_key=f"rebalance:{account_id}:{event_date.isoformat()}:{ticker}:{action}",
                notes=notes,
            )
        )

    new_ticker_set = set(new_tickers)
    for ticker, shares in held_before.items():
        if ticker not in new_ticker_set:
            _txn(ticker, TransactionType.SELL, shares, opens[ticker], "exit")

    after_shares: dict[str, float] = {}
    for ticker in new_tickers:
        price = opens[ticker]
        target_shares = target_value_each / price
        cur = held_before.get(ticker, 0.0)
        delta = target_shares - cur
        if delta > 1e-9:
            _txn(ticker, TransactionType.BUY, delta, price, "topup")
        elif delta < -1e-9:
            _txn(ticker, TransactionType.SELL, -delta, price, "trim")
        after_shares[ticker] = target_shares

    for ticker, row in current_targets.items():
        if ticker not in new_ticker_set:
            row.active = False
            row.deactivated_date = event_date
    for ticker in new_tickers:
        row = current_targets.get(ticker)
        if row is not None:
            row.active = True
            row.target_weight_pct = 100.0 / n
        else:
            db.add(
                ModelTarget(
                    account_id=account_id,
                    ticker=ticker,
                    sector=sector_by_new_ticker[ticker],
                    composite_score=None,
                    target_weight_pct=100.0 / n,
                    target_dollars=round(target_value_each, 2),
                    active=True,
                    activated_date=event_date,
                )
            )

    values_after = {t: s * opens[t] for t, s in after_shares.items()}
    total_positions_after = sum(values_after.values())
    total_positions_before = sum(values_before.values())

    def _holdings_rows(values: dict[str, float], shares: dict[str, float], sectors: dict[str, str]) -> list[dict]:
        weights = _weights_by_value(values)
        return [
            {
                "ticker": t,
                "sector": sectors.get(t, "Unknown"),
                "shares": round(shares[t], 6),
                "value": round(v, 2),
                "weight": round(weights.get(t, 0.0), 6),
            }
            for t, v in sorted(values.items(), key=lambda kv: -kv[1])
        ]

    before_snapshot = {
        "holdings": _holdings_rows(values_before, held_before, sectors_before),
        "sector_allocation": _sector_alloc(values_before, sectors_before),
        "cash": round(cash_before, 2),
        "total_value": round(total_positions_before + cash_before, 2),
    }
    after_snapshot = {
        "holdings": _holdings_rows(values_after, after_shares, sector_by_new_ticker),
        "sector_allocation": _sector_alloc(values_after, sector_by_new_ticker),
        "cash": round(total_value - total_positions_after, 2),
        "total_value": round(total_value, 2),
    }

    event = RebalanceEvent(
        account_id=account_id,
        event_date=event_date,
        notes=notes,
        before_snapshot=json.dumps(before_snapshot),
        after_snapshot=json.dumps(after_snapshot),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def history_events(db: Session, account_ids: list[str]) -> list[dict]:
    rows = (
        db.execute(
            select(RebalanceEvent)
            .where(RebalanceEvent.account_id.in_(account_ids))
            .order_by(RebalanceEvent.event_date.desc(), RebalanceEvent.id.desc())
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": r.id,
            "account_id": r.account_id,
            "event_date": r.event_date.isoformat(),
            "notes": r.notes,
            "before": json.loads(r.before_snapshot),
            "after": json.loads(r.after_snapshot),
        }
        for r in rows
    ]
