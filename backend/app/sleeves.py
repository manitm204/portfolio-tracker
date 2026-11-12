"""Sleeve lifecycle: funding an empty sleeve and recording trades in a live one.

Fills default to the official open of the trade date, the convention used for
every sleeve purchase. Both operations only write ledger rows; everything shown
in the app is reconstructed from that ledger.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from .bootstrap import equal_weight_targets, hydrate_account, upsert_target
from .ingestion import SECTOR_MAP, _positions_before, ny_today
from .market_data import MarketDataClient, MarketDataError, provider_name
from .models import (
    Account,
    IndexConstituent,
    ModelTarget,
    Transaction,
    TransactionType,
)

MIN_HOLDINGS = 4
MAX_HOLDINGS = 6


class SleeveError(Exception):
    """A request that can't be applied; the message is safe to show the user."""


def _sleeve(db: Session, account_id: str) -> Account:
    account = db.get(Account, account_id)
    if account is None or account.archived or account.sleeve_number is None:
        raise SleeveError(f"Unknown sleeve '{account_id}'")
    return account


def _resolve_sector(db: Session, ticker: str, given: str | None) -> str:
    if given:
        if given not in SECTOR_MAP:
            raise SleeveError(f"{ticker}: unknown sector '{given}'")
        return SECTOR_MAP[given]
    known = db.execute(
        select(IndexConstituent.sector).where(
            IndexConstituent.ticker == ticker, IndexConstituent.sector != "Unknown"
        )
    ).scalar()
    if known is None:
        raise SleeveError(f"{ticker} isn't in the S&P 500 list; choose its sector")
    return known


def populate_sleeve(
    db: Session,
    client: MarketDataClient,
    account_id: str,
    start_date: dt.date,
    holdings: list[tuple[str, str | None]],
) -> int:
    """Fund an empty sleeve: equal dollars per ticker at ``start_date``'s open.

    All-or-nothing: if any open is missing nothing is kept and the sleeve stays
    empty. Returns the number of fills.
    """
    account = _sleeve(db, account_id)
    if db.execute(
        select(Transaction.id).where(Transaction.account_id == account_id)
    ).first():
        raise SleeveError(f"{account.display_name} is already funded")
    tickers = [t.strip().upper() for t, _ in holdings]
    if len(set(tickers)) != len(tickers):
        raise SleeveError("Each ticker can only appear once")
    if not MIN_HOLDINGS <= len(tickers) <= MAX_HOLDINGS:
        raise SleeveError(f"A sleeve holds {MIN_HOLDINGS}-{MAX_HOLDINGS} stocks")
    if start_date > ny_today():
        raise SleeveError("The purchase date can't be in the future")

    resolved = [
        (ticker, _resolve_sector(db, ticker, sector))
        for ticker, (_, sector) in zip(tickers, holdings)
    ]
    account.start_date = start_date
    equal_weight_targets(db, account, resolved)
    db.flush()
    result = hydrate_account(db, account_id, client)
    if not result.hydrated:
        raise SleeveError("; ".join(result.errors))
    return result.fills


def _official_open(client: MarketDataClient, ticker: str, date: dt.date) -> float:
    try:
        bars = client.historical_eod(ticker, date, date)
    except MarketDataError as err:
        raise SleeveError(f"{ticker}: {err}") from err
    bar = next((b for b in bars if b.get("date") == date.isoformat()), None)
    if bar is None or not bar.get("open"):
        raise SleeveError(f"{ticker}: no opening price for {date} (market closed?)")
    return float(bar["open"])


def record_trade(
    db: Session,
    client: MarketDataClient,
    account_id: str,
    side: str,
    ticker: str,
    trade_date: dt.date,
    price: float | None = None,
    dollars: float | None = None,
    shares: float | None = None,
    sector: str | None = None,
) -> Transaction:
    """Buy with a sleeve's cash, or sell (all shares unless ``shares`` is given)."""
    account = _sleeve(db, account_id)
    ticker = ticker.strip().upper()
    if account.start_date is None:
        raise SleeveError(f"{account.display_name} isn't funded yet")
    if not account.start_date <= trade_date <= ny_today():
        raise SleeveError("The trade date must fall between the sleeve's start and today")

    positions, cash = _positions_before(db, account_id, trade_date + dt.timedelta(days=1))
    held = positions.get(ticker, 0.0)
    fill = price if price is not None else _official_open(client, ticker, trade_date)
    if fill <= 0:
        raise SleeveError("Price must be positive")

    if side == "SELL":
        quantity = shares if shares is not None else held
        if held <= 1e-9:
            raise SleeveError(f"{account.display_name} doesn't hold {ticker}")
        if quantity <= 0 or quantity > held + 1e-9:
            raise SleeveError(f"Can't sell {quantity:g} of {held:g} {ticker} shares")
        txn = Transaction(
            account_id=account_id,
            trade_date=trade_date,
            ticker=ticker,
            type=TransactionType.SELL,
            shares=quantity,
            price=fill,
            cash_flow=quantity * fill,
            source="USER",
            notes=None if price is not None else "Filled at the official open",
        )
        if held - quantity <= 1e-6:
            target = db.execute(
                select(ModelTarget).where(
                    ModelTarget.account_id == account_id, ModelTarget.ticker == ticker
                )
            ).scalar_one_or_none()
            if target is not None:
                target.active = False
                target.deactivated_date = trade_date
    elif side == "BUY":
        if not dollars or dollars <= 0:
            raise SleeveError("Enter the dollars to invest")
        if dollars > cash + 0.005:
            raise SleeveError(f"Only ${cash:,.2f} of cash available in this sleeve")
        open_tickers = {t for t, v in positions.items() if v > 1e-9}
        if ticker not in open_tickers and len(open_tickers) >= MAX_HOLDINGS:
            raise SleeveError(f"A sleeve holds at most {MAX_HOLDINGS} stocks")
        upsert_target(
            db,
            account_id,
            ticker,
            sector=_resolve_sector(db, ticker, sector),
            target_dollars=dollars,
            active=True,
            activated_date=trade_date,
            deactivated_date=None,
        )
        txn = Transaction(
            account_id=account_id,
            trade_date=trade_date,
            ticker=ticker,
            type=TransactionType.BUY,
            shares=dollars / fill,
            price=fill,
            cash_flow=-dollars,
            source="USER",
            notes=None if price is not None else f"Filled at the {provider_name(client)} open",
        )
    else:
        raise SleeveError(f"Unknown side '{side}'")
    db.add(txn)
    db.commit()
    return txn
