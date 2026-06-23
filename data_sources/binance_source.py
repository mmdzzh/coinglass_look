import logging
from datetime import datetime
from typing import List, Dict, Any

from config import BINANCE_FAPI_BASE
from .base_source import DataSource
from binance_client import BinanceClient

logger = logging.getLogger(__name__)


class BinanceDataSource(DataSource):
    name = "binance"

    INTERVAL_MAP = {
        "5m": "5m",
        "15m": "15m",
        "1h": "1h",
        "4h": "4h",
        "1d": "1d",
    }

    def __init__(self, base_url: str = None):
        self.client = BinanceClient(base_url=base_url or BINANCE_FAPI_BASE)

    def list_symbols(self) -> List[Dict[str, Any]]:
        return self.client.list_usds_perpetual_symbols()

    def fetch_oi_history(
        self,
        symbol: str,
        interval: str,
        start_time: datetime = None,
        end_time: datetime = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        if interval in ("1w", "1M"):
            interval = "1d"
        period = self.INTERVAL_MAP.get(interval, interval)
        # Binance openInterestHist returns the most recent records only;
        # startTime/endTime are not reliably supported.
        return self.client.fetch_open_interest_history(
            symbol=symbol,
            period=period,
            limit=limit,
        )

    def supported_intervals(self) -> List[str]:
        return ["5m", "15m", "1h", "4h", "1d", "1w", "1M"]
