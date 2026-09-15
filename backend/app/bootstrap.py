"""One-time seed hydration.

Loads the seed book (accounts + model targets) from ``data/*.csv`` and, once
per account, fetches the official opening price for each purchase date from
FMP, materializes canonical BUY transactions and immutable OfficialFill rows.

Idempotency: hydration is guarded by ``bootstrap_state`` and every generated
transaction carries a unique ``source_key`` so re-running can never duplicate
rows. Official fills are never recomputed from newer price data.
"""

from __future__ import annotations

import csv
import datetime as dt
import logging
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import PROJECT_ROOT
from .fmp_client import FMPClient, FMPError
from .models import (
    Account,
    BootstrapState,
    ModelTarget,
    OfficialFill,
    PriceBar,
    Transaction,
    TransactionType,
)

log = logging.getLogger(__name__)

DATA_DIR = PROJECT_ROOT / "data"


# ---------------------------------------------------------------------------
# Seed book loading (accounts + model targets), idempotent upserts.
# ---------------------------------------------------------------------------
def load_seed_book(db: Session, data_dir: Path = DATA_DIR) -> None:
    _load_accounts(db, data_dir / "accounts.csv")
    _load_targets_5(db, data_dir / "portfolio_5_seed.csv")
    db.commit()


def _load_accounts(db: Session, path: Path) -> None:
    with path.open() as f:
        for row in csv.DictReader(f):
            acct = db.get(Account, row["account_id"])
            if acct is None:
                acct = Account(id=row["account_id"])
                db.add(acct)
            acct.display_name = row["display_name"]
            acct.start_date = dt.date.fromisoformat(row["start_date"])
            acct.starting_cash = float(row["starting_cash"])
            acct.benchmark_1 = row["benchmark_1"]
            acct.benchmark_2 = row["benchmark_2"]


def _upsert_target(db: Session, account_id: str, ticker: str, **fields) -> None:
    existing = db.execute(
        select(ModelTarget).where(
            ModelTarget.account_id == account_id, ModelTarget.ticker == ticker
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(ModelTarget(account_id=account_id, ticker=ticker, **fields))
    else:
        for k, v in fields.items():
            setattr(existing, k, v)


def _load_targets_5(db: Session, path: Path) -> None:
    with path.open() as f:
        for row in csv.DictReader(f):
            dollars = float(row["investment_dollars"])
            _upsert_target(
                db,
                row["account_id"],
                row["ticker"],
                sector=row["sector"],
                composite_score=None,
                target_weight_pct=20.0,
                target_dollars=dollars,
                active=row["active"].strip().lower() == "true",
            )


# ---------------------------------------------------------------------------
# Hydration
# ---------------------------------------------------------------------------
@dataclass
class HydrationResult:
    account_id: str
    hydrated: bool
    already_done: bool = False
    fills: int = 0
    total_cost: float = 0.0
    residual_cash: float = 0.0
    errors: list[str] = field(default_factory=list)


def hydrate_account(
    db: Session, account_id: str, client: FMPClient | None = None
) -> HydrationResult:
    """Fetch official opens and materialize canonical transactions for one account."""
    state = db.get(BootstrapState, account_id)
    if state is not None:
        return HydrationResult(account_id=account_id, hydrated=True, already_done=True)

    account = db.get(Account, account_id)
    if account is None:
        raise ValueError(f"Unknown account {account_id}")

    targets = (
        db.execute(
            select(ModelTarget).where(
                ModelTarget.account_id == account_id, ModelTarget.active.is_(True)
            )
        )
        .scalars()
        .all()
    )
    if not targets:
        raise ValueError(
            f"No active model targets for {account_id}; load the seed book first"
        )

    own_client = client is None
    client = client or FMPClient()
    result = HydrationResult(account_id=account_id, hydrated=False)
    try:
        fill_date = account.start_date
        opens: dict[str, float] = {}
        for t in targets:
            try:
                bars = client.historical_eod(t.ticker, fill_date, fill_date)
                bar = next(
                    (b for b in bars if b.get("date") == fill_date.isoformat()), None
                )
                if bar is None or bar.get("open") in (None, 0):
                    result.errors.append(
                        f"{t.ticker}: no official open for {fill_date}"
                    )
                    continue
                opens[t.ticker] = float(bar["open"])
                _upsert_price_bar(db, t.ticker, fill_date, bar)
            except FMPError as err:
                result.errors.append(f"{t.ticker}: {err}")

        if result.errors:
            # All-or-nothing: a partial book would corrupt cost basis. Surface
            # errors and let the operator retry once data/connectivity is fixed.
            db.rollback()
            return result

        # Pre-compute total cost so the initial deposit can cover the actual
        # fills (each target is an exact-dollar purchase, so this equals
        # starting_cash unless the book was hand-edited).
        planned_cost = sum(t.target_dollars for t in targets)
        deposit_amount = max(account.starting_cash, planned_cost)
        deposit_note = "Initial funding"
        if deposit_amount != account.starting_cash:
            deposit_note = (
                f"Initial funding (planned {account.starting_cash:.2f}, raised to cover "
                f"the seed fills)"
            )
        db.add(
            Transaction(
                account_id=account_id,
                trade_date=fill_date,
                ticker=None,
                type=TransactionType.DEPOSIT,
                cash_flow=deposit_amount,
                source="BOOTSTRAP",
                source_key=f"bootstrap:{account_id}:deposit",
                notes=deposit_note,
            )
        )

        for t in targets:
            open_price = opens[t.ticker]
            # Exact-dollar purchase; shares keep full precision.
            cost = t.target_dollars
            shares = cost / open_price
            db.add(
                Transaction(
                    account_id=account_id,
                    trade_date=fill_date,
                    ticker=t.ticker,
                    type=TransactionType.BUY,
                    shares=shares,
                    price=open_price,
                    fees=0.0,
                    cash_flow=-cost,
                    source="FMP_OFFICIAL_OPEN",
                    source_key=f"bootstrap:{account_id}:{t.ticker}",
                    notes="Hydrated once from official opening price",
                )
            )
            db.add(
                OfficialFill(
                    account_id=account_id,
                    ticker=t.ticker,
                    fill_date=fill_date,
                    official_open=open_price,
                    shares=shares,
                    cost=cost,
                )
            )
            result.fills += 1
            result.total_cost += cost

        result.residual_cash = deposit_amount - result.total_cost
        db.add(
            BootstrapState(
                account_id=account_id,
                detail=(
                    f"fills={result.fills} total_cost={result.total_cost:.2f} "
                    f"residual_cash={result.residual_cash:.2f}"
                ),
            )
        )
        db.commit()
        result.hydrated = True
        log.info(
            "Hydrated %s: %d fills, cost %.2f, residual cash %.2f",
            account_id,
            result.fills,
            result.total_cost,
            result.residual_cash,
        )
        return result
    finally:
        if own_client:
            client.close()


def _upsert_price_bar(db: Session, ticker: str, date: dt.date, bar: dict) -> None:
    existing = db.execute(
        select(PriceBar).where(PriceBar.ticker == ticker, PriceBar.date == date)
    ).scalar_one_or_none()
    if existing is None:
        db.add(
            PriceBar(
                ticker=ticker,
                date=date,
                open=bar.get("open"),
                high=bar.get("high"),
                low=bar.get("low"),
                close=bar.get("close"),
                volume=bar.get("volume"),
            )
        )


def hydrate_all(db: Session, client: FMPClient | None = None) -> list[HydrationResult]:
    load_seed_book(db)
    account_ids = db.execute(select(Account.id)).scalars().all()
    own = client is None
    client = client or FMPClient()
    try:
        return [hydrate_account(db, aid, client) for aid in account_ids]
    finally:
        if own:
            client.close()
