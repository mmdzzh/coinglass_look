import os
from typing import Dict
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://coinglass:coinglass@localhost:5432/coinglass")
BINANCE_FAPI_BASE = os.getenv("BINANCE_FAPI_BASE", "https://fapi.binance.com")
BYBIT_API_BASE = os.getenv("BYBIT_API_BASE", "https://api.bybit.com")
COINGLASS_API_KEY = os.getenv("COINGLASS_API_KEY", "")
COINGLASS_API_BASE = os.getenv("COINGLASS_API_BASE", "https://open-api-v4.coinglass.com")

# Comma-separated list of enabled data sources: binance, bybit, coinglass
DATA_SOURCES = [s.strip() for s in os.getenv("DATA_SOURCES", "binance,bybit").split(",") if s.strip()]
DEFAULT_DATA_SOURCE = os.getenv("DEFAULT_DATA_SOURCE", DATA_SOURCES[0] if DATA_SOURCES else "binance")

# Supported intervals and their Binance API period strings
INTERVALS: Dict[str, str] = {
    "5m": "5m",
    "15m": "15m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
    "1w": "1d",   # aggregated from daily data
    "1M": "1d",   # aggregated from daily data
}

DISPLAY_INTERVALS = list(INTERVALS.keys())

# Backfill depth in days; 0 means "to onboard date" (unlimited)
BACKFILL_DAYS: Dict[str, int] = {
    "5m": int(os.getenv("BACKFILL_DAYS_5M", "30")),
    "15m": int(os.getenv("BACKFILL_DAYS_15M", "30")),
    "1h": int(os.getenv("BACKFILL_DAYS_1H", "30")),
    "4h": int(os.getenv("BACKFILL_DAYS_4H", "365")),
    "1d": int(os.getenv("BACKFILL_DAYS_1D", "0")),
    "1w": int(os.getenv("BACKFILL_DAYS_1W", "0")),
    "1M": int(os.getenv("BACKFILL_DAYS_1M", "0")),
}

# Update cadence in minutes
UPDATE_MINUTES: Dict[str, int] = {
    "5m": int(os.getenv("UPDATE_MINUTES_5M", "15")),
    "15m": int(os.getenv("UPDATE_MINUTES_15M", "15")),
    "1h": int(os.getenv("UPDATE_MINUTES_1H", "60")),
    "4h": int(os.getenv("UPDATE_MINUTES_4H", "60")),
    "1d": int(os.getenv("UPDATE_MINUTES_1D", "360")),
    "1w": int(os.getenv("UPDATE_MINUTES_1W", "360")),
    "1M": int(os.getenv("UPDATE_MINUTES_1M", "360")),
}

REQUEST_DELAY_MS = float(os.getenv("REQUEST_DELAY_MS", "120"))
REQUEST_MAX_RETRIES = int(os.getenv("REQUEST_MAX_RETRIES", "5"))
