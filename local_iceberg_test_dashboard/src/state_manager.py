# Iceberg Test Dashboard - State Manager
"""
Thread-safe state container for real-time market data.

Manages shared state between WebSocket/SSE background threads and Dash callbacks.
Uses RLock for concurrent access to prevent race conditions.

Requirements: 10.4, 11.3, 12.4, 13.4, 15.2, 3.7, 3.9
"""

import base64
import json
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
import pytz

from .models import (
    SymbolTick,
    IndicatorData,
    OptionChainData,
    OptionStrike,
    Candle,
    VALID_SYMBOLS,
    VALID_MODES,
)

IST = pytz.timezone("Asia/Kolkata")

# Market hours constants
MARKET_START_MINUTES = 9 * 60 + 15  # 9:15 AM = 555 minutes
MARKET_END_MINUTES = 15 * 60 + 30   # 3:30 PM = 930 minutes
CANDLE_INTERVAL_MINUTES = 5


def floor_to_5min_boundary(ts: datetime) -> datetime:
    """Floor a timestamp to the nearest 5-minute candle boundary.
    
    Candles are aligned to market open (9:15, 9:20, 9:25, etc.)
    
    Args:
        ts: Timestamp to floor
        
    Returns:
        Timestamp floored to 5-minute boundary
    """
    # Get minutes since midnight
    total_minutes = ts.hour * 60 + ts.minute
    
    # Floor to 5-minute boundary
    floored_minutes = (total_minutes // CANDLE_INTERVAL_MINUTES) * CANDLE_INTERVAL_MINUTES
    
    # Create new timestamp with floored time
    return ts.replace(
        hour=floored_minutes // 60,
        minute=floored_minutes % 60,
        second=0,
        microsecond=0
    )

# JWT refresh threshold in seconds (1 hour = 3600 seconds)
JWT_REFRESH_THRESHOLD_SECONDS = 3600


@dataclass
class ConnectionStatus:
    """Connection status for streaming clients."""

    ws_connected: bool = False
    sse_connected: bool = False
    last_ws_update: Optional[datetime] = None
    last_sse_update: Optional[datetime] = None


@dataclass
class UserSession:
    """User session information for access control.
    
    Requirement 15.2: Track user role for admin access control.
    Requirement 3.7: Store JWT token securely in session state.
    """
    
    email: Optional[str] = None
    role: Optional[str] = None
    name: Optional[str] = None
    is_authenticated: bool = False
    jwt_token: Optional[str] = None
    jwt_expiry: Optional[datetime] = None


def parse_jwt_expiry(token: str) -> Optional[datetime]:
    """Parse expiry timestamp from JWT token.
    
    Requirement 3.9: Check JWT expiry for refresh logic.
    
    JWT format: header.payload.signature
    The payload contains the 'exp' claim with Unix timestamp.
    
    Args:
        token: JWT token string
        
    Returns:
        Expiry datetime in IST timezone if found, None otherwise
    """
    if not token:
        return None
    
    try:
        # JWT format: header.payload.signature
        parts = token.split('.')
        if len(parts) != 3:
            return None
        
        payload = parts[1]
        
        # Add padding if needed (base64 requires padding to be multiple of 4)
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += '=' * padding
        
        # Decode base64url to bytes
        decoded = base64.urlsafe_b64decode(payload)
        
        # Parse JSON payload
        claims = json.loads(decoded)
        
        # Get expiry timestamp
        exp = claims.get('exp')
        if exp:
            # Convert Unix timestamp to datetime in IST
            return datetime.fromtimestamp(exp, tz=IST)
    except Exception:
        # If any parsing fails, return None
        pass
    
    return None


def jwt_needs_refresh(expiry: Optional[datetime], threshold_seconds: int = JWT_REFRESH_THRESHOLD_SECONDS) -> bool:
    """Check if JWT token needs to be refreshed.
    
    Requirement 3.9: WHEN JWT token has less than 1 hour remaining,
    THE Dashboard SHALL refresh via POST /v1/auth/refresh.
    
    Property 3: JWT Refresh Threshold - When current time is within 1 hour
    of expiry (T - now < 3600 seconds), refresh SHALL be triggered.
    
    Args:
        expiry: JWT expiry datetime
        threshold_seconds: Seconds before expiry to trigger refresh (default 3600 = 1 hour)
        
    Returns:
        True if refresh is needed, False otherwise
    """
    if expiry is None:
        # No expiry info - don't trigger refresh
        return False
    
    now = datetime.now(IST)
    time_remaining = (expiry - now).total_seconds()
    
    # Refresh if less than threshold seconds remaining
    return time_remaining < threshold_seconds


@dataclass
class OTPSession:
    """OTP session information for admin operations.
    
    Requirement 15.8: Track OTP session expiry for re-verification prompts.
    """
    
    otp_verified: bool = False
    otp_expiry: Optional[datetime] = None
    verified_at: Optional[datetime] = None


@dataclass
class ErrorState:
    """Error state for tracking and displaying errors.
    
    Requirements:
        17.1: WHEN an API call fails, THE Dashboard SHALL display the error message without crashing
        5.6: IF bootstrap fails, THEN THE Dashboard SHALL display error and allow retry
    """
    
    has_error: bool = False
    error_message: Optional[str] = None
    error_type: Optional[str] = None  # 'bootstrap', 'api', 'websocket', 'sse', 'general'
    error_timestamp: Optional[datetime] = None
    can_retry: bool = True
    retry_count: int = 0
    max_retries: int = 3


@dataclass
class StalenessState:
    """Staleness state for tracking data freshness.
    
    Requirements:
        5.7: THE Dashboard SHALL display cache_stale warning from meta.cache_stale if true
        17.6: IF data is stale (>5 minutes old), THEN THE Dashboard SHALL display a staleness warning
    """
    
    # Cache stale flag from bootstrap response (Requirement 5.7)
    cache_stale: bool = False
    
    # Last data update timestamp for staleness detection (Requirement 17.6)
    last_data_update: Optional[datetime] = None
    
    # Staleness threshold in seconds (5 minutes = 300 seconds)
    staleness_threshold_seconds: int = 300


@dataclass
class DataGapState:
    """State for tracking data gaps and auto-bootstrap.
    
    FIX-032: Data Gap Detection & Auto-Bootstrap
    """
    
    # Last bootstrap attempt timestamp
    last_bootstrap_attempt: Optional[datetime] = None
    
    # Minimum interval between bootstrap attempts (2 minutes)
    bootstrap_cooldown_seconds: int = 120
    
    # Data gap threshold in seconds (5 minutes)
    gap_threshold_seconds: int = 300
    
    # Whether a data gap is currently detected
    has_gap: bool = False
    
    # Type of gap detected (skew, pcr, candles, indicators)
    gap_type: Optional[str] = None
    
    # Gap details for display
    gap_message: Optional[str] = None


@dataclass
class MarketInfoState:
    """Market info state from API response meta.
    
    FIX-043: Market Info Exposure & Positional Last Trading Day
    
    Stores market calendar information from bootstrap/health responses.
    """
    
    # Current market state (OPEN, CLOSED, PRE_MARKET, POST_MARKET, HOLIDAY, WEEKEND, UNKNOWN)
    market_state: str = "UNKNOWN"
    
    # Whether today is a trading day (not weekend/holiday)
    is_trading_day: Optional[bool] = None
    
    # Holiday name if today is a holiday
    holiday_name: Optional[str] = None
    
    # Previous trading day in YYYY-MM-DD format
    previous_trading_day: Optional[str] = None
    
    # Last update timestamp
    last_updated: Optional[datetime] = None


class StateManager:
    """Thread-safe state container for real-time dashboard data.

    This class manages all shared state between:
    - WebSocket client (fast stream - LTP updates)
    - SSE client (slow stream - indicator updates)
    - Dash callbacks (UI updates)

    All public methods are thread-safe using RLock for concurrent access.

    Requirements:
        10.4: Symbol selector updates LTPs in real-time from WebSocket tick events
        11.3: WebSocket tick events update corresponding symbol LTP
        12.4: SSE indicator_update events update indicator display
        13.4: Maintain separate data stores for current and positional modes

    Attributes:
        symbols_ltp: Dict mapping symbol -> SymbolTick with latest LTP
        indicators: Dict mapping symbol -> mode -> IndicatorData
        option_chains: Dict mapping symbol -> mode -> OptionChainData
        candles: Dict mapping symbol -> List[Candle]
        ema_history: Dict mapping symbol -> List of (ts, ema_5, ema_21) tuples
        connection_status: Current connection status for WS and SSE
        market_state: Current market state (OPEN, CLOSED, UNKNOWN)
    """

    def __init__(self):
        """Initialize state manager with empty state containers."""
        self._lock = threading.RLock()

        # Symbol LTP data (Requirement 10.4, 11.3)
        self.symbols_ltp: Dict[str, SymbolTick] = {}

        # Indicator data per symbol/mode (Requirement 12.4, 13.4)
        # Structure: {symbol: {mode: IndicatorData}}
        self.indicators: Dict[str, Dict[str, IndicatorData]] = {}

        # Option chain data per symbol/mode (Requirement 13.4)
        # Structure: {symbol: {mode: OptionChainData}}
        self.option_chains: Dict[str, Dict[str, OptionChainData]] = {}

        # Candle data per symbol
        self.candles: Dict[str, List[Candle]] = {}

        # EMA history for charting: (timestamp, ema_5, ema_21)
        self.ema_history: Dict[str, List[Tuple[datetime, float, float]]] = {}

        # Skew/PCR history for charting: (timestamp, skew, pcr)
        # Requirement 8.1, 8.2: Track Skew and PCR values over time for timeseries display
        self.skew_pcr_history: Dict[str, Dict[str, List[Tuple[datetime, float, float]]]] = {}

        # ADR history for charting: (timestamp, adr)
        # ADR is symbol-level (not mode-specific)
        self.adr_history: Dict[str, List[Tuple[datetime, float]]] = {}

        # RSI history for charting: (timestamp, rsi)
        # RSI is symbol-level (not mode-specific)
        self.rsi_history: Dict[str, List[Tuple[datetime, float]]] = {}

        # Connection status
        self.connection_status = ConnectionStatus()

        # Market state
        self.market_state: str = "UNKNOWN"
        
        # User session (Requirement 15.2)
        self.user_session = UserSession()
        
        # OTP session (Requirement 15.8)
        self.otp_session = OTPSession()
        
        # Error state (Requirements 17.1, 5.6)
        self.error_state = ErrorState()
        
        # Staleness state (Requirements 5.7, 17.6)
        self.staleness_state = StalenessState()
        
        # Data gap state (FIX-032)
        self.data_gap_state = DataGapState()
        
        # Market info state (FIX-043)
        self.market_info_state = MarketInfoState()

        # Initialize empty structures for all valid symbols
        self._initialize_symbols()

    def _initialize_symbols(self) -> None:
        """Initialize empty data structures for all valid symbols."""
        for symbol in VALID_SYMBOLS:
            self.indicators[symbol] = {}
            self.option_chains[symbol] = {}
            self.candles[symbol] = []
            self.ema_history[symbol] = []
            self.skew_pcr_history[symbol] = {}
            self.adr_history[symbol] = []
            self.rsi_history[symbol] = []
            for mode in VALID_MODES:
                self.indicators[symbol][mode] = IndicatorData()
                self.option_chains[symbol][mode] = OptionChainData(
                    expiry="", underlying=0.0
                )
                self.skew_pcr_history[symbol][mode] = []

    def update_ltp(
        self,
        symbol: str,
        ltp: float,
        change: float = 0.0,
        change_pct: float = 0.0,
        ts: Optional[datetime] = None,
    ) -> None:
        """Update LTP for a symbol from WebSocket tick event.

        Thread-safe update of symbol LTP data.

        Requirement 11.3: WHEN receiving a tick event, THE Dashboard SHALL
        update the corresponding symbol LTP.

        Args:
            symbol: Trading symbol (lowercase)
            ltp: Last traded price
            change: Price change from previous close
            change_pct: Percentage change from previous close
            ts: Timestamp of the tick (defaults to now in IST)
        """
        symbol = symbol.lower()
        if ts is None:
            ts = datetime.now(IST)

        with self._lock:
            self.symbols_ltp[symbol] = SymbolTick(
                symbol=symbol,
                ltp=ltp,
                change=change,
                change_pct=change_pct,
                ts=ts,
            )
            self.connection_status.last_ws_update = ts
            # Update staleness tracking (Requirement 17.6)
            self.staleness_state.last_data_update = ts

    def update_indicators(
        self,
        symbol: str,
        mode: str,
        indicators: IndicatorData,
    ) -> None:
        """Update indicator data for a symbol/mode combination.

        Thread-safe update of indicator data. Maintains separate data
        for current and positional modes per Requirement 13.4.
        
        History entries are aligned to 5-minute candle boundaries and
        deduplicated (last value wins for each candle bucket).

        Requirement 12.4: WHEN receiving an indicator_update event,
        THE Dashboard SHALL update indicator display.

        Requirement 13.4: THE Dashboard SHALL maintain separate data
        stores for current and positional modes.

        Args:
            symbol: Trading symbol (lowercase)
            mode: Expiry mode ('current' or 'positional')
            indicators: IndicatorData object with updated values
        """
        symbol = symbol.lower()
        mode = mode.lower()

        with self._lock:
            if symbol not in self.indicators:
                self.indicators[symbol] = {}
            self.indicators[symbol][mode] = indicators
            self.connection_status.last_sse_update = indicators.ts
            # Update staleness tracking (Requirement 17.6)
            if indicators.ts:
                self.staleness_state.last_data_update = indicators.ts

            # Align timestamp to 5-minute candle boundary for history
            candle_ts = floor_to_5min_boundary(indicators.ts) if indicators.ts else None

            # Update EMA history for charting (candle-aligned, deduplicated)
            if indicators.ema_5 is not None and indicators.ema_21 is not None and candle_ts:
                if symbol not in self.ema_history:
                    self.ema_history[symbol] = []
                
                # Check if we already have an entry for this candle bucket
                # If so, update it (last value wins); otherwise append
                existing_idx = None
                for idx, (ts, _, _) in enumerate(self.ema_history[symbol]):
                    if ts == candle_ts:
                        existing_idx = idx
                        break
                
                if existing_idx is not None:
                    # Update existing entry
                    self.ema_history[symbol][existing_idx] = (candle_ts, indicators.ema_5, indicators.ema_21)
                else:
                    # Append new entry
                    self.ema_history[symbol].append(
                        (candle_ts, indicators.ema_5, indicators.ema_21)
                    )
                    # Keep only last 100 entries to prevent memory growth
                    if len(self.ema_history[symbol]) > 100:
                        self.ema_history[symbol] = self.ema_history[symbol][-100:]

            # Update Skew/PCR history for charting (candle-aligned, deduplicated)
            if indicators.skew is not None and indicators.pcr is not None and candle_ts:
                if symbol not in self.skew_pcr_history:
                    self.skew_pcr_history[symbol] = {}
                if mode not in self.skew_pcr_history[symbol]:
                    self.skew_pcr_history[symbol][mode] = []
                
                # Check if we already have an entry for this candle bucket
                # If so, update it (last value wins); otherwise append
                existing_idx = None
                for idx, (ts, _, _) in enumerate(self.skew_pcr_history[symbol][mode]):
                    if ts == candle_ts:
                        existing_idx = idx
                        break
                
                if existing_idx is not None:
                    # Update existing entry
                    self.skew_pcr_history[symbol][mode][existing_idx] = (candle_ts, indicators.skew, indicators.pcr)
                else:
                    # Append new entry
                    self.skew_pcr_history[symbol][mode].append(
                        (candle_ts, indicators.skew, indicators.pcr)
                    )
                    # Keep only last 100 entries to prevent memory growth
                    if len(self.skew_pcr_history[symbol][mode]) > 100:
                        self.skew_pcr_history[symbol][mode] = self.skew_pcr_history[symbol][mode][-100:]

            # Update ADR history for charting (candle-aligned, deduplicated)
            # ADR is symbol-level (not mode-specific)
            if indicators.adr is not None and candle_ts:
                if symbol not in self.adr_history:
                    self.adr_history[symbol] = []
                
                # Check if we already have an entry for this candle bucket
                existing_idx = None
                for idx, (ts, _) in enumerate(self.adr_history[symbol]):
                    if ts == candle_ts:
                        existing_idx = idx
                        break
                
                if existing_idx is not None:
                    self.adr_history[symbol][existing_idx] = (candle_ts, indicators.adr)
                else:
                    self.adr_history[symbol].append((candle_ts, indicators.adr))
                    if len(self.adr_history[symbol]) > 100:
                        self.adr_history[symbol] = self.adr_history[symbol][-100:]

            # Update RSI history for charting (candle-aligned, deduplicated)
            # RSI is symbol-level (not mode-specific)
            if indicators.rsi is not None and candle_ts:
                if symbol not in self.rsi_history:
                    self.rsi_history[symbol] = []
                
                # Check if we already have an entry for this candle bucket
                existing_idx = None
                for idx, (ts, _) in enumerate(self.rsi_history[symbol]):
                    if ts == candle_ts:
                        existing_idx = idx
                        break
                
                if existing_idx is not None:
                    self.rsi_history[symbol][existing_idx] = (candle_ts, indicators.rsi)
                else:
                    self.rsi_history[symbol].append((candle_ts, indicators.rsi))
                    if len(self.rsi_history[symbol]) > 100:
                        self.rsi_history[symbol] = self.rsi_history[symbol][-100:]

    def update_option_chain(
        self,
        symbol: str,
        mode: str,
        option_chain: OptionChainData,
    ) -> None:
        """Update option chain data for a symbol/mode combination.

        Thread-safe update of option chain data. Maintains separate data
        for current and positional modes per Requirement 13.4.

        Requirement 13.4: THE Dashboard SHALL maintain separate data
        stores for current and positional modes.

        Args:
            symbol: Trading symbol (lowercase)
            mode: Expiry mode ('current' or 'positional')
            option_chain: OptionChainData object with updated values
        """
        symbol = symbol.lower()
        mode = mode.lower()

        with self._lock:
            if symbol not in self.option_chains:
                self.option_chains[symbol] = {}
            self.option_chains[symbol][mode] = option_chain

    def update_option_chain_ltp(
        self,
        symbol: str,
        mode: str,
        strike_ltps: Dict[float, Tuple[Optional[float], Optional[float]]],
    ) -> None:
        """Update option chain LTP values from WebSocket event.

        Updates call_ltp and put_ltp for specific strikes without
        replacing the entire option chain.

        Args:
            symbol: Trading symbol (lowercase)
            mode: Expiry mode ('current' or 'positional')
            strike_ltps: Dict mapping strike -> (call_ltp, put_ltp)
        """
        symbol = symbol.lower()
        mode = mode.lower()

        with self._lock:
            if symbol not in self.option_chains:
                return
            if mode not in self.option_chains[symbol]:
                return

            option_chain = self.option_chains[symbol][mode]
            for strike_obj in option_chain.strikes:
                if strike_obj.strike in strike_ltps:
                    call_ltp, put_ltp = strike_ltps[strike_obj.strike]
                    if call_ltp is not None:
                        strike_obj.call_ltp = call_ltp
                    if put_ltp is not None:
                        strike_obj.put_ltp = put_ltp

    def update_candles(self, symbol: str, candles: List[Candle]) -> None:
        """Update candle data for a symbol.

        Thread-safe replacement of candle data.

        Args:
            symbol: Trading symbol (lowercase)
            candles: List of Candle objects
        """
        symbol = symbol.lower()

        with self._lock:
            self.candles[symbol] = candles

    def append_candle(self, symbol: str, candle: Candle) -> None:
        """Append a new candle to symbol's candle list.

        Thread-safe append of a single candle.

        Args:
            symbol: Trading symbol (lowercase)
            candle: Candle object to append
        """
        symbol = symbol.lower()

        with self._lock:
            if symbol not in self.candles:
                self.candles[symbol] = []
            self.candles[symbol].append(candle)

    def set_ws_connected(self, connected: bool) -> None:
        """Update WebSocket connection status.

        Args:
            connected: True if connected, False otherwise
        """
        with self._lock:
            self.connection_status.ws_connected = connected
            if connected:
                self.connection_status.last_ws_update = datetime.now(IST)

    def set_sse_connected(self, connected: bool) -> None:
        """Update SSE connection status.

        Args:
            connected: True if connected, False otherwise
        """
        with self._lock:
            self.connection_status.sse_connected = connected
            if connected:
                self.connection_status.last_sse_update = datetime.now(IST)

    def set_market_state(self, state: str) -> None:
        """Update market state.

        Args:
            state: Market state (OPEN, CLOSED, UNKNOWN)
        """
        with self._lock:
            self.market_state = state

    # Read methods (also thread-safe for consistency)

    def get_ltp(self, symbol: str) -> Optional[SymbolTick]:
        """Get current LTP data for a symbol.

        Args:
            symbol: Trading symbol (lowercase)

        Returns:
            SymbolTick if available, None otherwise
        """
        symbol = symbol.lower()
        with self._lock:
            return self.symbols_ltp.get(symbol)

    def get_all_ltps(self) -> Dict[str, SymbolTick]:
        """Get all current LTP data.

        Returns:
            Copy of symbols_ltp dict
        """
        with self._lock:
            return dict(self.symbols_ltp)

    def get_indicators(self, symbol: str, mode: str) -> Optional[IndicatorData]:
        """Get indicator data for a symbol/mode combination.

        Args:
            symbol: Trading symbol (lowercase)
            mode: Expiry mode ('current' or 'positional')

        Returns:
            IndicatorData if available, None otherwise
        """
        symbol = symbol.lower()
        mode = mode.lower()
        with self._lock:
            if symbol in self.indicators and mode in self.indicators[symbol]:
                return self.indicators[symbol][mode]
            return None

    def get_option_chain(self, symbol: str, mode: str) -> Optional[OptionChainData]:
        """Get option chain data for a symbol/mode combination.

        Args:
            symbol: Trading symbol (lowercase)
            mode: Expiry mode ('current' or 'positional')

        Returns:
            OptionChainData if available, None otherwise
        """
        symbol = symbol.lower()
        mode = mode.lower()
        with self._lock:
            if symbol in self.option_chains and mode in self.option_chains[symbol]:
                return self.option_chains[symbol][mode]
            return None

    def get_candles(self, symbol: str) -> List[Candle]:
        """Get candle data for a symbol.

        Args:
            symbol: Trading symbol (lowercase)

        Returns:
            List of Candle objects (copy)
        """
        symbol = symbol.lower()
        with self._lock:
            return list(self.candles.get(symbol, []))

    def get_ema_history(self, symbol: str) -> List[Tuple[datetime, float, float]]:
        """Get EMA history for a symbol.

        Args:
            symbol: Trading symbol (lowercase)

        Returns:
            List of (timestamp, ema_5, ema_21) tuples (copy), sorted by timestamp
        """
        symbol = symbol.lower()
        with self._lock:
            if symbol in self.ema_history:
                # Return sorted copy to ensure proper chart rendering
                return sorted(self.ema_history[symbol], key=lambda x: x[0])
            return []

    def get_skew_pcr_history(self, symbol: str, mode: str) -> List[Tuple[datetime, float, float]]:
        """Get Skew/PCR history for a symbol/mode combination.

        Requirement 8.1, 8.2: Provide Skew and PCR timeseries data for charting.

        Args:
            symbol: Trading symbol (lowercase)
            mode: Expiry mode ('current' or 'positional')

        Returns:
            List of (timestamp, skew, pcr) tuples (copy), sorted by timestamp
        """
        symbol = symbol.lower()
        mode = mode.lower()
        with self._lock:
            if symbol in self.skew_pcr_history and mode in self.skew_pcr_history[symbol]:
                # Return sorted copy to ensure proper chart rendering
                return sorted(self.skew_pcr_history[symbol][mode], key=lambda x: x[0])
            return []

    def get_adr_history(self, symbol: str) -> List[Tuple[datetime, float]]:
        """Get ADR history for a symbol.

        ADR is symbol-level (not mode-specific).

        Args:
            symbol: Trading symbol (lowercase)

        Returns:
            List of (timestamp, adr) tuples (copy), sorted by timestamp
        """
        symbol = symbol.lower()
        with self._lock:
            if symbol in self.adr_history:
                return sorted(self.adr_history[symbol], key=lambda x: x[0])
            return []

    def get_rsi_history(self, symbol: str) -> List[Tuple[datetime, float]]:
        """Get RSI history for a symbol.

        RSI is symbol-level (not mode-specific).

        Args:
            symbol: Trading symbol (lowercase)

        Returns:
            List of (timestamp, rsi) tuples (copy), sorted by timestamp
        """
        symbol = symbol.lower()
        with self._lock:
            if symbol in self.rsi_history:
                return sorted(self.rsi_history[symbol], key=lambda x: x[0])
            return []

    def clear_indicator_history(self, symbol: Optional[str] = None, mode: Optional[str] = None) -> None:
        """Clear indicator history before re-populating from bootstrap.
        
        Call this before populating history from bootstrap to avoid duplicates.
        
        Args:
            symbol: If provided, clear only this symbol's history. If None, clear all.
            mode: If provided with symbol, clear only this mode's skew/pcr history.
        """
        with self._lock:
            if symbol is None:
                # Clear all history
                for sym in VALID_SYMBOLS:
                    self.ema_history[sym] = []
                    self.adr_history[sym] = []
                    self.rsi_history[sym] = []
                    for m in VALID_MODES:
                        if sym in self.skew_pcr_history and m in self.skew_pcr_history[sym]:
                            self.skew_pcr_history[sym][m] = []
            else:
                symbol = symbol.lower()
                # Clear specific symbol's EMA, ADR, RSI history
                if symbol in self.ema_history:
                    self.ema_history[symbol] = []
                if symbol in self.adr_history:
                    self.adr_history[symbol] = []
                if symbol in self.rsi_history:
                    self.rsi_history[symbol] = []
                
                # Clear specific symbol/mode's skew/pcr history
                if mode is not None:
                    mode = mode.lower()
                    if symbol in self.skew_pcr_history and mode in self.skew_pcr_history[symbol]:
                        self.skew_pcr_history[symbol][mode] = []
                else:
                    # Clear all modes for this symbol
                    if symbol in self.skew_pcr_history:
                        for m in VALID_MODES:
                            if m in self.skew_pcr_history[symbol]:
                                self.skew_pcr_history[symbol][m] = []

    def get_connection_status(self) -> ConnectionStatus:
        """Get current connection status.

        Returns:
            Copy of ConnectionStatus
        """
        with self._lock:
            return ConnectionStatus(
                ws_connected=self.connection_status.ws_connected,
                sse_connected=self.connection_status.sse_connected,
                last_ws_update=self.connection_status.last_ws_update,
                last_sse_update=self.connection_status.last_sse_update,
            )

    def get_market_state(self) -> str:
        """Get current market state.

        Returns:
            Market state string (OPEN, CLOSED, UNKNOWN)
        """
        with self._lock:
            return self.market_state

    # User session methods (Requirement 15.2, 3.7, 3.9)

    def set_user_session(
        self,
        email: Optional[str] = None,
        role: Optional[str] = None,
        name: Optional[str] = None,
        jwt_token: Optional[str] = None,
        jwt_expiry: Optional[datetime] = None,
    ) -> None:
        """Set user session information.
        
        Requirement 15.2: Track user role for admin access control.
        Requirement 3.7: Store JWT token securely in session state.
        Requirement 3.9: Track JWT expiry for refresh logic.

        Args:
            email: User email address
            role: User role (admin, customer, test_customer)
            name: User display name
            jwt_token: JWT authentication token
            jwt_expiry: JWT token expiry datetime (auto-parsed from token if not provided)
        """
        with self._lock:
            self.user_session.email = email
            self.user_session.role = role
            self.user_session.name = name
            self.user_session.jwt_token = jwt_token
            
            # Auto-parse JWT expiry if not provided (Requirement 3.9)
            if jwt_expiry is not None:
                self.user_session.jwt_expiry = jwt_expiry
            elif jwt_token is not None:
                self.user_session.jwt_expiry = parse_jwt_expiry(jwt_token)
            else:
                self.user_session.jwt_expiry = None
            
            self.user_session.is_authenticated = email is not None and jwt_token is not None

    def get_user_session(self) -> UserSession:
        """Get current user session information.
        
        Returns:
            Copy of UserSession
        """
        with self._lock:
            return UserSession(
                email=self.user_session.email,
                role=self.user_session.role,
                name=self.user_session.name,
                is_authenticated=self.user_session.is_authenticated,
                jwt_token=self.user_session.jwt_token,
                jwt_expiry=self.user_session.jwt_expiry,
            )

    def is_admin(self) -> bool:
        """Check if current user has admin role.
        
        Requirement 15.2: Admin page SHALL only be accessible to users with admin role.

        Returns:
            True if user has admin role, False otherwise
        """
        with self._lock:
            return (
                self.user_session.is_authenticated 
                and self.user_session.role == "admin"
            )

    def jwt_needs_refresh(self) -> bool:
        """Check if JWT token needs to be refreshed.
        
        Requirement 3.9: WHEN JWT token has less than 1 hour remaining,
        THE Dashboard SHALL refresh via POST /v1/auth/refresh.
        
        Returns:
            True if refresh is needed (< 1 hour remaining), False otherwise
        """
        with self._lock:
            if not self.user_session.is_authenticated:
                return False
            return jwt_needs_refresh(self.user_session.jwt_expiry)

    def update_jwt_token(self, new_token: str) -> None:
        """Update JWT token after refresh.
        
        Requirement 3.9: Update stored JWT after successful refresh.
        
        Args:
            new_token: New JWT token from refresh response
        """
        with self._lock:
            if not self.user_session.is_authenticated:
                return
            
            self.user_session.jwt_token = new_token
            self.user_session.jwt_expiry = parse_jwt_expiry(new_token)

    def get_jwt_expiry_info(self) -> Tuple[Optional[datetime], Optional[int]]:
        """Get JWT expiry information.
        
        Returns:
            Tuple of (expiry datetime, seconds remaining) or (None, None) if not authenticated
        """
        with self._lock:
            if not self.user_session.is_authenticated or not self.user_session.jwt_expiry:
                return None, None
            
            expiry = self.user_session.jwt_expiry
            now = datetime.now(IST)
            seconds_remaining = int((expiry - now).total_seconds())
            
            return expiry, seconds_remaining

    def clear_user_session(self) -> None:
        """Clear user session information (logout).
        """
        with self._lock:
            self.user_session = UserSession()

    # OTP session methods (Requirement 15.8)

    def set_otp_verified(
        self,
        verified: bool = True,
        expiry: Optional[datetime] = None,
    ) -> None:
        """Set OTP verification status.
        
        Requirement 15.8: Track OTP session expiry for re-verification prompts.

        Args:
            verified: Whether OTP has been verified
            expiry: OTP session expiry datetime
        """
        with self._lock:
            self.otp_session.otp_verified = verified
            self.otp_session.otp_expiry = expiry
            if verified:
                self.otp_session.verified_at = datetime.now(IST)
            else:
                self.otp_session.verified_at = None

    def get_otp_session(self) -> OTPSession:
        """Get current OTP session information.
        
        Returns:
            Copy of OTPSession
        """
        with self._lock:
            return OTPSession(
                otp_verified=self.otp_session.otp_verified,
                otp_expiry=self.otp_session.otp_expiry,
                verified_at=self.otp_session.verified_at,
            )

    def is_otp_session_valid(self) -> bool:
        """Check if OTP session is valid (verified and not expired).
        
        Requirement 15.8: IF OTP session expires, THEN Admin page SHALL prompt
        for re-verification.

        Returns:
            True if OTP session is valid, False otherwise
        """
        with self._lock:
            if not self.otp_session.otp_verified:
                return False
            
            if self.otp_session.otp_expiry is None:
                # No expiry set - session is valid
                return True
            
            # Check if session has expired
            now = datetime.now(IST)
            return now < self.otp_session.otp_expiry

    def clear_otp_session(self) -> None:
        """Clear OTP session information.
        
        Used when OTP session expires or user logs out.
        """
        with self._lock:
            self.otp_session = OTPSession()

    # Error state methods (Requirements 17.1, 5.6)

    def set_error(
        self,
        message: str,
        error_type: str = "general",
        can_retry: bool = True,
    ) -> None:
        """Set an error state for display.
        
        Requirements:
            17.1: WHEN an API call fails, THE Dashboard SHALL display the error message without crashing
            5.6: IF bootstrap fails, THEN THE Dashboard SHALL display error and allow retry
        
        Args:
            message: Error message to display
            error_type: Type of error ('bootstrap', 'api', 'websocket', 'sse', 'general')
            can_retry: Whether the operation can be retried
        """
        with self._lock:
            self.error_state.has_error = True
            self.error_state.error_message = message
            self.error_state.error_type = error_type
            self.error_state.error_timestamp = datetime.now(IST)
            self.error_state.can_retry = can_retry
            self.error_state.retry_count += 1

    def clear_error(self) -> None:
        """Clear the current error state.
        
        Called when an operation succeeds or user dismisses the error.
        """
        with self._lock:
            self.error_state = ErrorState()

    def get_error_state(self) -> ErrorState:
        """Get the current error state.
        
        Returns:
            Copy of ErrorState
        """
        with self._lock:
            return ErrorState(
                has_error=self.error_state.has_error,
                error_message=self.error_state.error_message,
                error_type=self.error_state.error_type,
                error_timestamp=self.error_state.error_timestamp,
                can_retry=self.error_state.can_retry,
                retry_count=self.error_state.retry_count,
                max_retries=self.error_state.max_retries,
            )

    def has_error(self) -> bool:
        """Check if there is an active error.
        
        Returns:
            True if there is an error, False otherwise
        """
        with self._lock:
            return self.error_state.has_error

    def can_retry_operation(self) -> bool:
        """Check if the failed operation can be retried.
        
        Requirement 17.2: Implement retry logic for failed API calls (3 attempts with backoff)
        
        Returns:
            True if retry is allowed, False otherwise
        """
        with self._lock:
            return (
                self.error_state.can_retry 
                and self.error_state.retry_count < self.error_state.max_retries
            )

    def increment_retry_count(self) -> int:
        """Increment the retry count and return the new value.
        
        Returns:
            New retry count
        """
        with self._lock:
            self.error_state.retry_count += 1
            return self.error_state.retry_count

    # Staleness state methods (Requirements 5.7, 17.6)

    def set_cache_stale(self, stale: bool) -> None:
        """Set the cache_stale flag from bootstrap response.
        
        Requirement 5.7: THE Dashboard SHALL display cache_stale warning 
        from meta.cache_stale if true.
        
        Args:
            stale: Whether the cache is stale
        """
        with self._lock:
            self.staleness_state.cache_stale = stale

    def update_last_data_timestamp(self, ts: Optional[datetime] = None) -> None:
        """Update the last data update timestamp.
        
        Requirement 17.6: Track data freshness for staleness detection.
        
        Args:
            ts: Timestamp of the data update (defaults to now in IST)
        """
        with self._lock:
            if ts is None:
                ts = datetime.now(IST)
            self.staleness_state.last_data_update = ts

    def is_data_stale(self) -> bool:
        """Check if data is stale (>5 minutes old).
        
        Requirement 17.6: IF data is stale (>5 minutes old), THEN THE Dashboard 
        SHALL display a staleness warning.
        
        Returns:
            True if data is stale, False otherwise
        """
        with self._lock:
            if self.staleness_state.last_data_update is None:
                # No data yet - consider stale
                return True
            
            now = datetime.now(IST)
            age = (now - self.staleness_state.last_data_update).total_seconds()
            return age > self.staleness_state.staleness_threshold_seconds

    def is_cache_stale(self) -> bool:
        """Check if cache_stale flag is set from bootstrap.
        
        Requirement 5.7: THE Dashboard SHALL display cache_stale warning 
        from meta.cache_stale if true.
        
        Returns:
            True if cache is marked as stale, False otherwise
        """
        with self._lock:
            return self.staleness_state.cache_stale

    def get_staleness_state(self) -> StalenessState:
        """Get the current staleness state.
        
        Returns:
            Copy of StalenessState
        """
        with self._lock:
            return StalenessState(
                cache_stale=self.staleness_state.cache_stale,
                last_data_update=self.staleness_state.last_data_update,
                staleness_threshold_seconds=self.staleness_state.staleness_threshold_seconds,
            )

    def get_data_age_seconds(self) -> Optional[int]:
        """Get the age of the last data update in seconds.
        
        Returns:
            Age in seconds, or None if no data has been received
        """
        with self._lock:
            if self.staleness_state.last_data_update is None:
                return None
            
            now = datetime.now(IST)
            return int((now - self.staleness_state.last_data_update).total_seconds())

    def should_show_staleness_warning(self) -> bool:
        """Check if a staleness warning should be displayed.
        
        Requirements:
            5.7: Display cache_stale warning from meta.cache_stale if true
            17.6: Display staleness warning if data is >5 minutes old
        
        Returns:
            True if any staleness warning should be shown, False otherwise
        """
        with self._lock:
            # Check cache_stale flag from bootstrap (Requirement 5.7)
            if self.staleness_state.cache_stale:
                return True
            
            # Check data age (Requirement 17.6)
            if self.staleness_state.last_data_update is None:
                return False  # No data yet, don't show warning
            
            now = datetime.now(IST)
            age = (now - self.staleness_state.last_data_update).total_seconds()
            return age > self.staleness_state.staleness_threshold_seconds

    # Data Gap Detection methods (FIX-032)

    def is_market_open(self) -> bool:
        """Check if Indian market is currently open.
        
        Market hours: 09:15 - 15:30 IST, Monday-Friday
        
        Returns:
            True if market is open, False otherwise
        """
        now = datetime.now(IST)
        
        # Check if it's a weekday (Monday=0, Sunday=6)
        if now.weekday() >= 5:  # Saturday or Sunday
            return False
        
        # Check market hours
        current_minutes = now.hour * 60 + now.minute
        return MARKET_START_MINUTES <= current_minutes <= MARKET_END_MINUTES

    def detect_data_gaps(self, symbol: str, mode: str) -> Dict[str, Any]:
        """Detect gaps in indicator data for a symbol/mode.
        
        FIX-032: Data Gap Detection
        
        Checks if indicator data (skew, pcr) is missing or stale during market hours.
        
        Args:
            symbol: Trading symbol (lowercase)
            mode: Expiry mode ('current' or 'positional')
        
        Returns:
            Dict with gap detection results:
            {
                "has_gap": bool,
                "gap_type": str | None,  # "indicators", "skew_pcr", "candles"
                "last_data_time": datetime | None,
                "gap_minutes": int | None,
                "message": str | None,
            }
        """
        symbol = symbol.lower()
        mode = mode.lower()
        
        with self._lock:
            result = {
                "has_gap": False,
                "gap_type": None,
                "last_data_time": None,
                "gap_minutes": None,
                "message": None,
            }
            
            # Only check during market hours
            if not self.is_market_open():
                return result
            
            now = datetime.now(IST)
            gap_threshold = self.data_gap_state.gap_threshold_seconds
            
            # Check indicator data
            indicators = self.indicators.get(symbol, {}).get(mode)
            if indicators and indicators.ts:
                age_seconds = (now - indicators.ts).total_seconds()
                if age_seconds > gap_threshold:
                    result["has_gap"] = True
                    result["gap_type"] = "indicators"
                    result["last_data_time"] = indicators.ts
                    result["gap_minutes"] = int(age_seconds / 60)
                    result["message"] = f"Indicator data is {result['gap_minutes']} minutes old"
                    return result
            elif indicators is None or indicators.ts is None:
                # No indicator data at all
                result["has_gap"] = True
                result["gap_type"] = "indicators"
                result["message"] = "No indicator data available"
                return result
            
            # Check skew/pcr history
            skew_pcr = self.skew_pcr_history.get(symbol, {}).get(mode, [])
            if skew_pcr:
                last_entry = max(skew_pcr, key=lambda x: x[0])
                age_seconds = (now - last_entry[0]).total_seconds()
                if age_seconds > gap_threshold:
                    result["has_gap"] = True
                    result["gap_type"] = "skew_pcr"
                    result["last_data_time"] = last_entry[0]
                    result["gap_minutes"] = int(age_seconds / 60)
                    result["message"] = f"Skew/PCR data is {result['gap_minutes']} minutes old"
                    return result
            
            return result

    def should_auto_bootstrap(self) -> bool:
        """Check if auto-bootstrap should be triggered.
        
        FIX-032: Auto-Bootstrap Trigger
        
        Conditions:
        1. Market is OPEN
        2. Data gap detected (>5 minutes without updates)
        3. Last bootstrap was >2 minutes ago (prevent spam)
        4. User is authenticated
        
        Returns:
            True if auto-bootstrap should be triggered, False otherwise
        """
        with self._lock:
            # Must be authenticated
            if not self.user_session.is_authenticated:
                return False
            
            # Must be during market hours
            if not self.is_market_open():
                return False
            
            # Check cooldown period
            if self.data_gap_state.last_bootstrap_attempt:
                cooldown = self.data_gap_state.bootstrap_cooldown_seconds
                elapsed = (datetime.now(IST) - self.data_gap_state.last_bootstrap_attempt).total_seconds()
                if elapsed < cooldown:
                    return False
            
            # Check for data gaps in any symbol/mode
            for symbol in VALID_SYMBOLS:
                for mode in VALID_MODES:
                    gap_result = self.detect_data_gaps(symbol, mode)
                    if gap_result["has_gap"]:
                        # Update gap state
                        self.data_gap_state.has_gap = True
                        self.data_gap_state.gap_type = gap_result["gap_type"]
                        self.data_gap_state.gap_message = gap_result["message"]
                        return True
            
            # No gaps detected
            self.data_gap_state.has_gap = False
            self.data_gap_state.gap_type = None
            self.data_gap_state.gap_message = None
            return False

    def record_bootstrap_attempt(self) -> None:
        """Record a bootstrap attempt timestamp.
        
        FIX-032: Rate limiting for auto-bootstrap
        
        Called after triggering a bootstrap to prevent spam.
        """
        with self._lock:
            self.data_gap_state.last_bootstrap_attempt = datetime.now(IST)

    def get_data_gap_state(self) -> DataGapState:
        """Get the current data gap state.
        
        Returns:
            Copy of DataGapState
        """
        with self._lock:
            return DataGapState(
                last_bootstrap_attempt=self.data_gap_state.last_bootstrap_attempt,
                bootstrap_cooldown_seconds=self.data_gap_state.bootstrap_cooldown_seconds,
                gap_threshold_seconds=self.data_gap_state.gap_threshold_seconds,
                has_gap=self.data_gap_state.has_gap,
                gap_type=self.data_gap_state.gap_type,
                gap_message=self.data_gap_state.gap_message,
            )

    def clear_data_gap(self) -> None:
        """Clear the data gap state after successful bootstrap.
        """
        with self._lock:
            self.data_gap_state.has_gap = False
            self.data_gap_state.gap_type = None
            self.data_gap_state.gap_message = None

    # Market Info methods (FIX-043)

    def set_market_info(
        self,
        market_state: Optional[str] = None,
        is_trading_day: Optional[bool] = None,
        holiday_name: Optional[str] = None,
        previous_trading_day: Optional[str] = None,
    ) -> None:
        """Set market info from API response meta.
        
        FIX-043: Market Info Exposure & Positional Last Trading Day
        
        Args:
            market_state: Current market state (OPEN, CLOSED, etc.)
            is_trading_day: Whether today is a trading day
            holiday_name: Holiday name if today is a holiday
            previous_trading_day: Previous trading day in YYYY-MM-DD format
        """
        with self._lock:
            if market_state is not None:
                self.market_info_state.market_state = market_state
                # Also update the legacy market_state field
                self.market_state = market_state
            if is_trading_day is not None:
                self.market_info_state.is_trading_day = is_trading_day
            if holiday_name is not None:
                self.market_info_state.holiday_name = holiday_name
            if previous_trading_day is not None:
                self.market_info_state.previous_trading_day = previous_trading_day
            self.market_info_state.last_updated = datetime.now(IST)

    def get_market_info(self) -> MarketInfoState:
        """Get current market info state.
        
        Returns:
            Copy of MarketInfoState
        """
        with self._lock:
            return MarketInfoState(
                market_state=self.market_info_state.market_state,
                is_trading_day=self.market_info_state.is_trading_day,
                holiday_name=self.market_info_state.holiday_name,
                previous_trading_day=self.market_info_state.previous_trading_day,
                last_updated=self.market_info_state.last_updated,
            )

    def is_holiday(self) -> bool:
        """Check if today is a holiday.
        
        Returns:
            True if today is a holiday, False otherwise
        """
        with self._lock:
            return self.market_info_state.holiday_name is not None

    def get_holiday_name(self) -> Optional[str]:
        """Get the holiday name if today is a holiday.
        
        Returns:
            Holiday name or None
        """
        with self._lock:
            return self.market_info_state.holiday_name

    def clear(self) -> None:
        """Clear all state data.

        Useful for testing or resetting the dashboard.
        """
        with self._lock:
            self.symbols_ltp.clear()
            self.indicators.clear()
            self.option_chains.clear()
            self.candles.clear()
            self.ema_history.clear()
            self.skew_pcr_history.clear()
            self.adr_history.clear()
            self.rsi_history.clear()
            self.connection_status = ConnectionStatus()
            self.market_state = "UNKNOWN"
            self.user_session = UserSession()
            self.otp_session = OTPSession()
            self.error_state = ErrorState()
            self.staleness_state = StalenessState()
            self.data_gap_state = DataGapState()
            self.market_info_state = MarketInfoState()
            self._initialize_symbols()
