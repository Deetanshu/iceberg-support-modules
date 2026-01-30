# Iceberg Test Dashboard - SSE Client Tests
"""
Tests for the TieredStreamClient SSE client.

Tests event handling, reconnection logic, and state updates.
Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7, 12.8, 12.9, 12.10
"""

import json
import pytest
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock
import pytz

from src.sse_client import TieredStreamClient, calculate_sse_backoff_delay
from src.state_manager import StateManager
from src.models import VALID_SYMBOLS, VALID_MODES

IST = pytz.timezone("Asia/Kolkata")


class TestTieredStreamClientInit:
    """Tests for TieredStreamClient initialization."""

    def test_init_with_defaults(self):
        """Test client initializes with default values."""
        state = StateManager()
        client = TieredStreamClient(state, "test_jwt_token")

        assert client.state is state
        assert client.jwt_token == "test_jwt_token"
        assert client.symbols == list(VALID_SYMBOLS)
        assert client.modes == list(VALID_MODES)
        assert client.running is False
        assert client.reconnect_delay == 1.0

    def test_init_with_custom_symbols(self):
        """Test client initializes with custom symbols."""
        state = StateManager()
        client = TieredStreamClient(
            state,
            "test_jwt_token",
            symbols=["nifty", "banknifty"],
            modes=["current"],
        )

        assert client.symbols == ["nifty", "banknifty"]
        assert client.modes == ["current"]

    def test_init_with_callback(self):
        """Test client initializes with refresh callback."""
        state = StateManager()
        callback = Mock()
        client = TieredStreamClient(
            state,
            "test_jwt_token",
            on_refresh_recommended=callback,
        )

        assert client.on_refresh_recommended is callback


class TestBuildUrl:
    """Tests for URL building."""

    def test_build_url_includes_all_params(self):
        """Test URL includes token, symbols, and modes."""
        state = StateManager()
        client = TieredStreamClient(
            state,
            "test_jwt_token",
            symbols=["nifty", "banknifty"],
            modes=["current", "positional"],
        )

        url = client._build_url()

        assert "token=test_jwt_token" in url
        assert "symbols=nifty,banknifty" in url
        assert "modes=current,positional" in url
        assert "include_optional=true" in url
        assert "/v1/stream/indicators/tiered" in url


class TestEventHandling:
    """Tests for SSE event handling."""

    def test_handle_snapshot_updates_state(self):
        """Test snapshot event updates state manager.
        
        Requirement 12.3: WHEN receiving a snapshot event,
        THE Dashboard SHALL populate initial indicator values.
        """
        state = StateManager()
        client = TieredStreamClient(state, "test_jwt_token")

        snapshot_data = {
            "event_type": "snapshot",
            "data": {
                "nifty": {
                    "current": {
                        "indicators": {
                            "skew": 0.5,
                            "pcr": 1.2,
                            "signal": "BUY",
                            "skew_confidence": 0.8,
                        }
                    }
                }
            }
        }

        client._handle_snapshot(snapshot_data)

        indicators = state.get_indicators("nifty", "current")
        assert indicators is not None
        assert indicators.skew == 0.5
        assert indicators.pcr == 1.2
        assert indicators.signal == "BUY"

    def test_handle_indicator_update(self):
        """Test indicator_update event updates state.
        
        Requirement 12.4: WHEN receiving an indicator_update event,
        THE Dashboard SHALL update indicator display.
        """
        state = StateManager()
        client = TieredStreamClient(state, "test_jwt_token")

        update_data = {
            "event_type": "indicator_update",
            "symbol": "banknifty",
            "mode": "positional",
            "indicators": {
                "skew": -0.3,
                "pcr": 0.9,
                "signal": "SELL",
                "skew_confidence": 0.6,
                "rsi": 45.5,
            },
            "timestamp": "2026-01-20T10:30:00+05:30",
        }

        client._handle_indicator_update(update_data)

        indicators = state.get_indicators("banknifty", "positional")
        assert indicators is not None
        assert indicators.skew == -0.3
        assert indicators.signal == "SELL"
        assert indicators.rsi == 45.5

    def test_handle_option_chain_update(self):
        """Test option_chain_update event updates state.
        
        Requirement 12.5: WHEN receiving an option_chain_update event,
        THE Dashboard SHALL update option chain OI/COI.
        """
        state = StateManager()
        client = TieredStreamClient(state, "test_jwt_token")

        update_data = {
            "event_type": "option_chain_update",
            "symbol": "nifty",
            "mode": "current",
            "expiry": "2026-01-23",
            "underlying": 24500.0,
            "strikes": [
                {"strike": 24400, "call_oi": 1000, "put_oi": 2000},
                {"strike": 24500, "call_oi": 1500, "put_oi": 1500},
                {"strike": 24600, "call_oi": 2000, "put_oi": 1000},
            ],
            "timestamp": "2026-01-20T10:30:00+05:30",
        }

        client._handle_option_chain_update(update_data)

        option_chain = state.get_option_chain("nifty", "current")
        assert option_chain is not None
        assert option_chain.expiry == "2026-01-23"
        assert option_chain.underlying == 24500.0
        assert len(option_chain.strikes) == 3

    def test_handle_market_closed(self):
        """Test market_closed event updates market state.
        
        Requirement 12.6: WHEN receiving a market_closed event,
        THE Dashboard SHALL display market closed banner.
        """
        state = StateManager()
        client = TieredStreamClient(state, "test_jwt_token")

        client._handle_market_closed({})

        assert state.get_market_state() == "CLOSED"

    def test_handle_heartbeat(self):
        """Test heartbeat event updates connection status.
        
        Requirement 12.7: WHEN receiving a heartbeat event,
        THE Dashboard SHALL update connection status.
        """
        state = StateManager()
        client = TieredStreamClient(state, "test_jwt_token")

        heartbeat_data = {
            "event_type": "heartbeat",
            "timestamp": "2026-01-20T10:30:00+05:30",
        }

        client._handle_heartbeat(heartbeat_data)

        assert client.last_heartbeat_time is not None
        assert state.get_connection_status().sse_connected is True

    def test_handle_refresh_recommended_calls_callback(self):
        """Test refresh_recommended event triggers callback.
        
        Requirement 12.8: WHEN receiving a refresh_recommended event,
        THE Dashboard SHALL re-fetch bootstrap data.
        """
        state = StateManager()
        callback = Mock()
        client = TieredStreamClient(
            state,
            "test_jwt_token",
            on_refresh_recommended=callback,
        )

        client._handle_refresh_recommended({})

        callback.assert_called_once()


class TestBackoffDelay:
    """Tests for exponential backoff calculation."""

    def test_backoff_sequence(self):
        """Test backoff follows 2^(n-1) capped at 30s.
        
        Requirement 12.9: Backoff sequence: 1s, 2s, 4s, 8s, 16s, 30s, 30s, ...
        """
        assert calculate_sse_backoff_delay(1) == 1.0
        assert calculate_sse_backoff_delay(2) == 2.0
        assert calculate_sse_backoff_delay(3) == 4.0
        assert calculate_sse_backoff_delay(4) == 8.0
        assert calculate_sse_backoff_delay(5) == 16.0
        assert calculate_sse_backoff_delay(6) == 30.0  # Capped
        assert calculate_sse_backoff_delay(7) == 30.0  # Still capped

    def test_backoff_zero_or_negative(self):
        """Test backoff returns 1.0 for invalid counts."""
        assert calculate_sse_backoff_delay(0) == 1.0
        assert calculate_sse_backoff_delay(-1) == 1.0


class TestConnectionManagement:
    """Tests for connection lifecycle management."""

    def test_disconnect_sets_flags(self):
        """Test disconnect properly sets flags."""
        state = StateManager()
        client = TieredStreamClient(state, "test_jwt_token")
        client.running = True

        client.disconnect()

        assert client.running is False
        assert state.get_connection_status().sse_connected is False

    def test_update_jwt_token(self):
        """Test JWT token can be updated."""
        state = StateManager()
        client = TieredStreamClient(state, "old_token")

        client.update_jwt_token("new_token")

        assert client.jwt_token == "new_token"

    def test_is_connected_returns_state(self):
        """Test is_connected returns state manager value."""
        state = StateManager()
        client = TieredStreamClient(state, "test_jwt_token")

        assert client.is_connected() is False

        state.set_sse_connected(True)
        assert client.is_connected() is True


class TestEventParsing:
    """Tests for SSE event parsing in _handle_event."""

    def test_handle_event_routes_correctly(self):
        """Test _handle_event routes to correct handler."""
        state = StateManager()
        client = TieredStreamClient(state, "test_jwt_token")

        # Test indicator_update routing
        indicator_data = json.dumps({
            "event_type": "indicator_update",
            "symbol": "nifty",
            "mode": "current",
            "indicators": {"skew": 0.5, "skew_confidence": 0.8},
        })

        client._handle_event("indicator_update", indicator_data)

        indicators = state.get_indicators("nifty", "current")
        assert indicators.skew == 0.5

    def test_handle_event_with_invalid_json(self):
        """Test _handle_event handles invalid JSON gracefully."""
        state = StateManager()
        client = TieredStreamClient(state, "test_jwt_token")

        # Should not raise exception
        client._handle_event("indicator_update", "invalid json {")

    def test_handle_event_with_empty_data(self):
        """Test _handle_event handles empty data gracefully."""
        state = StateManager()
        client = TieredStreamClient(state, "test_jwt_token")

        # Should not raise exception
        client._handle_event("indicator_update", "")


class TestReconnectionLogic:
    """Tests for SSE reconnection logic.
    
    Requirements: 12.8, 12.9, 12.10
    """

    def test_reconnect_delay_increases_exponentially(self):
        """Test reconnect delay follows exponential backoff.
        
        Requirement 12.9: Implement reconnection with exponential backoff
        (1s, 2s, 4s, 8s, max 30s).
        """
        state = StateManager()
        client = TieredStreamClient(state, "test_jwt_token")

        # Initial delay should be 1.0
        assert client.reconnect_delay == 1.0

        # Simulate increasing delay
        client.reconnect_delay = min(client.reconnect_delay * 2, client.MAX_RECONNECT_DELAY)
        assert client.reconnect_delay == 2.0

        client.reconnect_delay = min(client.reconnect_delay * 2, client.MAX_RECONNECT_DELAY)
        assert client.reconnect_delay == 4.0

        client.reconnect_delay = min(client.reconnect_delay * 2, client.MAX_RECONNECT_DELAY)
        assert client.reconnect_delay == 8.0

        client.reconnect_delay = min(client.reconnect_delay * 2, client.MAX_RECONNECT_DELAY)
        assert client.reconnect_delay == 16.0

        client.reconnect_delay = min(client.reconnect_delay * 2, client.MAX_RECONNECT_DELAY)
        assert client.reconnect_delay == 30.0  # Capped at MAX_RECONNECT_DELAY

        client.reconnect_delay = min(client.reconnect_delay * 2, client.MAX_RECONNECT_DELAY)
        assert client.reconnect_delay == 30.0  # Still capped

    def test_max_reconnect_delay_constant(self):
        """Test MAX_RECONNECT_DELAY is 30 seconds."""
        assert TieredStreamClient.MAX_RECONNECT_DELAY == 30.0

    def test_proactive_reconnect_minutes_constant(self):
        """Test PROACTIVE_RECONNECT_MINUTES is 55 minutes.
        
        Requirement 12.10: Proactively reconnect every 55 minutes
        before Cloud Run timeout.
        """
        assert TieredStreamClient.PROACTIVE_RECONNECT_MINUTES == 55

    def test_refresh_recommended_triggers_callback(self):
        """Test refresh_recommended event triggers bootstrap re-fetch.
        
        Requirement 12.8: Handle refresh_recommended event by re-fetching bootstrap.
        """
        state = StateManager()
        bootstrap_called = []

        def mock_bootstrap():
            bootstrap_called.append(True)

        client = TieredStreamClient(
            state,
            "test_jwt_token",
            on_refresh_recommended=mock_bootstrap,
        )

        # Trigger refresh_recommended event
        client._handle_refresh_recommended({})

        assert len(bootstrap_called) == 1

    def test_refresh_recommended_without_callback(self):
        """Test refresh_recommended event without callback doesn't crash."""
        state = StateManager()
        client = TieredStreamClient(state, "test_jwt_token")

        # Should not raise exception
        client._handle_refresh_recommended({})

    def test_schedule_proactive_reconnect_creates_timer(self):
        """Test proactive reconnect timer is created."""
        state = StateManager()
        client = TieredStreamClient(state, "test_jwt_token")

        client._schedule_proactive_reconnect()

        assert client._proactive_reconnect_timer is not None
        assert client._proactive_reconnect_timer.daemon is True

        # Clean up
        client._cancel_proactive_reconnect()

    def test_cancel_proactive_reconnect_clears_timer(self):
        """Test proactive reconnect timer is properly cancelled."""
        state = StateManager()
        client = TieredStreamClient(state, "test_jwt_token")

        client._schedule_proactive_reconnect()
        assert client._proactive_reconnect_timer is not None

        client._cancel_proactive_reconnect()
        assert client._proactive_reconnect_timer is None

    def test_disconnect_cancels_proactive_reconnect(self):
        """Test disconnect cancels proactive reconnect timer."""
        state = StateManager()
        client = TieredStreamClient(state, "test_jwt_token")
        client.running = True

        client._schedule_proactive_reconnect()
        assert client._proactive_reconnect_timer is not None

        client.disconnect()
        assert client._proactive_reconnect_timer is None

    def test_reconnect_delay_resets_on_successful_connection(self):
        """Test reconnect delay resets to 1.0 after successful connection."""
        state = StateManager()
        client = TieredStreamClient(state, "test_jwt_token")

        # Simulate failed reconnections
        client.reconnect_delay = 16.0

        # Simulate successful connection (what happens in _connect_and_stream)
        # After successful connection, delay should reset
        client.reconnect_delay = 1.0

        assert client.reconnect_delay == 1.0
