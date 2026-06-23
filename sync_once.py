import logging
from database import init_db, SessionLocal
from data_sources import BybitDataSource
from sync_service import SyncService

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

TOP_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
    "ADAUSDT", "LINKUSDT", "LTCUSDT", "BCHUSDT", "AVAXUSDT",
]

if __name__ == "__main__":
    init_db()
    db = SessionLocal()
    try:
        service = SyncService(BybitDataSource())
        logger.info("Syncing symbols...")
        service.sync_symbols(db)

        for symbol in TOP_SYMBOLS:
            logger.info(f"Syncing {symbol} 1d history...")
            try:
                rows = service.backfill_symbol_interval(db, symbol, "1d")
                logger.info(f"Inserted {rows} rows for {symbol}/1d")
            except Exception as exc:
                logger.error(f"Failed to sync {symbol}: {exc}")
    finally:
        db.close()
