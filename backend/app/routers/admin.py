from __future__ import annotations

import threading

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import services
from ..database import get_db, session_scope
from ..fmp_client import FMPError
from ..ingestion import refresh_market_data

router = APIRouter(prefix="/api", tags=["admin"])

_refresh_lock = threading.Lock()


@router.post("/refresh")
def refresh(db: Session = Depends(get_db)):
    """Manual refresh. Serialized: concurrent calls return 409."""
    if not _refresh_lock.acquire(blocking=False):
        raise HTTPException(409, "A refresh is already running")
    try:
        report = refresh_market_data(db, trigger="manual")
        return {
            "run_id": report.run_id,
            "status": report.status,
            "symbols_total": report.symbols_total,
            "symbols_ok": report.symbols_ok,
            "symbols_failed": report.symbols_failed,
            "failures": report.failures,
            "dividends_created": report.dividends_created,
            "splits_created": report.splits_created,
        }
    except FMPError as err:
        raise HTTPException(502, f"Market data provider error: {err}")
    finally:
        _refresh_lock.release()


@router.get("/data-quality")
def data_quality(db: Session = Depends(get_db)):
    return services.data_quality_payload(db)


def run_scheduled_refresh() -> None:
    """Entry point used by APScheduler (creates its own session)."""
    if not _refresh_lock.acquire(blocking=False):
        return
    try:
        with session_scope() as db:
            refresh_market_data(db, trigger="scheduled")
    except Exception:  # logged inside; never crash the scheduler thread
        import logging

        logging.getLogger(__name__).exception("Scheduled refresh failed")
    finally:
        _refresh_lock.release()
