from __future__ import annotations

import logging
import threading

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import services
from ..database import get_db, session_scope
from ..market_data import MarketDataError, get_market_data_client
from ..ingestion import refresh_index_snapshot, refresh_market_data

router = APIRouter(prefix="/api", tags=["admin"])
log = logging.getLogger(__name__)

refresh_lock = threading.Lock()


def _refresh_index(db: Session) -> dict | None:
    """The index heatmap never fails a refresh: it keeps its last snapshot."""
    try:
        with get_market_data_client() as client:
            return refresh_index_snapshot(db, client)
    except MarketDataError as err:
        db.rollback()
        log.warning("Index snapshot failed: %s", err)
        return None


@router.post("/refresh")
def refresh(db: Session = Depends(get_db)):
    """Manual refresh. Serialized: concurrent calls return 409."""
    if not refresh_lock.acquire(blocking=False):
        raise HTTPException(409, "A refresh is already running")
    try:
        report = refresh_market_data(db, trigger="manual")
        index = _refresh_index(db)
        return {
            "run_id": report.run_id,
            "status": report.status,
            "symbols_total": report.symbols_total,
            "symbols_ok": report.symbols_ok,
            "symbols_failed": report.symbols_failed,
            "failures": report.failures,
            "dividends_created": report.dividends_created,
            "splits_created": report.splits_created,
            "index_symbols": index["updated"] if index else 0,
        }
    except MarketDataError as err:
        raise HTTPException(502, f"Market data provider error: {err}")
    finally:
        refresh_lock.release()


@router.get("/data-quality")
def data_quality(db: Session = Depends(get_db)):
    return services.data_quality_payload(db)


def run_scheduled_refresh() -> None:
    """Entry point used by APScheduler (creates its own session)."""
    if not refresh_lock.acquire(blocking=False):
        return
    try:
        with session_scope() as db:
            refresh_market_data(db, trigger="scheduled")
            _refresh_index(db)
    except Exception:  # logged inside; never crash the scheduler thread
        log.exception("Scheduled refresh failed")
    finally:
        refresh_lock.release()
