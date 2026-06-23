import logging
import os
import time
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

import requests

from .base_source import DataSource

logger = logging.getLogger(__name__)


class BybitDataSource(DataSource):
    name = "bybit"

    INTERVAL_MAP = {
        "5m": "5min",
        "15m": "15min",
        "1h": "1h",
        "4h": "4h",
        "1d": "1d",
    }

    KLINE_INTERVAL_MAP = {
        "5m": "5",
        "15m": "15",
        "1h": "60",
        "4h": "240",
        "1d": "D",
    }

    def __init__(self, base_url: str = "https://api.bybit.com"):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
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
        url = f"{self.base_url}{path}"
        for attempt in range(5):
            try:
                time.sleep(0.12)
                resp = self.session.get(url, params=params or {}, timeout=30, proxies=self.proxies)
                resp.raise_for_status()
                data = resp.json()
                if data.get("retCode") != 0:
                    logger.warning(f"Bybit API error: {data}")
                    raise RuntimeError(data.get("retMsg", "Unknown Bybit error"))
                return data
            except Exception as exc:
                logger.warning(f"Bybit request failed (attempt {attempt + 1}/5): {exc}")
                if attempt == 4:
                    raise
                time.sleep(2 ** attempt)
        return {}

    def list_symbols(self) -> List[Dict[str, Any]]:
        data = self._get("/v5/market/instruments-info", {
            "category": "linear",
            "status": "Trading",
            "limit": 1000,
        })
        symbols = []
        for item in data.get("result", {}).get("list", []):
            if item.get("quoteCoin") != "USDT":
                continue
            if item.get("status") != "Trading":
                continue
            symbols.append({
                "symbol": item["symbol"],
                "base_asset": item.get("baseCoin"),
                "quote_asset": item.get("quoteCoin"),
                "onboard_date": self._parse_ms(item.get("launchTime")),
            })
        return symbols

    def fetch_oi_history(
        self,
        symbol: str,
        interval: str,
        start_time: datetime = None,
        end_time: datetime = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        if interval in ("1w", "1M"):
            interval = "1d"
        interval_str = self.INTERVAL_MAP.get(interval, interval)
        params = {
            "category": "linear",
            "symbol": symbol,
            "intervalTime": interval_str,
            "limit": min(limit, 200),
        }
        if start_time:
            params["startTime"] = int(start_time.timestamp() * 1000)
        if end_time:
            params["endTime"] = int(end_time.timestamp() * 1000)

        data = self._get("/v5/market/open-interest", params=params)
        oi_rows = data.get("result", {}).get("list", [])
        if not oi_rows:
            return []

        # Fetch closing prices for the same window to estimate notional OI value
        price_map = self._fetch_price_map(
            symbol=symbol,
            interval=interval,
            start_time=start_time,
            end_time=end_time,
            limit=min(limit, 200),
        )

        result = []
        for row in oi_rows:
            ts_ms = int(row["timestamp"])
            ts = self._parse_ms(ts_ms)
            oi_qty = row.get("openInterest")
            close_price = price_map.get(ts_ms)
            oi_value = None
            if oi_qty is not None and close_price is not None:
                try:
                    oi_value = float(oi_qty) * float(close_price)
                except (TypeError, ValueError):
                    pass
            result.append({
                "symbol": symbol,
                "timestamp": ts,
                "sum_open_interest": oi_qty,
                "sum_open_interest_value": oi_value,
            })
        return result

    def _fetch_price_map(
        self,
        symbol: str,
        interval: str,
        start_time: datetime = None,
        end_time: datetime = None,
        limit: int = 200,
    ) -> Dict[int, float]:
        kline_interval = self.KLINE_INTERVAL_MAP.get(interval, "D")
        params = {
            "category": "linear",
            "symbol": symbol,
            "interval": kline_interval,
            "limit": limit,
        }
        if start_time:
            params["startTime"] = int(start_time.timestamp() * 1000)
        if end_time:
            params["endTime"] = int(end_time.timestamp() * 1000)

        try:
            data = self._get("/v5/market/kline", params=params)
            price_map = {}
            for row in data.get("result", {}).get("list", []):
                # [timestamp, open, high, low, close, volume, turnover]
                ts_ms = int(row[0])
                price_map[ts_ms] = float(row[4])
            return price_map
        except Exception as exc:
            logger.warning(f"Failed to fetch price for {symbol}: {exc}")
            return {}

    def supported_intervals(self) -> List[str]:
        return ["5m", "15m", "1h", "4h", "1d", "1w", "1M"]

    @staticmethod
    def _parse_ms(value):
        if value is None:
            return None
        return datetime.fromtimestamp(int(value) / 1000.0, tz=timezone.utc)


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
