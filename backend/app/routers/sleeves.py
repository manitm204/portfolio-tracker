from __future__ import annotations

import datetime as dt
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import services
from ..database import get_db
from ..ingestion import refresh_market_data
from ..market_data import MarketDataError, get_market_data_client
from ..sleeves import SleeveError, populate_sleeve, record_trade
from .admin import refresh_lock

router = APIRouter(prefix="/api", tags=["sleeves"])


class HoldingIn(BaseModel):
    ticker: str
    sector: str | None = None


class PopulateIn(BaseModel):
    start_date: dt.date
    holdings: list[HoldingIn]


class TradeIn(BaseModel):
    side: Literal["BUY", "SELL"]
    ticker: str
    trade_date: dt.date
    price: float | None = None
    dollars: float | None = None
    shares: float | None = None
    sector: str | None = None


@router.get("/sleeves")
def sleeves(db: Session = Depends(get_db)):
    return services.sleeves_payload(db)


@router.get("/market/heatmap")
def market_heatmap(period: str = Query("1D"), db: Session = Depends(get_db)):
    return services.index_heatmap_payload(db, period)


def _locked_update(db: Session, apply) -> None:
    """Run ``apply(client)`` then pull prices and corporate actions for anything
    new, under the refresh lock so the ledger isn't changing mid-refresh."""
    if not refresh_lock.acquire(blocking=False):
        raise HTTPException(409, "A refresh is running; try again in a moment")
    try:
        with get_market_data_client() as client:
            apply(client)
            refresh_market_data(db, trigger="manual", client=client)
    except SleeveError as err:
        db.rollback()
        raise HTTPException(422, str(err))
    except MarketDataError as err:
        db.rollback()
        raise HTTPException(502, f"Market data provider error: {err}")
    finally:
        refresh_lock.release()


@router.post("/sleeves/{account_id}/populate")
def populate(account_id: str, body: PopulateIn, db: Session = Depends(get_db)):
    _locked_update(
        db,
        lambda client: populate_sleeve(
            db,
            client,
            account_id,
            body.start_date,
            [(h.ticker, h.sector) for h in body.holdings],
        ),
    )
    return {"status": "ok"}


@router.post("/sleeves/{account_id}/trades")
def trade(account_id: str, body: TradeIn, db: Session = Depends(get_db)):
    _locked_update(
        db,
        lambda client: record_trade(
            db,
            client,
            account_id,
            body.side,
            body.ticker,
            body.trade_date,
            price=body.price,
            dollars=body.dollars,
            shares=body.shares,
            sector=body.sector,
        ),
    )
    return {"status": "ok"}
