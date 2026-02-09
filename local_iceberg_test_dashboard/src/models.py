# Iceberg Test Dashboard - Data Models
"""
Data models for the Iceberg Test Dashboard.

Uses dataclasses with type hints for all market data structures.
Requirements: 5.5, 9.2
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
import pytz

IST = pytz.timezone("Asia/Kolkata")


@dataclass
class SymbolTick:
    """Real-time tick data for a symbol.

    Attributes:
        symbol: Trading symbol (nifty, banknifty, sensex, finnifty)
        ltp: Last traded price
        change: Price change from previous close
        change_pct: Percentage change from previous close
        ts: Timestamp of the tick (IST)
    """

    symbol: str
    ltp: float
    change: float = 0.0
    change_pct: float = 0.0
    ts: datetime = field(default_factory=lambda: datetime.now(IST))

    def __post_init__(self):
        """Validate symbol is lowercase."""
        self.symbol = self.symbol.lower()


@dataclass
class IndicatorData:
    """Computed indicator values for a symbol/mode combination.

    Attributes:
        skew: COI-based positioning indicator (-1.0 to +1.0)
        raw_skew: Skew adjusted by price direction
        pcr: Put-Call Ratio from current OI
        adr: Advance/Decline Ratio
        signal: Trading signal (STRONG_BUY, BUY, NEUTRAL, SELL, STRONG_SELL)
        skew_confidence: Confidence level (0.0 to 1.0)
        rsi: Relative Strength Index (14-period)
        ema_5: 5-period EMA (legacy, use ema_9 instead)
        ema_9: 9-period EMA (FIX-023: correct column name)
        ema_13: 13-period EMA
        ema_21: 21-period EMA
        ema_50: 50-period EMA
        bb_upper: Bollinger Band upper
        bb_middle: Bollinger Band middle (20-period SMA)
        bb_lower: Bollinger Band lower
        vwap: Volume Weighted Average Price
        pivot_point: Standard pivot point
        intuition_text: AI-generated market insight text
        intuition_confidence: Confidence level for intuition (0.0 to 1.0) - FIX-042
        intuition_recommendations: LLM-generated strike recommendations - FIX-042
        ts: Timestamp of the indicator update (IST)
    """

    skew: Optional[float] = None
    raw_skew: Optional[float] = None
    pcr: Optional[float] = None
    adr: Optional[float] = None
    signal: str = "NEUTRAL"
    skew_confidence: float = 0.0
    rsi: Optional[float] = None
    ema_5: Optional[float] = None  # Legacy field, prefer ema_9
    ema_9: Optional[float] = None  # FIX-023: correct column name
    ema_13: Optional[float] = None
    ema_21: Optional[float] = None
    ema_50: Optional[float] = None
    bb_upper: Optional[float] = None
    bb_middle: Optional[float] = None
    bb_lower: Optional[float] = None
    vwap: Optional[float] = None
    pivot_point: Optional[float] = None
    intuition_text: Optional[str] = None  # AI-generated market insight
    intuition_confidence: Optional[float] = None  # FIX-042: Confidence for intuition
    intuition_recommendations: Optional[Dict[str, str]] = None  # FIX-042: {"low_risk": "23200CE", "medium_risk": "23300CE"}
    call_coi_sum: Optional[float] = None  # Sum of Call COI across strike range (from support_fields)
    put_coi_sum: Optional[float] = None  # Sum of Put COI across strike range (from support_fields)
    ts: datetime = field(default_factory=lambda: datetime.now(IST))


@dataclass
class OptionStrike:
    """Option chain data for a single strike price.

    Requirement 9.2: Table columns for option chain display.

    Attributes:
        strike: Strike price
        call_oi: Call open interest
        put_oi: Put open interest
        call_coi: Call change in open interest
        put_coi: Put change in open interest
        strike_skew: Per-strike skew value
        call_ltp: Call last traded price
        put_ltp: Put last traded price
    """

    strike: float
    call_oi: int = 0
    put_oi: int = 0
    call_coi: Optional[int] = None
    put_coi: Optional[int] = None
    strike_skew: Optional[float] = None
    call_ltp: Optional[float] = None
    put_ltp: Optional[float] = None
    signal: Optional[str] = None  # Per-strike signal: STRONG_BUY, BUY, NEUTRAL, SELL, STRONG_SELL


@dataclass
class OptionChainData:
    """Complete option chain for a symbol/mode combination.

    Attributes:
        expiry: Expiry date string (e.g., "2026-01-23")
        underlying: Current underlying price
        strikes: List of OptionStrike objects
        ts: Timestamp of the option chain update (IST)
    """

    expiry: str
    underlying: float
    strikes: List[OptionStrike] = field(default_factory=list)
    ts: datetime = field(default_factory=lambda: datetime.now(IST))


@dataclass
class Candle:
    """OHLCV candle data.

    Requirement 5.5: Columnar data parsing support.

    Attributes:
        ts: Candle timestamp (IST)
        open: Opening price
        high: High price
        low: Low price
        close: Closing price
        volume: Trading volume
    """

    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int = 0

    def to_columnar_entry(self) -> dict:
        """Convert to columnar format entry for round-trip testing."""
        return {
            "ts": self.ts.isoformat() if self.ts else None,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }


@dataclass
class SymbolData:
    """Aggregated data for a symbol/mode combination.

    Attributes:
        candles: List of OHLCV candles
        option_chain: Option chain data
        indicators: Current indicator values
    """

    candles: List[Candle] = field(default_factory=list)
    option_chain: Optional[OptionChainData] = None
    indicators: Optional[IndicatorData] = None


# Valid symbols as defined in product.md
VALID_SYMBOLS = ["nifty", "banknifty", "sensex", "finnifty"]

# Valid modes
VALID_MODES = ["current", "positional"]

# Valid signals
VALID_SIGNALS = ["STRONG_BUY", "BUY", "NEUTRAL", "SELL", "STRONG_SELL"]
