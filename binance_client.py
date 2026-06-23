import os
import time
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

import requests

from config import BINANCE_FAPI_BASE, REQUEST_DELAY_MS, REQUEST_MAX_RETRIES

logger = logging.getLogger(__name__)


def _get_system_proxy() -> Optional[str]:
    """Try to detect Windows system proxy."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
            proxy_enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
            proxy_server, _ = winreg.QueryValueEx(key, "ProxyServer")
            if proxy_enable and proxy_server:
                # ProxyServer may be '127.0.0.1:7897' or 'http=...;https=...'
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


def _get_proxies() -> Dict[str, Optional[str]]:
    http_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if not http_proxy or not https_proxy:
        system_proxy = _get_system_proxy()
        http_proxy = http_proxy or system_proxy
        https_proxy = https_proxy or system_proxy
    return {
        "http": http_proxy,
        "https": https_proxy,
    }


class BinanceClient:
    def __init__(self, base_url: str = BINANCE_FAPI_BASE):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "coinglass-oi-dashboard/1.0",
        })
        self.proxies = _get_proxies()
        if self.proxies.get("https") or self.proxies.get("http"):
            logger.info(f"Using proxies: {self.proxies}")

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.base_url}{path}"
        for attempt in range(REQUEST_MAX_RETRIES):
            try:
                time.sleep(REQUEST_DELAY_MS / 1000.0)
                response = self.session.get(
                    url,
                    params=params or {},
                    timeout=30,
                    proxies=self.proxies,
                )
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", "60"))
                    logger.warning(f"Rate limited. Sleeping {retry_after}s...")
                    time.sleep(retry_after)
                    continue
                response.raise_for_status()
                return response.json()
            except requests.exceptions.RequestException as exc:
                logger.warning(f"Request failed (attempt {attempt + 1}/{REQUEST_MAX_RETRIES}): {exc}")
                if attempt == REQUEST_MAX_RETRIES - 1:
                    raise
                time.sleep(2 ** attempt)
        return []

    def get_exchange_info(self) -> Dict[str, Any]:
        return self._get("/fapi/v1/exchangeInfo")

    def list_usds_perpetual_symbols(self) -> List[Dict[str, Any]]:
        info = self.get_exchange_info()
        symbols = []
        for s in info.get("symbols", []):
            if s.get("status") != "TRADING":
                continue
            if s.get("contractType") != "PERPETUAL":
                continue
            if s.get("quoteAsset") != "USDT":
                continue
            symbols.append({
                "symbol": s["symbol"],
                "base_asset": s.get("baseAsset"),
                "quote_asset": s.get("quoteAsset"),
                "onboard_date": self._parse_ms(s.get("onboardDate")),
            })
        return symbols

    def fetch_open_interest_history(
        self,
        symbol: str,
        period: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {
            "symbol": symbol,
            "period": period,
            "limit": min(limit, 500),
        }
        # Binance's openInterestHist endpoint ignores/invalidates startTime/endTime
        # in many cases. We always fetch the most recent data and let the caller
        # filter by time if needed.
        data = self._get("/futures/data/openInterestHist", params=params)
        result = []
        for row in data:
            result.append({
                "symbol": symbol,
                "timestamp": self._parse_ms(row.get("timestamp")),
                "sum_open_interest": self._to_decimal(row.get("sumOpenInterest")),
                "sum_open_interest_value": self._to_decimal(row.get("sumOpenInterestValue")),
            })
        return result

    @staticmethod
    def _parse_ms(value: Optional[int]) -> Optional[datetime]:
        if value is None:
            return None
        return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)

    @staticmethod
    def _to_ms(dt: Optional[datetime]) -> Optional[int]:
        if dt is None:
            return None
        return int(dt.timestamp() * 1000)

    @staticmethod
    def _to_decimal(value: Optional[str]):
        if value is None:
            return None
        try:
            from decimal import Decimal
            return Decimal(value)
        except Exception:
            return None
