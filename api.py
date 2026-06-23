import logging
import threading
from datetime import datetime, timezone, timedelta
from typing import List, Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from config import DISPLAY_INTERVALS, INTERVALS, DEFAULT_DATA_SOURCE, DATA_SOURCES
from database import get_db
from models import OpenInterest, SymbolMeta
from schemas import (
    LatestOIItem,
    OIHistoryResponse,
    OpenInterestOut,
    SymbolMetaOut,
    SyncStatus,
)
from sync_service import SyncService
from data_sources import BinanceDataSource, BybitDataSource, CoinglassDataSource

logger = logging.getLogger(__name__)
router = APIRouter()

SOURCE_MAP = {
    "binance": BinanceDataSource,
    "bybit": BybitDataSource,
    "coinglass": CoinglassDataSource,
}


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid datetime format: {value}")


def _get_source(source_name: str):
    if source_name not in DATA_SOURCES:
        raise HTTPException(
            status_code=400,
            detail=f"Source '{source_name}' is not enabled. Enabled sources: {DATA_SOURCES}",
        )
    return SOURCE_MAP[source_name]()


@router.get("/api/sources", response_model=List[str])
def list_sources():
    return DATA_SOURCES


@router.get("/api/pairs", response_model=List[SymbolMetaOut])
def list_pairs(
    source: str = Query(DEFAULT_DATA_SOURCE),
    active_only: bool = Query(True),
    db: Session = Depends(get_db),
):
    query = db.query(SymbolMeta).filter(SymbolMeta.source == source)
    if active_only:
        query = query.filter(SymbolMeta.active == True)
    return query.order_by(SymbolMeta.symbol).all()


@router.get("/api/oi/latest", response_model=List[LatestOIItem])
def get_latest_oi(
    source: str = Query(DEFAULT_DATA_SOURCE),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    # Get latest timestamp per symbol
    latest_subq = (
        db.query(
            OpenInterest.symbol,
            OpenInterest.source,
            func.max(OpenInterest.timestamp).label("max_ts"),
        )
        .filter(OpenInterest.source == source, OpenInterest.interval == "1d")
        .group_by(OpenInterest.symbol, OpenInterest.source)
        .subquery()
    )

    # Get previous timestamp per symbol (second latest)
    prev_subq = (
        db.query(
            OpenInterest.symbol,
            OpenInterest.source,
            func.max(OpenInterest.timestamp).label("prev_ts"),
        )
        .filter(
            OpenInterest.source == source,
            OpenInterest.interval == "1d",
        )
        .group_by(OpenInterest.symbol, OpenInterest.source)
        .subquery()
    )

    latest_rows = (
        db.query(OpenInterest, SymbolMeta)
        .join(
            latest_subq,
            (OpenInterest.symbol == latest_subq.c.symbol)
            & (OpenInterest.source == latest_subq.c.source)
            & (OpenInterest.timestamp == latest_subq.c.max_ts),
        )
        .outerjoin(
            SymbolMeta,
            (OpenInterest.symbol == SymbolMeta.symbol) & (OpenInterest.source == SymbolMeta.source),
        )
        .filter(OpenInterest.source == source)
        .order_by(OpenInterest.sum_open_interest_value.desc().nullslast())
        .limit(limit)
        .all()
    )

    # Build previous value lookup (one query for all symbols)
    prev_values = {}
    symbols = [oi.symbol for oi, _ in latest_rows]
    if symbols:
        prev_rows = (
            db.query(OpenInterest.symbol, OpenInterest.timestamp, OpenInterest.sum_open_interest_value)
            .filter(
                OpenInterest.source == source,
                OpenInterest.interval == "1d",
                OpenInterest.symbol.in_(symbols),
            )
            .all()
        )
        # Group by symbol and sort timestamps descending
        from collections import defaultdict
        by_symbol = defaultdict(list)
        for r in prev_rows:
            by_symbol[r.symbol].append((r.timestamp, r.sum_open_interest_value))
        for symbol, entries in by_symbol.items():
            entries.sort(key=lambda x: x[0], reverse=True)
            if len(entries) >= 2:
                prev_values[symbol] = entries[1][1]

    result = []
    for oi, meta in latest_rows:
        prev_value = prev_values.get(oi.symbol)
        change_percent = None
        if prev_value and oi.sum_open_interest_value:
            try:
                change_percent = float((oi.sum_open_interest_value - prev_value) / prev_value * 100)
            except (TypeError, ValueError):
                pass
        result.append(
            LatestOIItem(
                symbol=oi.symbol,
                source=oi.source,
                base_asset=meta.base_asset if meta else None,
                timestamp=oi.timestamp,
                sum_open_interest=oi.sum_open_interest,
                sum_open_interest_value=oi.sum_open_interest_value,
                prev_open_interest_value=prev_value,
                change_percent=change_percent,
            )
        )
    return result


@router.get("/api/oi/{symbol}", response_model=OIHistoryResponse)
def get_oi_history(
    symbol: str,
    interval: str = Query("1d", enum=DISPLAY_INTERVALS),
    source: str = Query(DEFAULT_DATA_SOURCE),
    start: Optional[str] = Query(None, description="ISO datetime start"),
    end: Optional[str] = Query(None, description="ISO datetime end"),
    aggregate: bool = Query(True, description="Aggregate daily data for 1w/1M"),
    db: Session = Depends(get_db),
):
    if interval not in DISPLAY_INTERVALS:
        raise HTTPException(status_code=400, detail=f"Invalid interval. Choose from {DISPLAY_INTERVALS}")

    start_dt = _parse_dt(start)
    end_dt = _parse_dt(end) or datetime.now(timezone.utc)

    base_interval = INTERVALS[interval]
    query = (
        db.query(OpenInterest)
        .filter(
            OpenInterest.symbol == symbol,
            OpenInterest.source == source,
            OpenInterest.interval == base_interval,
            OpenInterest.timestamp <= end_dt,
        )
        .order_by(OpenInterest.timestamp)
    )
    if start_dt:
        query = query.filter(OpenInterest.timestamp >= start_dt)
    rows = query.all()

    if interval in ("1w", "1M") and aggregate:
        data = _aggregate_oi(rows, interval)
    else:
        data = [
            OpenInterestOut(
                timestamp=r.timestamp,
                sum_open_interest=r.sum_open_interest,
                sum_open_interest_value=r.sum_open_interest_value,
            )
            for r in rows
        ]

    return OIHistoryResponse(symbol=symbol, source=source, interval=interval, count=len(data), data=data)


# In-memory sync job tracking. Persists only for the lifetime of the process.
_sync_jobs: dict[str, dict] = {}


def _run_sync_job(source: str, full_backfill: bool, symbols: Optional[List[str]], intervals: Optional[List[str]]):
    """Run sync in a background thread with its own DB session."""
    from database import SessionLocal

    db = SessionLocal()
    job = _sync_jobs.setdefault(source, {})
    job.update({
        "running": True,
        "started_at": datetime.now(timezone.utc),
        "completed_at": None,
        "message": f"Sync in progress for {source}",
        "symbols": 0,
        "intervals": 0,
        "rows": 0,
        "error": None,
    })
    try:
        data_source_cls = SOURCE_MAP.get(source)
        if data_source_cls is None:
            raise ValueError(f"Unsupported source: {source}")
        service = SyncService(data_source_cls())
        service.sync_symbols(db)
        job["message"] = f"Syncing {source}..."

        def _progress(symbol, done, total, rows):
            job.update({
                "symbols": total,
                "rows": rows,
                "message": f"Syncing {source}: {done}/{total} ({symbol})",
            })

        if full_backfill:
            stats = service.run_full_backfill(db, symbols=symbols, intervals=intervals, progress_callback=_progress)
        else:
            stats = service.incremental_sync(db, symbols=symbols, intervals=intervals, progress_callback=_progress)
        job.update({
            **stats,
            "message": f"Sync completed for {source}",
            "running": False,
            "completed_at": datetime.now(timezone.utc),
        })
        logger.info(f"Background sync completed for {source}: {stats}")
    except Exception as exc:
        logger.exception(f"Background sync failed for {source}")
        job.update({
            "running": False,
            "completed_at": datetime.now(timezone.utc),
            "error": str(exc),
            "message": f"Sync failed for {source}: {exc}",
        })
    finally:
        db.close()


@router.post("/admin/sync", response_model=SyncStatus)
def trigger_sync(
    source: str = Query(DEFAULT_DATA_SOURCE),
    full_backfill: bool = Query(False),
    symbols: Optional[List[str]] = Query(None),
    intervals: Optional[List[str]] = Query(None),
):
    if source not in DATA_SOURCES:
        raise HTTPException(
            status_code=400,
            detail=f"Source '{source}' is not enabled. Enabled sources: {DATA_SOURCES}",
        )

    job = _sync_jobs.get(source)
    if job and job.get("running"):
        return SyncStatus(
            message=f"Sync already running for {source}",
            running=True,
            started_at=job.get("started_at"),
        )

    thread = threading.Thread(
        target=_run_sync_job,
        args=(source, full_backfill, symbols, intervals),
        daemon=True,
    )
    thread.start()
    return SyncStatus(
        message=f"Sync started for {source}",
        running=True,
        started_at=datetime.now(timezone.utc),
    )


@router.get("/admin/sync/status", response_model=SyncStatus)
def get_sync_status(source: str = Query(DEFAULT_DATA_SOURCE)):
    if source not in DATA_SOURCES:
        raise HTTPException(
            status_code=400,
            detail=f"Source '{source}' is not enabled. Enabled sources: {DATA_SOURCES}",
        )
    job = _sync_jobs.get(source, {})
    return SyncStatus(
        symbols=job.get("symbols", 0),
        intervals=job.get("intervals", 0),
        rows=job.get("rows", 0),
        message=job.get("message", "No sync run yet"),
        running=job.get("running", False),
        started_at=job.get("started_at"),
        completed_at=job.get("completed_at"),
    )


def _aggregate_oi(rows: List[OpenInterest], interval: str) -> List[OpenInterestOut]:
    if not rows:
        return []
    data = [
        {
            "timestamp": r.timestamp,
            "sum_open_interest": float(r.sum_open_interest) if r.sum_open_interest is not None else None,
            "sum_open_interest_value": float(r.sum_open_interest_value) if r.sum_open_interest_value is not None else None,
        }
        for r in rows
    ]
    df = pd.DataFrame(data)
    df.set_index("timestamp", inplace=True)

    rule = "W-SUN" if interval == "1w" else "ME"
    agg = df.resample(rule).last().dropna(subset=["sum_open_interest"])

    result = []
    for ts, row in agg.iterrows():
        result.append(
            OpenInterestOut(
                timestamp=ts.to_pydatetime(),
                sum_open_interest=row["sum_open_interest"],
                sum_open_interest_value=row["sum_open_interest_value"],
            )
        )
    return result
