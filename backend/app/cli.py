"""Operational CLI.

Usage (from backend/):
    python -m app.cli bootstrap   # load seed book + one-time official-open hydration
    python -m app.cli refresh     # incremental market-data refresh
    python -m app.cli status      # bootstrap/refresh status summary
"""

from __future__ import annotations

import logging
import sys

from .bootstrap import hydrate_all
from .database import session_scope
from .fmp_client import FMPClient
from .ingestion import execute_equal_weight_rebalance, refresh_market_data

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")


def cmd_bootstrap() -> int:
    with session_scope() as db:
        results = hydrate_all(db)
    code = 0
    for r in results:
        if r.already_done:
            print(f"{r.account_id}: already hydrated (immutable)")
        elif r.hydrated:
            print(
                f"{r.account_id}: hydrated {r.fills} fills, cost ${r.total_cost:,.2f}, "
                f"residual cash ${r.residual_cash:,.2f}"
            )
        else:
            code = 1
            print(f"{r.account_id}: FAILED — {len(r.errors)} errors")
            for e in r.errors[:20]:
                print(f"  - {e}")
    return code


def cmd_refresh() -> int:
    with session_scope() as db:
        report = refresh_market_data(db, trigger="manual")
    print(
        f"refresh run {report.run_id}: {report.status} — "
        f"{report.symbols_ok}/{report.symbols_total} symbols ok, "
        f"{report.dividends_created} dividends, {report.splits_created} splits"
    )
    for f in report.failures[:20]:
        print(f"  - {f}")
    return 0 if report.status in ("success", "partial") else 1


def cmd_rebalance_5() -> int:
    """One-time swap: PORTFOLIO_5 CIEN/SPGI/ADSK -> ROST/NUE/ABBV, equal-weight."""
    new_composition = [
        ("GOOGL", "Communication Services"),
        ("IBKR", "Financials"),
        ("ROST", "Consumer Discretionary"),
        ("NUE", "Materials"),
        ("ABBV", "Health Care"),
    ]
    with session_scope() as db, FMPClient() as client:
        event = execute_equal_weight_rebalance(
            db,
            client,
            "PORTFOLIO_5",
            new_composition,
            notes="Swapped CIEN, SPGI, ADSK for ROST, NUE, ABBV; rebalanced to equal weight.",
        )
    print(f"rebalance event #{event.id} on {event.event_date}")
    return 0


def cmd_status() -> int:
    from sqlalchemy import func, select

    from .models import BootstrapState, PriceBar, RefreshRun, Transaction

    with session_scope() as db:
        for st in db.execute(select(BootstrapState)).scalars():
            print(f"bootstrap {st.account_id}: {st.hydrated_at} ({st.detail})")
        n_txn = db.execute(select(func.count(Transaction.id))).scalar()
        n_bars = db.execute(select(func.count(PriceBar.id))).scalar()
        print(f"transactions: {n_txn}, price bars: {n_bars}")
        run = (
            db.execute(select(RefreshRun).order_by(RefreshRun.id.desc()))
            .scalars()
            .first()
        )
        if run:
            print(f"last refresh: #{run.id} {run.status} at {run.finished_at}")
    return 0


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    return {
        "bootstrap": cmd_bootstrap,
        "refresh": cmd_refresh,
        "rebalance5": cmd_rebalance_5,
        "status": cmd_status,
    }.get(cmd, cmd_status)()


if __name__ == "__main__":
    raise SystemExit(main())
