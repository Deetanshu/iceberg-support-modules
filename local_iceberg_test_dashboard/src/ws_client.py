# Iceberg Test Dashboard - WebSocket Client
"""
WebSocket client for the Iceberg Fast Stream.

Connects to /v1/stream/fast for real-time LTP updates.
Handles tick, option_chain_ltp, and snapshot events.
Implements ping/pong protocol and reconnection with exponential backoff.

Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 11.8, 11.9, 17.7
"""

import json
import threading
import time
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Tuple
import pytz

import structlog
import websocket

from .config import get_settings
from .state_manager import StateManager
from .models import VALID_SYMBOLS

# Requirement 17.7: Log all errors to console for debugging
logger = structlog.get_logger(__name__)
IST = pytz.timezone("Asia/Kolkata")


class FastStreamClient:
    """WebSocket client for /v1/stream/fast.

    Provides real-time LTP updates for all symbols via WebSocket connection.
    Implements automatic reconnection with exponential backoff.

    Requirements:
        11.1: Connect to wss://api.botbro.trade/v1/stream/fast with JWT token
        11.2: Subscribe to all 4 symbols in the connection
        11.3: Update corresponding symbol LTP on tick event
        11.4: Update option chain LTPs on option_chain_ltp event
        11.5: Respond to ping with pong within 60 seconds
        11.6: Refresh JWT and reconnect on close code 4001
        11.7: Display slow client warning on close code 4005
        11.8: Implement reconnection with exponential backoff (1s, 2s, 4s, 8s, max 30s)
        11.9: Proactively reconnect every 55 minutes before Cloud Run timeout

    Attributes:
        state: StateManager instance for updating shared state
        jwt_token: JWT token for authentication
        symbols: List of symbols to subscribe to
        ws: WebSocketApp instance
        running: Flag to control the client lifecycle
        reconnect_delay: Current reconnection delay in seconds
        last_connect_time: Timestamp of last successful connection
        on_jwt_refresh_needed: Callback for JWT refresh
        on_slow_client_warning: Callback for slow client warning
    """

    # Constants
    MAX_RECONNECT_DELAY = 30.0  # Maximum backoff delay in seconds
    PROACTIVE_RECONNECT_MINUTES = 55  # Reconnect before Cloud Run timeout
    PING_TIMEOUT = 60  # Seconds to respond to ping

    def __init__(
        self,
        state_manager: StateManager,
        jwt_token: str,
        symbols: Optional[List[str]] = None,
        on_jwt_refresh_needed: Optional[Callable[[], Optional[str]]] = None,
        on_slow_client_warning: Optional[Callable[[], None]] = None,
    ):
        """Initialize the FastStreamClient.

        Args:
            state_manager: StateManager instance for updating shared state
            jwt_token: JWT token for authentication
            symbols: List of symbols to subscribe to (defaults to all valid symbols)
            on_jwt_refresh_needed: Callback to refresh JWT token, returns new token
            on_slow_client_warning: Callback when slow client warning is received
        """
        self.state = state_manager
        self.jwt_token = jwt_token
        self.symbols = symbols or list(VALID_SYMBOLS)
        self.on_jwt_refresh_needed = on_jwt_refresh_needed
        self.on_slow_client_warning = on_slow_client_warning

        self.ws: Optional[websocket.WebSocketApp] = None
        self.running = False
        self.reconnect_delay = 1.0
        self.last_connect_time: Optional[datetime] = None
        self._thread: Optional[threading.Thread] = None
        self._reconnect_timer: Optional[threading.Timer] = None
        self._proactive_reconnect_timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()

    def _build_url(self) -> str:
        """Build WebSocket URL with token and symbols.

        Requirement 11.1: Connect to wss://api.botbro.trade/v1/stream/fast with JWT token
        Requirement 11.2: Subscribe to all 4 symbols in the connection

        Returns:
            WebSocket URL with query parameters
        """
        settings = get_settings()
        base_url = settings.ws_url
        symbols_param = ",".join(self.symbols)
        return f"{base_url}/v1/stream/fast?token={self.jwt_token}&symbols={symbols_param}"

    def connect(self) -> None:
        """Connect to the WebSocket stream.

        Starts the WebSocket connection in a background thread.
        """
        if self.running:
            logger.warning("FastStreamClient already running")
            return

        self.running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        """Run the WebSocket connection loop."""
        while self.running:
            try:
                url = self._build_url()
                logger.info("ws_connecting", url_prefix=url[:50])

                self.ws = websocket.WebSocketApp(
                    url,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                    on_open=self._on_open,
                )

                # Run with ping disabled (we handle ping/pong manually)
                self.ws.run_forever(ping_interval=0)

            except Exception as e:
                # Requirement 17.7: Log all errors to console for debugging
                logger.error("ws_connection_error", error=str(e), error_type=type(e).__name__)
                self.state.set_ws_connected(False)

            if self.running:
                self._schedule_reconnect()

    def _on_open(self, ws: websocket.WebSocketApp) -> None:
        """Handle WebSocket connection open.

        Args:
            ws: WebSocketApp instance
        """
        logger.info("ws_connected", symbols=self.symbols)
        self.state.set_ws_connected(True)
        self.last_connect_time = datetime.now(IST)
        self.reconnect_delay = 1.0  # Reset backoff on successful connection

        # Schedule proactive reconnection (Requirement 11.9)
        self._schedule_proactive_reconnect()

    def _on_message(self, ws: websocket.WebSocketApp, message: str) -> None:
        """Handle incoming WebSocket message.

        Requirement 11.3: Update corresponding symbol LTP on tick event
        Requirement 11.4: Update option chain LTPs on option_chain_ltp event
        Requirement 11.5: Respond to ping with pong within 60 seconds

        Args:
            ws: WebSocketApp instance
            message: Raw message string
        """
        try:
            data = json.loads(message)
            event = data.get("event")

            if event == "ping":
                self._handle_ping(ws)
            elif event == "tick":
                self._handle_tick(data)
            elif event == "option_chain_ltp":
                self._handle_option_chain_ltp(data)
            elif event == "snapshot":
                self._handle_snapshot(data)
            else:
                logger.debug("ws_unknown_event", event=event)

        except json.JSONDecodeError as e:
            # Requirement 17.7: Log all errors to console for debugging
            logger.error("ws_json_parse_error", error=str(e), message_preview=message[:100] if message else None)
        except Exception as e:
            # Requirement 17.7: Log all errors to console for debugging
            logger.error("ws_message_handling_error", error=str(e), error_type=type(e).__name__, event=data.get("event") if isinstance(data, dict) else None)

    def _handle_ping(self, ws: websocket.WebSocketApp) -> None:
        """Handle ping event by sending pong response.

        Requirement 11.5: Respond to ping with {"action": "pong"} within 60 seconds

        Args:
            ws: WebSocketApp instance
        """
        try:
            pong_message = json.dumps({"action": "pong"})
            ws.send(pong_message)
            logger.debug("ws_pong_sent")
        except Exception as e:
            # Requirement 17.7: Log all errors to console for debugging
            logger.error("ws_pong_send_error", error=str(e), error_type=type(e).__name__)

    def _handle_tick(self, data: dict) -> None:
        """Handle tick event to update symbol LTPs.

        Requirement 11.3: WHEN receiving a tick event, THE Dashboard SHALL
        update the corresponding symbol LTP.

        Args:
            data: Tick event data with structure:
                  {"event": "tick", "data": {symbol: {ltp, change, change_pct, ts}}}
        """
        tick_data = data.get("data", {})
        ts_str = data.get("ts") or data.get("timestamp")
        ts = self._parse_timestamp(ts_str)

        for symbol, tick in tick_data.items():
            if isinstance(tick, dict):
                ltp = tick.get("ltp", 0.0)
                change = tick.get("change", 0.0)
                change_pct = tick.get("change_pct", 0.0)
                tick_ts = self._parse_timestamp(tick.get("ts")) or ts

                self.state.update_ltp(
                    symbol=symbol,
                    ltp=ltp,
                    change=change,
                    change_pct=change_pct,
                    ts=tick_ts,
                )
                logger.debug("ws_ltp_updated", symbol=symbol, ltp=ltp)

    def _handle_option_chain_ltp(self, data: dict) -> None:
        """Handle option_chain_ltp event to update option LTPs.

        Requirement 11.4: WHEN receiving an option_chain_ltp event,
        THE Dashboard SHALL update option chain LTPs.

        API Spec format (columnar):
        {
          "event": "option_chain_ltp",
          "symbol": "nifty",
          "mode": "current",
          "data": {
            "strikes": [23900, 24000, 24100],
            "call_ltp": [161.50, 125.50, 95.25],
            "put_ltp": [85.25, 110.50, 145.75]
          }
        }

        Args:
            data: Option chain LTP event data
        """
        symbol = data.get("symbol", "").lower()
        mode = data.get("mode", "current").lower()
        
        # FIX: API uses columnar format in data.strikes, data.call_ltp, data.put_ltp
        data_obj = data.get("data", {})
        strikes_arr = data_obj.get("strikes", [])
        call_ltp_arr = data_obj.get("call_ltp", [])
        put_ltp_arr = data_obj.get("put_ltp", [])

        if not symbol or not strikes_arr:
            return

        # Build strike LTP mapping from columnar arrays
        strike_ltps: Dict[float, Tuple[Optional[float], Optional[float]]] = {}
        for i, strike in enumerate(strikes_arr):
            call_ltp = call_ltp_arr[i] if i < len(call_ltp_arr) else None
            put_ltp = put_ltp_arr[i] if i < len(put_ltp_arr) else None
            strike_ltps[float(strike)] = (call_ltp, put_ltp)

        self.state.update_option_chain_ltp(symbol, mode, strike_ltps)
        logger.debug("ws_option_chain_ltp_updated", symbol=symbol, mode=mode, strike_count=len(strike_ltps))

    def _handle_snapshot(self, data: dict) -> None:
        """Handle snapshot event with initial data.

        Args:
            data: Snapshot event data
        """
        # Snapshot handling - update all symbols with initial data
        snapshot_data = data.get("data", {})
        for symbol, symbol_data in snapshot_data.items():
            if isinstance(symbol_data, dict):
                ltp = symbol_data.get("ltp", 0.0)
                change = symbol_data.get("change", 0.0)
                change_pct = symbol_data.get("change_pct", 0.0)

                self.state.update_ltp(
                    symbol=symbol,
                    ltp=ltp,
                    change=change,
                    change_pct=change_pct,
                )
        logger.info("ws_snapshot_processed", symbol_count=len(snapshot_data))

    def _on_error(self, ws: websocket.WebSocketApp, error: Exception) -> None:
        """Handle WebSocket error.

        Requirement 17.7: Log all errors to console for debugging

        Args:
            ws: WebSocketApp instance
            error: Exception that occurred
        """
        logger.error("ws_error", error=str(error), error_type=type(error).__name__)
        self.state.set_ws_connected(False)

    def _on_close(
        self,
        ws: websocket.WebSocketApp,
        close_status_code: Optional[int],
        close_msg: Optional[str],
    ) -> None:
        """Handle WebSocket connection close.

        Requirement 11.6: Refresh JWT and reconnect on close code 4001
        Requirement 11.7: Display slow client warning on close code 4005

        Args:
            ws: WebSocketApp instance
            close_status_code: WebSocket close status code
            close_msg: Close message
        """
        logger.info("ws_closed", close_code=close_status_code, close_msg=close_msg)
        self.state.set_ws_connected(False)

        # Cancel proactive reconnect timer
        self._cancel_proactive_reconnect()

        if not self.running:
            return

        # Handle specific close codes
        if close_status_code == 4001:
            # JWT expired - try to refresh
            self._handle_jwt_expired()
        elif close_status_code == 4005:
            # Slow client warning
            self._handle_slow_client()

    def _handle_jwt_expired(self) -> None:
        """Handle JWT expired close code (4001).

        Requirement 11.6: IF WebSocket disconnects with code 4001,
        THEN THE Dashboard SHALL refresh JWT and reconnect.
        """
        logger.warning("ws_jwt_expired", close_code=4001)

        if self.on_jwt_refresh_needed:
            try:
                new_token = self.on_jwt_refresh_needed()
                if new_token:
                    self.jwt_token = new_token
                    self.reconnect_delay = 1.0  # Reset backoff for fresh token
                    logger.info("ws_jwt_refreshed")
                else:
                    # Requirement 17.7: Log all errors to console for debugging
                    logger.error("ws_jwt_refresh_no_token", error="JWT refresh callback returned no token")
            except Exception as e:
                # Requirement 17.7: Log all errors to console for debugging
                logger.error("ws_jwt_refresh_failed", error=str(e), error_type=type(e).__name__)

    def _handle_slow_client(self) -> None:
        """Handle slow client close code (4005).

        Requirement 11.7: IF WebSocket disconnects with code 4005,
        THEN THE Dashboard SHALL display slow client warning.
        """
        logger.warning("ws_slow_client_warning", close_code=4005)

        if self.on_slow_client_warning:
            try:
                self.on_slow_client_warning()
            except Exception as e:
                # Requirement 17.7: Log all errors to console for debugging
                logger.error("ws_slow_client_callback_error", error=str(e), error_type=type(e).__name__)

    def _schedule_reconnect(self) -> None:
        """Schedule reconnection with exponential backoff.

        Requirement 11.8: THE Dashboard SHALL implement reconnection with
        exponential backoff (1s, 2s, 4s, 8s, max 30s).
        """
        if not self.running:
            return

        delay = self.reconnect_delay
        logger.info("ws_reconnect_scheduled", delay_seconds=delay)

        time.sleep(delay)

        # Increase delay for next attempt (exponential backoff)
        self.reconnect_delay = min(self.reconnect_delay * 2, self.MAX_RECONNECT_DELAY)

    def _schedule_proactive_reconnect(self) -> None:
        """Schedule proactive reconnection before Cloud Run timeout.

        Requirement 11.9: THE Dashboard SHALL proactively reconnect
        every 55 minutes before Cloud Run timeout.
        """
        self._cancel_proactive_reconnect()

        reconnect_seconds = self.PROACTIVE_RECONNECT_MINUTES * 60

        def proactive_reconnect():
            if self.running and self.ws:
                logger.info("ws_proactive_reconnect_triggered")
                self.reconnect_delay = 1.0  # Reset backoff for proactive reconnect
                try:
                    self.ws.close()
                except Exception as e:
                    # Requirement 17.7: Log all errors to console for debugging
                    logger.error("ws_proactive_close_error", error=str(e), error_type=type(e).__name__)

        self._proactive_reconnect_timer = threading.Timer(
            reconnect_seconds, proactive_reconnect
        )
        self._proactive_reconnect_timer.daemon = True
        self._proactive_reconnect_timer.start()
        logger.debug("ws_proactive_reconnect_scheduled", minutes=self.PROACTIVE_RECONNECT_MINUTES)

    def _cancel_proactive_reconnect(self) -> None:
        """Cancel the proactive reconnection timer."""
        if self._proactive_reconnect_timer:
            self._proactive_reconnect_timer.cancel()
            self._proactive_reconnect_timer = None

    def _parse_timestamp(self, ts_str: Optional[str]) -> Optional[datetime]:
        """Parse timestamp string to datetime.

        Args:
            ts_str: ISO format timestamp string

        Returns:
            datetime in IST or None if parsing fails
        """
        if not ts_str:
            return None

        try:
            # Try ISO format with timezone
            if "+" in ts_str or ts_str.endswith("Z"):
                dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                return dt.astimezone(IST)
            else:
                # Assume IST if no timezone
                dt = datetime.fromisoformat(ts_str)
                return IST.localize(dt)
        except (ValueError, TypeError):
            return None

    def disconnect(self) -> None:
        """Disconnect from the WebSocket stream.

        Stops the client and closes the connection gracefully.
        """
        logger.info("ws_disconnecting")
        self.running = False
        self._cancel_proactive_reconnect()

        if self.ws:
            try:
                self.ws.close()
            except Exception as e:
                # Requirement 17.7: Log all errors to console for debugging
                logger.error("ws_close_error", error=str(e), error_type=type(e).__name__)

        self.state.set_ws_connected(False)

    def is_connected(self) -> bool:
        """Check if WebSocket is currently connected.

        Returns:
            True if connected, False otherwise
        """
        return self.state.get_connection_status().ws_connected

    def update_jwt_token(self, new_token: str) -> None:
        """Update the JWT token for reconnection.

        Args:
            new_token: New JWT token
        """
        with self._lock:
            self.jwt_token = new_token


def calculate_backoff_delay(failure_count: int) -> float:
    """Calculate exponential backoff delay.

    Requirement 11.8: Backoff follows 2^(n-1) capped at 30s.
    Sequence: 1s, 2s, 4s, 8s, 16s, 30s, 30s, ...

    Args:
        failure_count: Number of consecutive failures (1-indexed)

    Returns:
        Delay in seconds
    """
    if failure_count < 1:
        return 1.0
    return min(2 ** (failure_count - 1), 30.0)


def create_pong_message() -> str:
    """Create a valid pong response message.

    Requirement 11.5: The pong message SHALL be valid JSON with
    exactly the action field set to "pong".

    Returns:
        JSON string with pong action
    """
    return json.dumps({"action": "pong"})
