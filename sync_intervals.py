import argparse
import logging
import sys
from database import init_db, SessionLocal
from data_sources import BybitDataSource, BinanceDataSource, CoinglassDataSource
from sync_service import SyncService
from config import BACKFILL_DAYS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("sync_intervals.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

SOURCE_MAP = {
    "bybit": BybitDataSource,
    "binance": BinanceDataSource,
    "coinglass": CoinglassDataSource,
}


def sync_source_intervals(source_name: str, intervals: list[str] = None):
    if source_name not in SOURCE_MAP:
        raise ValueError(f"Unknown source: {source_name}. Supported: {list(SOURCE_MAP.keys())}")

    if intervals is None:
        intervals = ["4h", "1h", "15m", "5m"]

    init_db()
    db = SessionLocal()
    try:
        service = SyncService(SOURCE_MAP[source_name]())
        logger.info(f"Syncing symbols for {source_name}...")
        symbols = service.sync_symbols(db)
        active_symbols = [s.symbol for s in symbols if s.active]
        logger.info(f"Active symbols: {len(active_symbols)}")

        for interval in intervals:
            days = BACKFILL_DAYS.get(interval, 30)
            logger.info(f"[{source_name}] Syncing {interval} (last {days} days) for {len(active_symbols)} symbols...")
            total_rows = 0
            for idx, symbol in enumerate(active_symbols, 1):
                try:
                    rows = service.backfill_symbol_interval(db, symbol, interval)
                    total_rows += rows
                    if rows > 0:
                        logger.info(f"[{source_name}] [{idx}/{len(active_symbols)}] {symbol}/{interval}: +{rows} rows")
                except Exception as exc:
                    logger.error(f"[{source_name}] [{idx}/{len(active_symbols)}] Failed {symbol}/{interval}: {exc}")
                    try:
                        db.rollback()
                    except Exception:
                        pass
            logger.info(f"[{source_name}] {interval} sync complete: {total_rows} rows inserted")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill non-daily OI intervals")
    parser.add_argument("source", choices=list(SOURCE_MAP.keys()), help="Data source name")
    parser.add_argument("--intervals", nargs="+", default=None, help="Intervals to sync (default: 4h 1h 15m 5m)")
    args = parser.parse_args()
    sync_source_intervals(args.source, args.intervals)
