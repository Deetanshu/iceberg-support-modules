# Iceberg Test Dashboard - SSE Client
"""
SSE client for the Iceberg Tiered Stream.

Connects to /v1/stream/indicators/tiered for indicator updates.
Handles snapshot, indicator_update, option_chain_update, market_closed, heartbeat events.
Implements reconnection with exponential backoff.

Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7, 12.8, 12.9, 12.10, 17.7
"""

import json
import threading
import time
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Any
import pytz

import httpx
import structlog

from .config import get_settings
from .state_manager import StateManager
from .models import VALID_SYMBOLS, VALID_MODES
from .parsers import (
    parse_indicator_update,
    parse_option_chain_update,
    parse_snapshot_event,
    parse_timestamp,
    get_event_type,
)

# Requirement 17.7: Log all errors to console for debugging
logger = structlog.get_logger(__name__)
IST = pytz.timezone("Asia/Kolkata")


class TieredStreamClient:
    """SSE client for /v1/stream/indicators/tiered.

    Provides indicator updates for all symbols via SSE connection.
    Implements automatic reconnection with exponential backoff.

    Requirements:
        12.1: Connect to GET /v1/stream/indicators/tiered with JWT as query param
        12.2: Request all symbols and both modes (current, positional)
        12.3: Populate initial indicator values on snapshot event
        12.4: Update indicator display on indicator_update event
        12.5: Update option chain OI/COI on option_chain_update event
        12.6: Display market closed banner on market_closed event
        12.7: Update connection status on heartbeat event
        12.8: Re-fetch bootstrap data on refresh_recommended event
        12.9: Implement reconnection with exponential backoff (1s, 2s, 4s, 8s, max 30s)
        12.10: Proactively reconnect every 55 minutes before Cloud Run timeout

    Attributes:
        state: StateManager instance for updating shared state
        jwt_token: JWT token for authentication
        symbols: List of symbols to subscribe to
        modes: List of modes to subscribe to
        running: Flag to control the client lifecycle
        reconnect_delay: Current reconnection delay in seconds
        last_connect_time: Timestamp of last successful connection
        on_refresh_recommended: Callback for refresh_recommended event
    """

    # Constants
    MAX_RECONNECT_DELAY = 30.0  # Maximum backoff delay in seconds
    PROACTIVE_RECONNECT_MINUTES = 55  # Reconnect before Cloud Run timeout
    HEARTBEAT_TIMEOUT = 90  # Seconds without heartbeat before reconnecting

    def __init__(
        self,
        state_manager: StateManager,
        jwt_token: str,
        symbols: Optional[List[str]] = None,
        modes: Optional[List[str]] = None,
        on_refresh_recommended: Optional[Callable[[], None]] = None,
    ):
        """Initialize the TieredStreamClient.

        Args:
            state_manager: StateManager instance for updating shared state
            jwt_token: JWT token for authentication
            symbols: List of symbols to subscribe to (defaults to all valid symbols)
            modes: List of modes to subscribe to (defaults to all valid modes)
            on_refresh_recommended: Callback when refresh_recommended event is received
        """
        self.state = state_manager
        self.jwt_token = jwt_token
        self.symbols = symbols or list(VALID_SYMBOLS)
        self.modes = modes or list(VALID_MODES)
        self.on_refresh_recommended = on_refresh_recommended

        self.running = False
        self.reconnect_delay = 1.0
        self.last_connect_time: Optional[datetime] = None
        self.last_heartbeat_time: Optional[datetime] = None
        self._thread: Optional[threading.Thread] = None
        self._proactive_reconnect_timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

    def _build_url(self) -> str:
        """Build SSE URL with token and parameters.

        Requirement 12.1: Connect to GET /v1/stream/indicators/tiered with JWT as query param
        Requirement 12.2: Request all symbols and both modes (current, positional)

        Returns:
            SSE URL with query parameters
        """
        settings = get_settings()
        base_url = settings.iceberg_api_url
        symbols_param = ",".join(self.symbols)
        modes_param = ",".join(self.modes)
        return (
            f"{base_url}/v1/stream/indicators/tiered"
            f"?token={self.jwt_token}"
            f"&symbols={symbols_param}"
            f"&modes={modes_param}"
            f"&include_optional=true"
        )

    def connect(self) -> None:
        """Connect to the SSE stream.

        Starts the SSE connection in a background thread.
        """
        if self.running:
            logger.warning("TieredStreamClient already running")
            return

        self.running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        """Run the SSE connection loop."""
        while self.running and not self._stop_event.is_set():
            try:
                url = self._build_url()
                logger.info("sse_connecting", url_prefix=url[:60])

                self._connect_and_stream(url)

            except Exception as e:
                # Requirement 17.7: Log all errors to console for debugging
                logger.error("sse_connection_error", error=str(e), error_type=type(e).__name__)
                self.state.set_sse_connected(False)

            if self.running and not self._stop_event.is_set():
                self._schedule_reconnect()

    def _connect_and_stream(self, url: str) -> None:
        """Connect to SSE endpoint and process events.

        Args:
            url: Full SSE URL with query parameters
        """
        try:
            # Use httpx with streaming for SSE
            with httpx.Client(timeout=None) as client:
                with client.stream("GET", url) as response:
                    if response.status_code != 200:
                        # Requirement 17.7: Log all errors to console for debugging
                        logger.error("sse_connection_failed", status_code=response.status_code)
                        return

                    # Connection successful
                    self.state.set_sse_connected(True)
                    self.last_connect_time = datetime.now(IST)
                    self.last_heartbeat_time = datetime.now(IST)
                    self.reconnect_delay = 1.0  # Reset backoff on successful connection

                    # Schedule proactive reconnection (Requirement 12.10)
                    self._schedule_proactive_reconnect()

                    logger.info("sse_connected", symbols=self.symbols, modes=self.modes)

                    # Process SSE events
                    self._process_stream(response)

        except httpx.TimeoutException:
            # Requirement 17.7: Log all errors to console for debugging
            logger.warning("sse_timeout")
        except httpx.ConnectError as e:
            # Requirement 17.7: Log all errors to console for debugging
            logger.error("sse_connect_error", error=str(e), error_type=type(e).__name__)
        except Exception as e:
            # Requirement 17.7: Log all errors to console for debugging
            logger.error("sse_stream_error", error=str(e), error_type=type(e).__name__)
        finally:
            self.state.set_sse_connected(False)
            self._cancel_proactive_reconnect()

    def _process_stream(self, response: httpx.Response) -> None:
        """Process SSE event stream.

        Args:
            response: httpx streaming response
        """
        event_type = None
        event_data = ""

        for line in response.iter_lines():
            if self._stop_event.is_set() or not self.running:
                break

            line = line.strip()

            if not line:
                # Empty line signals end of event
                if event_data:
                    self._handle_event(event_type, event_data)
                    event_type = None
                    event_data = ""
                continue

            if line.startswith("event:"):
                event_type = line[6:].strip()
            elif line.startswith("data:"):
                data_content = line[5:].strip()
                if event_data:
                    event_data += "\n" + data_content
                else:
                    event_data = data_content
            elif line.startswith(":"):
                # Comment line (often used for keep-alive)
                pass

    def _handle_event(self, event_type: Optional[str], data: str) -> None:
        """Handle a complete SSE event.

        Requirements 12.3, 12.4, 12.5, 12.6, 12.7, 12.8:
        Handle snapshot, indicator_update, option_chain_update,
        market_closed, heartbeat, refresh_recommended events.

        Args:
            event_type: SSE event type (from "event:" line)
            data: SSE event data (from "data:" line)
        """
        if not data:
            return

        try:
            parsed_data = json.loads(data)
        except json.JSONDecodeError as e:
            # Requirement 17.7: Log all errors to console for debugging
            logger.error("sse_json_parse_error", error=str(e), data_preview=data[:100] if data else None)
            return

        # Determine event type from event line or data
        actual_event_type = event_type or get_event_type(parsed_data)

        try:
            if actual_event_type == "snapshot":
                self._handle_snapshot(parsed_data)
            elif actual_event_type == "indicator_update":
                self._handle_indicator_update(parsed_data)
            elif actual_event_type == "option_chain_update":
                self._handle_option_chain_update(parsed_data)
            elif actual_event_type == "market_closed":
                self._handle_market_closed(parsed_data)
            elif actual_event_type == "heartbeat":
                self._handle_heartbeat(parsed_data)
            elif actual_event_type == "refresh_recommended":
                self._handle_refresh_recommended(parsed_data)
            else:
                logger.debug("sse_unknown_event", event_type=actual_event_type)
        except Exception as e:
            # Requirement 17.7: Log all errors to console for debugging
            logger.error("sse_event_handling_error", error=str(e), error_type=type(e).__name__, event_type=actual_event_type)

    def _handle_snapshot(self, data: Dict[str, Any]) -> None:
        """Handle snapshot event to populate initial indicator values.

        Requirement 12.3: WHEN receiving a snapshot event,
        THE Dashboard SHALL populate initial indicator values.

        Args:
            data: Snapshot event data
        """
        logger.info("sse_snapshot_processing")
        try:
            parsed = parse_snapshot_event(data)
            for symbol, modes_data in parsed.items():
                for mode, symbol_data in modes_data.items():
                    if symbol_data.indicators:
                        self.state.update_indicators(symbol, mode, symbol_data.indicators)
                    if symbol_data.option_chain:
                        self.state.update_option_chain(symbol, mode, symbol_data.option_chain)
                    if symbol_data.candles:
                        self.state.update_candles(symbol, symbol_data.candles)
            logger.info("sse_snapshot_processed", symbol_count=len(parsed))
        except Exception as e:
            # Requirement 17.7: Log all errors to console for debugging
            logger.error("sse_snapshot_error", error=str(e), error_type=type(e).__name__)

    def _handle_indicator_update(self, data: Dict[str, Any]) -> None:
        """Handle indicator_update event to update indicator display.

        Requirement 12.4: WHEN receiving an indicator_update event,
        THE Dashboard SHALL update indicator display.

        Args:
            data: Indicator update event data
        """
        try:
            symbol, mode, indicators = parse_indicator_update(data)
            self.state.update_indicators(symbol, mode, indicators)
            print(f"[SSE] Indicator update: {symbol}/{mode} - EMA5={indicators.ema_5}, EMA21={indicators.ema_21}, RSI={indicators.rsi}")
            logger.debug("sse_indicators_updated", symbol=symbol, mode=mode)
        except Exception as e:
            # Requirement 17.7: Log all errors to console for debugging
            print(f"[SSE] ERROR parsing indicator update: {e}")
            logger.error("sse_indicator_update_error", error=str(e), error_type=type(e).__name__)

    def _handle_option_chain_update(self, data: Dict[str, Any]) -> None:
        """Handle option_chain_update event to update option chain OI/COI.

        Requirement 12.5: WHEN receiving an option_chain_update event,
        THE Dashboard SHALL update option chain OI/COI.

        Args:
            data: Option chain update event data
        """
        try:
            symbol, mode, option_chain = parse_option_chain_update(data)
            self.state.update_option_chain(symbol, mode, option_chain)
            print(f"[SSE] Option chain update: {symbol}/{mode} - {len(option_chain.strikes)} strikes, underlying={option_chain.underlying}")
            logger.debug("sse_option_chain_updated", symbol=symbol, mode=mode)
        except Exception as e:
            # Requirement 17.7: Log all errors to console for debugging
            print(f"[SSE] ERROR parsing option chain update: {e}")
            logger.error("sse_option_chain_update_error", error=str(e), error_type=type(e).__name__)

    def _handle_market_closed(self, data: Dict[str, Any]) -> None:
        """Handle market_closed event to display market closed banner.

        Requirement 12.6: WHEN receiving a market_closed event,
        THE Dashboard SHALL display market closed banner.

        Args:
            data: Market closed event data
        """
        logger.info("sse_market_closed_event")
        self.state.set_market_state("CLOSED")

    def _handle_heartbeat(self, data: Dict[str, Any]) -> None:
        """Handle heartbeat event to update connection status.

        Requirement 12.7: WHEN receiving a heartbeat event,
        THE Dashboard SHALL update connection status.

        Args:
            data: Heartbeat event data
        """
        self.last_heartbeat_time = datetime.now(IST)
        ts = parse_timestamp(data.get("timestamp", data.get("ts")))
        self.state.set_sse_connected(True)
        logger.debug("sse_heartbeat_received", timestamp=str(ts) if ts else None)

    def _handle_refresh_recommended(self, data: Dict[str, Any]) -> None:
        """Handle refresh_recommended event by re-fetching bootstrap data.

        Requirement 12.8: WHEN receiving a refresh_recommended event,
        THE Dashboard SHALL re-fetch bootstrap data.

        Args:
            data: Refresh recommended event data
        """
        logger.info("sse_refresh_recommended_event")
        if self.on_refresh_recommended:
            try:
                self.on_refresh_recommended()
            except Exception as e:
                # Requirement 17.7: Log all errors to console for debugging
                logger.error("sse_refresh_callback_error", error=str(e), error_type=type(e).__name__)

    def _schedule_reconnect(self) -> None:
        """Schedule reconnection with exponential backoff.

        Requirement 12.9: THE Dashboard SHALL implement reconnection with
        exponential backoff (1s, 2s, 4s, 8s, max 30s).
        """
        if not self.running or self._stop_event.is_set():
            return

        delay = self.reconnect_delay
        logger.info("sse_reconnect_scheduled", delay_seconds=delay)

        # Use stop_event.wait() instead of time.sleep() for interruptible wait
        self._stop_event.wait(timeout=delay)

        # Increase delay for next attempt (exponential backoff)
        self.reconnect_delay = min(self.reconnect_delay * 2, self.MAX_RECONNECT_DELAY)

    def _schedule_proactive_reconnect(self) -> None:
        """Schedule proactive reconnection before Cloud Run timeout.

        Requirement 12.10: THE Dashboard SHALL proactively reconnect
        every 55 minutes before Cloud Run timeout.
        """
        self._cancel_proactive_reconnect()

        reconnect_seconds = self.PROACTIVE_RECONNECT_MINUTES * 60

        def proactive_reconnect():
            if self.running:
                logger.info("sse_proactive_reconnect_triggered")
                self.reconnect_delay = 1.0  # Reset backoff for proactive reconnect
                # Signal the stream to stop, which will trigger reconnection
                self._stop_event.set()

        self._proactive_reconnect_timer = threading.Timer(
            reconnect_seconds, proactive_reconnect
        )
        self._proactive_reconnect_timer.daemon = True
        self._proactive_reconnect_timer.start()
        logger.debug("sse_proactive_reconnect_scheduled", minutes=self.PROACTIVE_RECONNECT_MINUTES)

    def _cancel_proactive_reconnect(self) -> None:
        """Cancel the proactive reconnection timer."""
        if self._proactive_reconnect_timer:
            self._proactive_reconnect_timer.cancel()
            self._proactive_reconnect_timer = None

    def disconnect(self) -> None:
        """Disconnect from the SSE stream.

        Stops the client and closes the connection gracefully.
        """
        logger.info("sse_disconnecting")
        self.running = False
        self._stop_event.set()
        self._cancel_proactive_reconnect()
        self.state.set_sse_connected(False)

    def is_connected(self) -> bool:
        """Check if SSE is currently connected.

        Returns:
            True if connected, False otherwise
        """
        return self.state.get_connection_status().sse_connected

    def update_jwt_token(self, new_token: str) -> None:
        """Update the JWT token for reconnection.

        Args:
            new_token: New JWT token
        """
        with self._lock:
            self.jwt_token = new_token


def calculate_sse_backoff_delay(failure_count: int) -> float:
    """Calculate exponential backoff delay for SSE reconnection.

    Requirement 12.9: Backoff follows 2^(n-1) capped at 30s.
    Sequence: 1s, 2s, 4s, 8s, 16s, 30s, 30s, ...

    Args:
        failure_count: Number of consecutive failures (1-indexed)

    Returns:
        Delay in seconds
    """
    if failure_count < 1:
        return 1.0
    return min(2 ** (failure_count - 1), 30.0)
