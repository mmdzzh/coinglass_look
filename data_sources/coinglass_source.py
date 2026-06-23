import logging
import os
import time
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

import requests

from .base_source import DataSource

logger = logging.getLogger(__name__)


class CoinglassDataSource(DataSource):
    name = "coinglass"

    INTERVAL_MAP = {
        "5m": "5m",
        "15m": "15m",
        "1h": "1h",
        "4h": "4h",
        "1d": "1d",
        "1w": "1w",
    }

    def __init__(self, api_key: str = None, base_url: str = "https://open-api-v4.coinglass.com"):
        self.api_key = api_key or os.environ.get("COINGLASS_API_KEY")
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "CG-API-KEY": self.api_key or "",
            "User-Agent": "coinglass-oi-dashboard/1.0",
        })
        self.proxies = self._detect_proxies()

    @staticmethod
    def _detect_proxies() -> Dict[str, Optional[str]]:
        http = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
        https = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        if http and https:
            return {"http": http, "https": https}
        system_proxy = _get_windows_system_proxy()
        return {"http": system_proxy, "https": system_proxy}

    def _get(self, path: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("Coinglass API key is required. Set COINGLASS_API_KEY in .env")
        url = f"{self.base_url}{path}"
        for attempt in range(5):
            try:
                time.sleep(0.12)
                resp = self.session.get(url, params=params or {}, timeout=30, proxies=self.proxies)
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:
                logger.warning(f"Coinglass request failed (attempt {attempt + 1}/5): {exc}")
                if attempt == 4:
                    raise
                time.sleep(2 ** attempt)
        return {}

    def list_symbols(self) -> List[Dict[str, Any]]:
        # Coinglass V4 supported-exchange-pair endpoint is not consistently available;
        # fall back to Binance's USDT perpetual symbol list since Coinglass OI history
        # is queried per exchange (we use Binance as the reference exchange).
        try:
            from data_sources.binance_source import BinanceDataSource
            return BinanceDataSource().list_symbols()
        except Exception as exc:
            logger.warning(f"Failed to fetch Binance symbols for Coinglass fallback: {exc}")
            return []

    def fetch_oi_history(
        self,
        symbol: str,
        interval: str,
        start_time: datetime = None,
        end_time: datetime = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        interval_str = self.INTERVAL_MAP.get(interval, "1d")
        base_params = {
            "exchange": "Binance",
            "symbol": symbol,
            "interval": interval_str,
            "limit": min(limit, 1000),
        }
        if start_time:
            base_params["start_time"] = int(start_time.timestamp() * 1000)
        if end_time:
            base_params["end_time"] = int(end_time.timestamp() * 1000)

        # Fetch both USD value and coin quantity; unit can be 'usd' or 'coin'.
        usd_data = self._get("/api/futures/open-interest/history", params={**base_params, "unit": "usd"})
        coin_data = self._get("/api/futures/open-interest/history", params={**base_params, "unit": "coin"})

        by_ts = {}
        for row in usd_data.get("data", []):
            ts = self._parse_ms(row.get("time"))
            by_ts[ts] = {"symbol": symbol, "timestamp": ts, "sum_open_interest": None, "sum_open_interest_value": row.get("close")}
        for row in coin_data.get("data", []):
            ts = self._parse_ms(row.get("time"))
            if ts in by_ts:
                by_ts[ts]["sum_open_interest"] = row.get("close")
            else:
                by_ts[ts] = {"symbol": symbol, "timestamp": ts, "sum_open_interest": row.get("close"), "sum_open_interest_value": None}

        return [by_ts[ts] for ts in sorted(by_ts)]

    def supported_intervals(self) -> List[str]:
        return ["5m", "15m", "1h", "4h", "1d", "1w"]

    @staticmethod
    def _parse_ms(value: Optional[int]):
        if value is None:
            return None
        return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)


def _get_windows_system_proxy() -> Optional[str]:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
            proxy_enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
            proxy_server, _ = winreg.QueryValueEx(key, "ProxyServer")
            if proxy_enable and proxy_server:
                if proxy_server.startswith("http="):
                    for part in proxy_server.split(";"):
                        if part.startswith("https="):
                            return "http://" + part.split("=", 1)[1]
                        if part.startswith("http="):
                            return "http://" + part.split("=", 1)[1]
                return f"http://{proxy_server}"
    except Exception:
        pass
    return None
