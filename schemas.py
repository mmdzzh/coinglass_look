from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, ConfigDict


class SymbolMetaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    symbol: str
    source: str
    base_asset: Optional[str]
    quote_asset: Optional[str]
    onboard_date: Optional[datetime]
    last_oi_sync_at: Optional[datetime]
    active: bool


class OpenInterestOut(BaseModel):
    timestamp: datetime
    sum_open_interest: Optional[Decimal]
    sum_open_interest_value: Optional[Decimal]


class OIHistoryResponse(BaseModel):
    symbol: str
    source: str
    interval: str
    count: int
    data: List[OpenInterestOut]


class LatestOIItem(BaseModel):
    symbol: str
    source: str
    base_asset: Optional[str]
    timestamp: datetime
    sum_open_interest: Optional[Decimal]
    sum_open_interest_value: Optional[Decimal]
    prev_open_interest_value: Optional[Decimal] = None
    change_percent: Optional[float] = None


class SyncStatus(BaseModel):
    symbols: int = 0
    intervals: int = 0
    rows: int = 0
    message: str
    running: bool = False
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
