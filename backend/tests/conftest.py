from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import database
from app.models import Account, Base, PriceBar, Transaction, TransactionType


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    # Point the app-wide holder at this test engine too (for code that uses
    # session_scope / get_session_factory).
    database._holder.engine = eng
    database._holder.factory = sessionmaker(
        bind=eng, autoflush=False, expire_on_commit=False
    )
    yield eng
    eng.dispose()


@pytest.fixture()
def db(engine) -> Session:
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    yield session
    session.close()


# ---------------------------------------------------------------------------
# Deterministic fixture data
# ---------------------------------------------------------------------------
D0 = dt.date(2026, 7, 24)  # Friday
D1 = dt.date(2026, 7, 27)  # Monday
D2 = dt.date(2026, 7, 28)
D3 = dt.date(2026, 7, 29)
TRADING_DAYS = [D0, D1, D2, D3]


def add_bars(
    db: Session,
    ticker: str,
    closes: dict[dt.date, float],
    opens: dict[dt.date, float] | None = None,
    adj: dict[dt.date, float] | None = None,
) -> None:
    for date, close in closes.items():
        db.add(
            PriceBar(
                ticker=ticker,
                date=date,
                open=(opens or {}).get(date, close),
                close=close,
                adj_close=(adj or {}).get(date, close),
                provisional=False,
            )
        )


def make_account(
    db: Session, account_id: str = "ACC", start: dt.date = D0, cash: float = 1000.0
) -> Account:
    acct = Account(
        id=account_id,
        display_name=account_id,
        start_date=start,
        starting_cash=cash,
        benchmark_1="SPY",
        benchmark_2="QQQ",
    )
    db.add(acct)
    return acct


def deposit(
    db: Session, account_id: str, date: dt.date, amount: float, key: str | None = None
) -> None:
    db.add(
        Transaction(
            account_id=account_id,
            trade_date=date,
            type=TransactionType.DEPOSIT,
            cash_flow=amount,
            source="TEST",
            source_key=key,
        )
    )


def buy(
    db: Session,
    account_id: str,
    date: dt.date,
    ticker: str,
    shares: float,
    price: float,
    fees: float = 0.0,
    key: str | None = None,
) -> None:
    db.add(
        Transaction(
            account_id=account_id,
            trade_date=date,
            ticker=ticker,
            type=TransactionType.BUY,
            shares=shares,
            price=price,
            fees=fees,
            cash_flow=-(shares * price + fees),
            source="TEST",
            source_key=key,
        )
    )


def sell(
    db: Session,
    account_id: str,
    date: dt.date,
    ticker: str,
    shares: float,
    price: float,
    fees: float = 0.0,
) -> None:
    db.add(
        Transaction(
            account_id=account_id,
            trade_date=date,
            ticker=ticker,
            type=TransactionType.SELL,
            shares=shares,
            price=price,
            fees=fees,
            cash_flow=shares * price - fees,
            source="TEST",
        )
    )


@pytest.fixture()
def spy_qqq(db):
    """Benchmark bars over the four fixture trading days."""
    add_bars(
        db,
        "SPY",
        {D0: 500.0, D1: 505.0, D2: 500.0, D3: 510.0},
        opens={D0: 498.0, D1: 502.0, D2: 503.0, D3: 501.0},
    )
    add_bars(
        db,
        "QQQ",
        {D0: 400.0, D1: 402.0, D2: 399.0, D3: 404.0},
        opens={D0: 399.0, D1: 401.0, D2: 401.0, D3: 400.0},
    )
    db.commit()
