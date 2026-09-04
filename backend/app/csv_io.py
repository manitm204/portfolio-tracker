"""CSV import/export for the transaction ledger.

Import uses the canonical schema from ``data/transactions.example.csv``:
transaction_id,account_id,trade_date,ticker,transaction_type,shares,price,
fees,cash_flow,source,notes  (+ optional split_ratio,new_ticker)

Rows carry their ``transaction_id`` as the idempotency source key: importing
the same file twice never duplicates rows.
"""

from __future__ import annotations

import csv
import datetime as dt
import io

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Account, Transaction, TransactionType

EXPORT_COLUMNS = [
    "transaction_id",
    "account_id",
    "trade_date",
    "ticker",
    "transaction_type",
    "shares",
    "price",
    "fees",
    "cash_flow",
    "split_ratio",
    "new_ticker",
    "source",
    "notes",
]


class ImportError_(Exception):
    pass


def import_transactions(
    db: Session, content: str, default_account: str | None = None
) -> dict:
    reader = csv.DictReader(io.StringIO(content))
    if reader.fieldnames is None:
        raise ImportError_("Empty CSV")
    required = {"account_id", "trade_date", "transaction_type"}
    missing = required - set(reader.fieldnames)
    if missing and not (
        default_account and required - {"account_id"} <= set(reader.fieldnames)
    ):
        raise ImportError_(f"Missing required columns: {sorted(missing)}")

    known_accounts = {a for (a,) in db.execute(select(Account.id))}
    created = skipped = 0
    errors: list[str] = []
    for i, row in enumerate(reader, start=2):
        try:
            account_id = (row.get("account_id") or default_account or "").strip()
            if account_id not in known_accounts:
                raise ImportError_(f"unknown account '{account_id}'")
            ttype = TransactionType((row.get("transaction_type") or "").strip().upper())
            trade_date = dt.date.fromisoformat(row["trade_date"].strip())
            ticker = (row.get("ticker") or "").strip().upper() or None
            if (
                ttype
                in (
                    TransactionType.BUY,
                    TransactionType.SELL,
                    TransactionType.SPLIT,
                    TransactionType.DIVIDEND,
                    TransactionType.SYMBOL_CHANGE,
                )
                and not ticker
            ):
                raise ImportError_(f"{ttype.value} requires a ticker")

            shares = _num(row.get("shares"))
            price = _num(row.get("price"))
            fees = _num(row.get("fees")) or 0.0
            cash_flow = _num(row.get("cash_flow"))
            split_ratio = _num(row.get("split_ratio"))
            new_ticker = (row.get("new_ticker") or "").strip().upper() or None

            if ttype in (TransactionType.BUY, TransactionType.SELL):
                if shares is None or shares <= 0:
                    raise ImportError_(f"{ttype.value} requires positive shares")
                if cash_flow is None:
                    if price is None:
                        raise ImportError_(f"{ttype.value} requires price or cash_flow")
                    gross = shares * price
                    cash_flow = (
                        -(gross + fees)
                        if ttype == TransactionType.BUY
                        else gross - fees
                    )
            if ttype in (
                TransactionType.DEPOSIT,
                TransactionType.WITHDRAWAL,
                TransactionType.DIVIDEND,
                TransactionType.FEE,
            ):
                if cash_flow is None:
                    raise ImportError_(f"{ttype.value} requires cash_flow")
                if ttype == TransactionType.WITHDRAWAL and cash_flow > 0:
                    cash_flow = -cash_flow
                if ttype == TransactionType.FEE and cash_flow > 0:
                    cash_flow = -cash_flow
            if ttype == TransactionType.SPLIT and (
                split_ratio is None or split_ratio <= 0
            ):
                raise ImportError_("SPLIT requires positive split_ratio")
            if ttype == TransactionType.SYMBOL_CHANGE and not new_ticker:
                raise ImportError_("SYMBOL_CHANGE requires new_ticker")

            source_key = (row.get("transaction_id") or "").strip() or None
            if (
                source_key
                and db.execute(
                    select(Transaction.id).where(Transaction.source_key == source_key)
                ).first()
            ):
                skipped += 1
                continue
            db.add(
                Transaction(
                    account_id=account_id,
                    trade_date=trade_date,
                    ticker=ticker,
                    type=ttype,
                    shares=shares,
                    price=price,
                    fees=fees,
                    cash_flow=cash_flow,
                    split_ratio=split_ratio,
                    new_ticker=new_ticker,
                    source=(row.get("source") or "CSV_IMPORT").strip(),
                    source_key=source_key,
                    notes=(row.get("notes") or "").strip() or None,
                )
            )
            created += 1
        except (ImportError_, ValueError, KeyError) as err:
            errors.append(f"line {i}: {err}")
    if errors:
        db.rollback()
        return {"created": 0, "skipped": 0, "errors": errors, "committed": False}
    db.commit()
    return {"created": created, "skipped": skipped, "errors": [], "committed": True}


def export_transactions(db: Session, account_ids: list[str]) -> str:
    txns = (
        db.execute(
            select(Transaction)
            .where(Transaction.account_id.in_(account_ids))
            .order_by(Transaction.trade_date, Transaction.id)
        )
        .scalars()
        .all()
    )
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=EXPORT_COLUMNS)
    writer.writeheader()
    for t in txns:
        writer.writerow(
            {
                "transaction_id": t.source_key or f"txn-{t.id}",
                "account_id": t.account_id,
                "trade_date": t.trade_date.isoformat(),
                "ticker": t.ticker or "",
                "transaction_type": t.type.value,
                "shares": t.shares if t.shares is not None else "",
                "price": t.price if t.price is not None else "",
                "fees": t.fees,
                "cash_flow": t.cash_flow if t.cash_flow is not None else "",
                "split_ratio": t.split_ratio if t.split_ratio is not None else "",
                "new_ticker": t.new_ticker or "",
                "source": t.source,
                "notes": t.notes or "",
            }
        )
    return buf.getvalue()


def _num(value) -> float | None:
    if value is None:
        return None
    s = str(value).strip().replace("$", "").replace(",", "")
    if not s:
        return None
    return float(s)
