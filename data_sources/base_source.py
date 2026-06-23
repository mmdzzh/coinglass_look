from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Dict, Any


class DataSource(ABC):
    """Abstract base class for Open Interest data sources."""

    name: str = "abstract"

    @abstractmethod
    def list_symbols(self) -> List[Dict[str, Any]]:
        """Return list of available symbols with metadata."""
        pass

    @abstractmethod
    def fetch_oi_history(
        self,
        symbol: str,
        interval: str,
        start_time: datetime = None,
        end_time: datetime = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        """Return list of OI records: [{symbol, timestamp, sum_open_interest, sum_open_interest_value}]."""
        pass

    @abstractmethod
    def supported_intervals(self) -> List[str]:
        pass
