"""
Data models for the remediation service.

Uses Pydantic for validation and serialization.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field


class IndexCandle(BaseModel):
    """Index candle data from Breeze or DB."""
    
    symbol: str
    bucket_ts: datetime
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Optional[int] = None
    tick_count: Optional[int] = None


class OptionCandle(BaseModel):
    """Option candle data with OI from Breeze or DB."""
    
    symbol: str
    expiry: date
    strike: Decimal
    option_type: Literal["CE", "PE"]
    bucket_ts: datetime
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    # OI range during the 5-minute period
    oi_open: Optional[int] = None
    oi_high: Optional[int] = None
    oi_low: Optional[int] = None
    oi_close: Optional[int] = None
    # Volume range during the 5-minute period
    vol_open: Optional[int] = None
    vol_high: Optional[int] = None
    vol_low: Optional[int] = None
    vol_close: Optional[int] = None
    tick_count: Optional[int] = None


class StrikeRange(BaseModel):
    """Strike range from admin config or ATM calculation."""
    
    symbol: str
    mode: Literal["current", "positional"]
    lower_strike: Decimal
    upper_strike: Decimal
    source: Literal["admin", "atm_fallback"]
    effective_from: Optional[date] = None


class RemediationProgress(BaseModel):
    """Progress tracking for resumability."""
    
    run_id: str
    symbol: str
    trade_date: date
    expiry: Optional[date] = None
    strike: Optional[Decimal] = None
    option_type: Optional[str] = None
    status: Literal["pending", "in_progress", "completed", "failed"]
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class BreezeCandle(BaseModel):
    """Raw candle data from Breeze API response."""
    
    datetime: str
    stock_code: str
    exchange_code: str
    product_type: Optional[str] = None
    expiry_date: Optional[str] = None
    right: Optional[str] = None
    strike_price: Optional[str] = None
    open: str
    high: str
    low: str
    close: str
    volume: str = ""
    open_interest: Optional[str] = None
    count: int = 0


class ValidationResult(BaseModel):
    """Result of validating a candle against Breeze data."""
    
    symbol: str
    bucket_ts: datetime
    is_valid: bool
    differences: dict = Field(default_factory=dict)
    breeze_candle: Optional[dict] = None
    db_candle: Optional[dict] = None


class RemediationSummary(BaseModel):
    """Summary of a remediation run."""
    
    run_id: str
    symbol: str
    from_date: date
    to_date: date
    total_dates: int
    completed_dates: int
    failed_dates: int
    candles_validated: int
    candles_updated: int
    candles_inserted: int
    errors: list[str] = Field(default_factory=list)
    duration_seconds: float
