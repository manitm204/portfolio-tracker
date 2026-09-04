from __future__ import annotations

import datetime as dt
import threading

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from .. import csv_io, services
from ..database import get_db
from ..fmp_client import FMPError

router = APIRouter(prefix="/api/accounts", tags=["accounts"])
_monte_carlo_lock = threading.Lock()


def _ctx(db: Session, account_id: str) -> services.AccountContext:
    try:
        return services.AccountContext(db, account_id)
    except services.UnknownAccount:
        raise HTTPException(404, f"Unknown account '{account_id}'")


def _parse_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise HTTPException(422, f"Invalid date '{value}' (expected YYYY-MM-DD)")


@router.get("")
def list_accounts(db: Session = Depends(get_db)):
    return services.list_accounts(db)


@router.get("/{account_id}/summary")
def summary(account_id: str, db: Session = Depends(get_db)):
    return services.summary_payload(_ctx(db, account_id))


@router.get("/{account_id}/performance")
def performance(
    account_id: str,
    start: str | None = Query(None),
    end: str | None = Query(None),
    db: Session = Depends(get_db),
):
    return services.performance_payload(
        _ctx(db, account_id), _parse_date(start), _parse_date(end)
    )


@router.get("/{account_id}/holdings")
def holdings(account_id: str, db: Session = Depends(get_db)):
    return services.holdings_payload(_ctx(db, account_id))


@router.get("/{account_id}/allocation")
def allocation(account_id: str, db: Session = Depends(get_db)):
    return services.allocation_payload(_ctx(db, account_id))


@router.get("/{account_id}/risk")
def risk(account_id: str, db: Session = Depends(get_db)):
    return services.risk_payload(_ctx(db, account_id))


@router.get("/{account_id}/monte-carlo")
def monte_carlo(
    account_id: str,
    sims: int = Query(50, ge=5, le=200),
    seed: int | None = Query(None),
    db: Session = Depends(get_db),
):
    """Actual portfolio vs ``sims`` random same-size stock picks from the
    S&P 500. May fetch and cache new price history on first call — can take
    a while; results are reusable across accounts/requests."""
    if not _monte_carlo_lock.acquire(blocking=False):
        raise HTTPException(409, "A Monte Carlo simulation is already running")
    try:
        return services.monte_carlo_payload(_ctx(db, account_id), sims, seed)
    except services.UnsupportedMonteCarlo as err:
        raise HTTPException(400, str(err))
    except FMPError as err:
        raise HTTPException(502, f"Market data provider error: {err}")
    finally:
        _monte_carlo_lock.release()


@router.get("/{account_id}/heatmap")
def heatmap(account_id: str, period: str = Query("1D"), db: Session = Depends(get_db)):
    return services.heatmap_payload(_ctx(db, account_id), period)


@router.get("/{account_id}/transactions")
def transactions(account_id: str, db: Session = Depends(get_db)):
    return services.transactions_payload(_ctx(db, account_id))


@router.get("/{account_id}/history")
def history(account_id: str, db: Session = Depends(get_db)):
    try:
        return services.history_payload(db, account_id)
    except services.UnknownAccount:
        raise HTTPException(404, f"Unknown account '{account_id}'")


@router.get("/{account_id}/transactions/export", response_class=PlainTextResponse)
def export_transactions(account_id: str, db: Session = Depends(get_db)):
    try:
        ids = services.resolve_account_ids(db, account_id)
    except services.UnknownAccount:
        raise HTTPException(404, f"Unknown account '{account_id}'")
    csv_text = csv_io.export_transactions(db, ids)
    return PlainTextResponse(
        csv_text,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={account_id}_transactions.csv"
        },
    )


@router.post("/{account_id}/transactions/import")
async def import_transactions(
    account_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)
):
    try:
        services.resolve_account_ids(db, account_id)
    except services.UnknownAccount:
        raise HTTPException(404, f"Unknown account '{account_id}'")
    content = (await file.read()).decode("utf-8-sig")
    default = None if account_id == services.COMBINED else account_id
    try:
        return csv_io.import_transactions(db, content, default_account=default)
    except csv_io.ImportError_ as err:
        raise HTTPException(422, str(err))


@router.get("/combined/contributions")
def combined_contributions(db: Session = Depends(get_db)):
    return {"accounts": services.account_contributions(db)}
