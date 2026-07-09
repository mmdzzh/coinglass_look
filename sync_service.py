import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict

from sqlalchemy.orm import Session

from config import INTERVALS, BACKFILL_DAYS, DISPLAY_INTERVALS
from data_sources.base_source import DataSource
from database import SessionLocal
from models import SymbolMeta, OpenInterest

logger = logging.getLogger(__name__)

# Period to milliseconds mapping for pagination step sizing
PERIOD_MS = {
    "5m": 5 * 60 * 1000,
    "15m": 15 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "1d": 24 * 60 * 60 * 1000,
}


class SyncService:
    def __init__(self, data_source: DataSource):
        self.data_source = data_source

    def sync_symbols(self, db: Session) -> List[SymbolMeta]:
        symbols = self.data_source.list_symbols()
        source = self.data_source.name
        existing = {s.symbol for s in db.query(SymbolMeta).filter(SymbolMeta.source == source).all()}
        updated = []
        for item in symbols:
            symbol = item["symbol"]
            meta = (
                db.query(SymbolMeta)
                .filter(SymbolMeta.symbol == symbol, SymbolMeta.source == source)
                .first()
            )
            if meta is None:
                meta = SymbolMeta(symbol=symbol, source=source)
                db.add(meta)
            meta.base_asset = item.get("base_asset")
            meta.quote_asset = item.get("quote_asset")
            meta.onboard_date = _ensure_aware(item.get("onboard_date"))
            meta.active = True
            updated.append(meta)
        new_symbols = {s["symbol"] for s in symbols}
        for symbol in existing - new_symbols:
            meta = (
                db.query(SymbolMeta)
                .filter(SymbolMeta.symbol == symbol, SymbolMeta.source == source)
                .first()
            )
            if meta:
                meta.active = False
        db.commit()
        logger.info(f"Synced {len(updated)} symbols from {source}.")
        return updated

    def backfill_symbol_interval(
        self,
        db: Session,
        symbol: str,
        interval: str,
        to_date: Optional[datetime] = None,
    ) -> int:
        """Backfill OI for a single symbol/interval. Returns number of rows inserted."""
        if interval in ("1w", "1M"):
            return 0

        source = self.data_source.name
        now = datetime.now(timezone.utc)

        if to_date is None:
            days = BACKFILL_DAYS.get(interval, 7)
            if days > 0:
                to_date = now - timedelta(days=days)
            else:
                meta = (
                    db.query(SymbolMeta)
                    .filter(SymbolMeta.symbol == symbol, SymbolMeta.source == source)
                    .first()
                )
                to_date = meta.onboard_date if meta and meta.onboard_date else now - timedelta(days=365)

        to_date = _ensure_aware(to_date)
        end_time = now
        total_rows = 0
        current_end = end_time
        period_ms = PERIOD_MS.get(interval, 24 * 60 * 60 * 1000)

        # Some sources (e.g., Binance) do not support time-range queries for OI;
        # they only return recent data. Sources like Bybit support ranges but return
        # the most recent N records within the range, so we paginate backwards.
        while current_end > to_date:
            rows = self.data_source.fetch_oi_history(
                symbol=symbol,
                interval=interval,
                start_time=to_date,
                end_time=current_end,
                limit=500,
            )
            if not rows:
                break

            # Filter rows within our desired window and sort ascending
            rows = [r for r in rows if to_date <= _ensure_aware(r["timestamp"]) <= end_time]
            if not rows:
                break
            rows.sort(key=lambda r: _ensure_aware(r["timestamp"]))

            upserted = self._upsert_oi_rows(db, source, interval, rows)
            total_rows += upserted
            logger.debug(f"Backfilled {source}/{symbol}/{interval}: {upserted} rows from {rows[0]['timestamp']} to {rows[-1]['timestamp']}")

            earliest_ts = _ensure_aware(rows[0]["timestamp"])
            # If we didn't get any earlier data, stop to avoid infinite loop
            if earliest_ts >= current_end:
                break
            current_end = earliest_ts - timedelta(milliseconds=period_ms)

        meta = (
            db.query(SymbolMeta)
            .filter(SymbolMeta.symbol == symbol, SymbolMeta.source == source)
            .first()
        )
        if meta:
            meta.last_oi_sync_at = now
            db.commit()
        return total_rows

    def incremental_sync(
        self,
        db: Session,
        symbols: Optional[List[str]] = None,
        intervals: Optional[List[str]] = None,
        progress_callback=None,
    ) -> Dict[str, int]:
        intervals = intervals or [i for i in DISPLAY_INTERVALS if i not in ("1w", "1M")]
        source = self.data_source.name
        if symbols is None:
            metas = db.query(SymbolMeta).filter(SymbolMeta.active == True, SymbolMeta.source == source).all()
            symbols = [m.symbol for m in metas]

        # Lookback window per interval so that coarse-grained candles are not
        # missed when last_oi_sync_at is just a few hours ago.
        LOOKBACK = {
            "5m": timedelta(hours=2),
            "15m": timedelta(hours=2),
            "1h": timedelta(hours=4),
            "4h": timedelta(hours=8),
            "1d": timedelta(days=2),
            "1w": timedelta(days=7),
            "1M": timedelta(days=30),
        }

        stats = {"source": source, "symbols": len(symbols), "intervals": len(intervals), "rows": 0}
        for idx, symbol in enumerate(symbols):
            for interval in intervals:
                try:
                    meta = (
                        db.query(SymbolMeta)
                        .filter(SymbolMeta.symbol == symbol, SymbolMeta.source == source)
                        .first()
                    )
                    if meta and meta.last_oi_sync_at:
                        start_time = _ensure_aware(meta.last_oi_sync_at) - LOOKBACK.get(interval, timedelta(hours=2))
                    else:
                        start_time = datetime.now(timezone.utc) - timedelta(
                            days=BACKFILL_DAYS.get(interval, 7)
                        )
                    rows = self.backfill_symbol_interval(db, symbol, interval, to_date=start_time)
                    stats["rows"] += rows
                except Exception as exc:
                    logger.error(f"Failed to sync {source}/{symbol}/{interval}: {exc}")
            if progress_callback:
                try:
                    progress_callback(symbol=symbol, done=idx + 1, total=len(symbols), rows=stats["rows"])
                except Exception:
                    pass
        return stats

    def run_full_backfill(
        self,
        db: Session,
        symbols: Optional[List[str]] = None,
        intervals: Optional[List[str]] = None,
        progress_callback=None,
    ) -> Dict[str, int]:
        intervals = intervals or [i for i in DISPLAY_INTERVALS if i not in ("1w", "1M")]
        source = self.data_source.name
        if symbols is None:
            metas = db.query(SymbolMeta).filter(SymbolMeta.active == True, SymbolMeta.source == source).all()
            symbols = [m.symbol for m in metas]

        stats = {"source": source, "symbols": len(symbols), "intervals": len(intervals), "rows": 0}
        for idx, symbol in enumerate(symbols):
            for interval in intervals:
                try:
                    rows = self.backfill_symbol_interval(db, symbol, interval)
                    stats["rows"] += rows
                except Exception as exc:
                    logger.error(f"Failed to backfill {source}/{symbol}/{interval}: {exc}")
            if progress_callback:
                try:
                    progress_callback(symbol=symbol, done=idx + 1, total=len(symbols), rows=stats["rows"])
                except Exception:
                    pass
        return stats

    @staticmethod
    def _upsert_oi_rows(db: Session, source: str, interval: str, rows: List[Dict]) -> int:
        if not rows:
            return 0

        # Build unique keys and also deduplicate within the batch
        seen = set()
        unique_rows = []
        for row in rows:
            ts = _ensure_aware(row["timestamp"])
            key = (row["symbol"], source, interval, ts)
            if key in seen:
                continue
            seen.add(key)
            unique_rows.append({**row, "timestamp": ts})

        if not unique_rows:
            return 0

        # Query existing records for all symbols/timestamps in this batch.
        symbols = list({r["symbol"] for r in unique_rows})
        aware_timestamps = [r["timestamp"] for r in unique_rows]
        existing = (
            db.query(OpenInterest.symbol, OpenInterest.source, OpenInterest.interval, OpenInterest.timestamp)
            .filter(
                OpenInterest.symbol.in_(symbols),
                OpenInterest.source == source,
                OpenInterest.interval == interval,
                OpenInterest.timestamp.in_(aware_timestamps),
            )
            .all()
        )
        existing_set = {(r.symbol, r.source, r.interval, _ensure_aware(r.timestamp)) for r in existing}

        inserted = 0
        for row in unique_rows:
            key = (row["symbol"], source, interval, row["timestamp"])
            if key in existing_set:
                continue
            db.add(
                OpenInterest(
                    symbol=row["symbol"],
                    source=source,
                    interval=interval,
                    timestamp=row["timestamp"],
                    sum_open_interest=row.get("sum_open_interest"),
                    sum_open_interest_value=row.get("sum_open_interest_value"),
                )
            )
            inserted += 1
            if inserted % 200 == 0:
                db.commit()
        db.commit()
        return inserted


def _ensure_aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def run_scheduled_sync(intervals: Optional[List[str]] = None):
    """Entry point for APScheduler job. Syncs all enabled data sources.

    By default all non-weekly/monthly intervals are synced.  Callers
    (e.g. APScheduler jobs in main.py) should pass a specific list
    such as ``["4h"]`` so that each interval runs on its own cadence.
    """
    from config import DATA_SOURCES
    from data_sources import BinanceDataSource, BybitDataSource, CoinglassDataSource

    source_map = {
        "binance": BinanceDataSource,
        "bybit": BybitDataSource,
        "coinglass": CoinglassDataSource,
    }

    if intervals is None:
        intervals = [i for i in DISPLAY_INTERVALS if i not in ("1w", "1M")]

    db = SessionLocal()
    try:
        for source_name in DATA_SOURCES:
            cls = source_map.get(source_name)
            if cls is None:
                logger.warning(f"Unknown data source: {source_name}")
                continue
            try:
                service = SyncService(cls())
                service.sync_symbols(db)
                stats = service.incremental_sync(db, intervals=intervals)
                logger.info(f"Scheduled sync complete for {source_name}: {stats}")
            except Exception as exc:
                logger.error(f"Scheduled sync failed for {source_name}: {exc}")
    finally:
        db.close()
