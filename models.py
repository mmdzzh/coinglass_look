from datetime import datetime
from sqlalchemy import (
    Column,
    BigInteger,
    Integer,
    DateTime,
    String,
    Numeric,
    Boolean,
    UniqueConstraint,
    Index,
)
from sqlalchemy import INTEGER
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class SymbolMeta(Base):
    __tablename__ = "symbol_meta"

    symbol = Column(String(20), primary_key=True)
    source = Column(String(20), primary_key=True, default="binance")
    base_asset = Column(String(20), nullable=True)
    quote_asset = Column(String(20), nullable=True)
    onboard_date = Column(DateTime(timezone=True), nullable=True)
    last_oi_sync_at = Column(DateTime(timezone=True), nullable=True)
    active = Column(Boolean, default=True)


class OpenInterest(Base):
    __tablename__ = "open_interest"

    id = Column(BigInteger().with_variant(INTEGER, "sqlite"), primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False)
    source = Column(String(20), nullable=False, default="binance")
    interval = Column(String(4), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    sum_open_interest = Column(Numeric(30, 8), nullable=True)
    sum_open_interest_value = Column(Numeric(30, 8), nullable=True)

    __table_args__ = (
        UniqueConstraint("symbol", "source", "interval", "timestamp", name="uix_oi_symbol_source_interval_time"),
        Index("ix_oi_symbol_source_interval_timestamp", "symbol", "source", "interval", "timestamp"),
        Index("ix_oi_symbol", "symbol"),
        Index("ix_oi_source", "source"),
        Index("ix_oi_interval", "interval"),
        Index("ix_oi_timestamp", "timestamp"),
    )
