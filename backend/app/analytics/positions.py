"""Daily position and cash reconstruction from the append-only ledger.

Rules
-----
* BUY/SELL change shares by ±shares and cash by ``cash_flow``.
* DIVIDEND/DEPOSIT/WITHDRAWAL/FEE change cash by ``cash_flow`` only.
* SPLIT multiplies the position by ``split_ratio`` starting on the split date
  (no cash effect, no economic return).
* SYMBOL_CHANGE moves the whole position from ``ticker`` to ``new_ticker``.
* External flows (used by TWR and benchmark simulation) are DEPOSIT and
  WITHDRAWAL only; everything else is internal to the account.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Transaction, TransactionType


def load_ledger(db: Session, account_ids: list[str]) -> list[Transaction]:
    return list(
        db.execute(
            select(Transaction)
            .where(Transaction.account_id.in_(account_ids))
            .order_by(Transaction.trade_date, Transaction.id)
        ).scalars()
    )


def daily_positions(
    ledger: list[Transaction], calendar: pd.DatetimeIndex
) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """Reconstruct daily state on the given trading calendar.

    Returns
    -------
    shares : DataFrame date × ticker — shares held at the END of each date.
    cash : Series date — cash balance at the end of each date.
    external_flows : Series date — net external cash flow (deposit/withdrawal)
        occurring on each date (0 where none). Flows on non-trading days are
        rolled forward to the next trading day.
    """
    if len(calendar) == 0:
        return pd.DataFrame(), pd.Series(dtype=float), pd.Series(dtype=float)

    by_date: dict[dt.date, list[Transaction]] = defaultdict(list)
    for txn in ledger:
        by_date[txn.trade_date].append(txn)

    cal_dates = [d.date() for d in calendar]

    # Map every ledger date to the calendar slot it settles on (next session).
    def settle_slot(d: dt.date) -> int | None:
        for i, cd in enumerate(cal_dates):
            if cd >= d:
                return i
        return None

    slot_txns: dict[int, list[Transaction]] = defaultdict(list)
    for d, txns in by_date.items():
        slot = settle_slot(d)
        if slot is not None:
            slot_txns[slot].extend(txns)
        # Transactions after the calendar end are ignored for this window.

    holdings: dict[str, float] = defaultdict(float)
    cash = 0.0
    share_rows: list[dict[str, float]] = []
    cash_vals: list[float] = []
    flow_vals: list[float] = []

    for i in range(len(cal_dates)):
        flow = 0.0
        for txn in sorted(slot_txns.get(i, []), key=lambda t: (t.trade_date, t.id)):
            ttype = txn.type
            if ttype == TransactionType.BUY:
                holdings[txn.ticker] += txn.shares or 0.0
                cash += (
                    txn.cash_flow
                    if txn.cash_flow is not None
                    else -((txn.shares or 0.0) * (txn.price or 0.0) + (txn.fees or 0.0))
                )
            elif ttype == TransactionType.SELL:
                holdings[txn.ticker] -= txn.shares or 0.0
                cash += (
                    txn.cash_flow
                    if txn.cash_flow is not None
                    else ((txn.shares or 0.0) * (txn.price or 0.0) - (txn.fees or 0.0))
                )
            elif ttype == TransactionType.DIVIDEND:
                cash += txn.cash_flow or 0.0
            elif ttype == TransactionType.FEE:
                cash += (
                    txn.cash_flow if txn.cash_flow is not None else -(txn.fees or 0.0)
                )
            elif ttype == TransactionType.DEPOSIT:
                cash += txn.cash_flow or 0.0
                flow += txn.cash_flow or 0.0
            elif ttype == TransactionType.WITHDRAWAL:
                amt = txn.cash_flow or 0.0
                cash += amt
                flow += amt
            elif ttype == TransactionType.SPLIT:
                if txn.ticker in holdings and txn.split_ratio:
                    holdings[txn.ticker] *= txn.split_ratio
            elif ttype == TransactionType.SYMBOL_CHANGE:
                if txn.ticker in holdings and txn.new_ticker:
                    holdings[txn.new_ticker] += holdings.pop(txn.ticker)
        share_rows.append({k: v for k, v in holdings.items() if abs(v) > 1e-12})
        cash_vals.append(cash)
        flow_vals.append(flow)

    shares = pd.DataFrame(share_rows, index=calendar).fillna(0.0)
    return (
        shares,
        pd.Series(cash_vals, index=calendar, name="cash"),
        pd.Series(flow_vals, index=calendar, name="external_flow"),
    )


def external_flow_list(ledger: list[Transaction]) -> list[tuple[dt.date, float]]:
    """Dated external flows (deposits positive, withdrawals negative)."""
    flows: list[tuple[dt.date, float]] = []
    for txn in ledger:
        if txn.type in (TransactionType.DEPOSIT, TransactionType.WITHDRAWAL):
            flows.append((txn.trade_date, txn.cash_flow or 0.0))
    return flows
