# Iceberg Test Dashboard - WebSocket Client Tests
"""
Unit tests for the FastStreamClient WebSocket client.

Tests cover:
- Message handling (tick, option_chain_ltp, snapshot, ping)
- Exponential backoff calculation
- Pong message creation
- State updates from WebSocket events

Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 11.8, 11.9
"""

import json
import pytest
from datetime import datetime
from unittest.mock import Mock, MagicMock, patch
import pytz

from src.state_manager import StateManager
from src.ws_client import (
    FastStreamClient,
    calculate_backoff_delay,
    create_pong_message,
)

IST = pytz.timezone("Asia/Kolkata")


@pytest.fixture
def state_manager():
    """Create a fresh StateManager for each test."""
    return StateManager()


@pytest.fixture
def ws_client(state_manager):
    """Create a FastStreamClient with mock callbacks."""
    return FastStreamClient(
        state_manager=state_manager,
        jwt_token="test_jwt_token",
        symbols=["nifty", "banknifty"],
        on_jwt_refresh_needed=Mock(return_value="new_jwt_token"),
        on_slow_client_warning=Mock(),
    )


class TestFastStreamClientInit:
    """Tests for FastStreamClient initialization."""

    def test_init_with_defaults(self, state_manager):
        """Test initialization with default symbols."""
        client = FastStreamClient(
            state_manager=state_manager,
            jwt_token="test_token",
        )
        assert client.jwt_token == "test_token"
        assert len(client.symbols) == 4  # All valid symbols
        assert "nifty" in client.symbols
        assert "banknifty" in client.symbols
        assert "sensex" in client.symbols
        assert "finnifty" in client.symbols

    def test_init_with_custom_symbols(self, state_manager):
        """Test initialization with custom symbol list."""
        client = FastStreamClient(
            state_manager=state_manager,
            jwt_token="test_token",
            symbols=["nifty", "banknifty"],
        )
        assert client.symbols == ["nifty", "banknifty"]

    def test_init_state(self, ws_client):
        """Test initial state values."""
        assert ws_client.running is False
        assert ws_client.reconnect_delay == 1.0
        assert ws_client.last_connect_time is None
        assert ws_client.ws is None


class TestBuildUrl:
    """Tests for WebSocket URL building."""

    def test_build_url_contains_token(self, ws_client):
        """Test that URL contains JWT token."""
        url = ws_client._build_url()
        assert "token=test_jwt_token" in url

    def test_build_url_contains_symbols(self, ws_client):
        """Test that URL contains symbols parameter."""
        url = ws_client._build_url()
        assert "symbols=nifty,banknifty" in url

    def test_build_url_endpoint(self, ws_client):
        """Test that URL points to correct endpoint."""
        url = ws_client._build_url()
        assert "/v1/stream/fast" in url


class TestHandlePing:
    """Tests for ping/pong protocol handling."""

    def test_handle_ping_sends_pong(self, ws_client):
        """Test that ping event triggers pong response.
        
        Requirement 11.5: Respond to ping with {"action": "pong"} within 60 seconds
        """
        mock_ws = Mock()
        ws_client._handle_ping(mock_ws)
        
        mock_ws.send.assert_called_once()
        sent_message = mock_ws.send.call_args[0][0]
        parsed = json.loads(sent_message)
        assert parsed == {"action": "pong"}

    def test_handle_ping_error_handling(self, ws_client):
        """Test that ping handler handles send errors gracefully."""
        mock_ws = Mock()
        mock_ws.send.side_effect = Exception("Send failed")
        
        # Should not raise
        ws_client._handle_ping(mock_ws)


class TestHandleTick:
    """Tests for tick event handling."""

    def test_handle_tick_updates_ltp(self, ws_client, state_manager):
        """Test that tick event updates symbol LTP.
        
        Requirement 11.3: WHEN receiving a tick event, THE Dashboard SHALL
        update the corresponding symbol LTP.
        """
        tick_data = {
            "event": "tick",
            "data": {
                "nifty": {
                    "ltp": 24500.50,
                    "change": 150.25,
                    "change_pct": 0.62,
                }
            },
        }
        
        ws_client._handle_tick(tick_data)
        
        ltp = state_manager.get_ltp("nifty")
        assert ltp is not None
        assert ltp.ltp == 24500.50
        assert ltp.change == 150.25
        assert ltp.change_pct == 0.62

    def test_handle_tick_multiple_symbols(self, ws_client, state_manager):
        """Test that tick event updates multiple symbols."""
        tick_data = {
            "event": "tick",
            "data": {
                "nifty": {"ltp": 24500.50, "change": 100.0, "change_pct": 0.5},
                "banknifty": {"ltp": 52000.00, "change": 200.0, "change_pct": 0.4},
            },
        }
        
        ws_client._handle_tick(tick_data)
        
        nifty_ltp = state_manager.get_ltp("nifty")
        banknifty_ltp = state_manager.get_ltp("banknifty")
        
        assert nifty_ltp.ltp == 24500.50
        assert banknifty_ltp.ltp == 52000.00

    def test_handle_tick_empty_data(self, ws_client, state_manager):
        """Test that empty tick data is handled gracefully."""
        tick_data = {"event": "tick", "data": {}}
        
        # Should not raise
        ws_client._handle_tick(tick_data)


class TestHandleOptionChainLtp:
    """Tests for option_chain_ltp event handling."""

    def test_handle_option_chain_ltp_updates_strikes(self, ws_client, state_manager):
        """Test that option_chain_ltp event updates strike LTPs.
        
        Requirement 11.4: WHEN receiving an option_chain_ltp event,
        THE Dashboard SHALL update option chain LTPs.
        """
        # First, set up some option chain data
        from src.models import OptionChainData, OptionStrike
        
        option_chain = OptionChainData(
            expiry="2026-01-23",
            underlying=24500.0,
            strikes=[
                OptionStrike(strike=24400.0, call_oi=1000, put_oi=2000),
                OptionStrike(strike=24500.0, call_oi=1500, put_oi=2500),
                OptionStrike(strike=24600.0, call_oi=1200, put_oi=2200),
            ],
        )
        state_manager.update_option_chain("nifty", "current", option_chain)
        
        # Now handle option_chain_ltp event (FIX: use columnar format per API spec)
        ltp_data = {
            "event": "option_chain_ltp",
            "symbol": "nifty",
            "mode": "current",
            "data": {
                "strikes": [24400.0, 24500.0],
                "call_ltp": [150.0, 100.0],
                "put_ltp": [50.0, 100.0],
            },
        }
        
        ws_client._handle_option_chain_ltp(ltp_data)
        
        updated_chain = state_manager.get_option_chain("nifty", "current")
        assert updated_chain.strikes[0].call_ltp == 150.0
        assert updated_chain.strikes[0].put_ltp == 50.0
        assert updated_chain.strikes[1].call_ltp == 100.0
        assert updated_chain.strikes[1].put_ltp == 100.0

    def test_handle_option_chain_ltp_missing_symbol(self, ws_client, state_manager):
        """Test that missing symbol is handled gracefully."""
        ltp_data = {
            "event": "option_chain_ltp",
            "symbol": "",
            "mode": "current",
            "data": {
                "strikes": [],
                "call_ltp": [],
                "put_ltp": [],
            },
        }
        
        # Should not raise
        ws_client._handle_option_chain_ltp(ltp_data)


class TestHandleSnapshot:
    """Tests for snapshot event handling."""

    def test_handle_snapshot_updates_all_symbols(self, ws_client, state_manager):
        """Test that snapshot event updates all symbol LTPs."""
        snapshot_data = {
            "event": "snapshot",
            "data": {
                "nifty": {"ltp": 24500.0, "change": 100.0, "change_pct": 0.5},
                "banknifty": {"ltp": 52000.0, "change": 200.0, "change_pct": 0.4},
            },
        }
        
        ws_client._handle_snapshot(snapshot_data)
        
        assert state_manager.get_ltp("nifty").ltp == 24500.0
        assert state_manager.get_ltp("banknifty").ltp == 52000.0


class TestOnMessage:
    """Tests for message routing."""

    def test_on_message_routes_ping(self, ws_client):
        """Test that ping messages are routed correctly."""
        mock_ws = Mock()
        message = json.dumps({"event": "ping"})
        
        ws_client._on_message(mock_ws, message)
        
        mock_ws.send.assert_called_once()

    def test_on_message_routes_tick(self, ws_client, state_manager):
        """Test that tick messages are routed correctly."""
        mock_ws = Mock()
        message = json.dumps({
            "event": "tick",
            "data": {"nifty": {"ltp": 24500.0, "change": 0, "change_pct": 0}},
        })
        
        ws_client._on_message(mock_ws, message)
        
        assert state_manager.get_ltp("nifty").ltp == 24500.0

    def test_on_message_handles_invalid_json(self, ws_client):
        """Test that invalid JSON is handled gracefully."""
        mock_ws = Mock()
        
        # Should not raise
        ws_client._on_message(mock_ws, "not valid json")


class TestOnClose:
    """Tests for connection close handling."""

    def test_on_close_jwt_expired(self, ws_client):
        """Test that close code 4001 triggers JWT refresh.
        
        Requirement 11.6: IF WebSocket disconnects with code 4001,
        THEN THE Dashboard SHALL refresh JWT and reconnect.
        """
        mock_ws = Mock()
        ws_client.running = True
        
        ws_client._on_close(mock_ws, 4001, "JWT expired")
        
        ws_client.on_jwt_refresh_needed.assert_called_once()
        assert ws_client.jwt_token == "new_jwt_token"

    def test_on_close_slow_client(self, ws_client):
        """Test that close code 4005 triggers slow client warning.
        
        Requirement 11.7: IF WebSocket disconnects with code 4005,
        THEN THE Dashboard SHALL display slow client warning.
        """
        mock_ws = Mock()
        ws_client.running = True
        
        ws_client._on_close(mock_ws, 4005, "Slow client")
        
        ws_client.on_slow_client_warning.assert_called_once()

    def test_on_close_updates_connection_status(self, ws_client, state_manager):
        """Test that close updates connection status."""
        mock_ws = Mock()
        state_manager.set_ws_connected(True)
        
        ws_client._on_close(mock_ws, 1000, "Normal close")
        
        assert not state_manager.get_connection_status().ws_connected


class TestOnOpen:
    """Tests for connection open handling."""

    def test_on_open_updates_connection_status(self, ws_client, state_manager):
        """Test that open updates connection status."""
        mock_ws = Mock()
        
        ws_client._on_open(mock_ws)
        
        assert state_manager.get_connection_status().ws_connected

    def test_on_open_resets_backoff(self, ws_client):
        """Test that successful connection resets backoff delay."""
        mock_ws = Mock()
        ws_client.reconnect_delay = 16.0  # Simulate previous failures
        
        ws_client._on_open(mock_ws)
        
        assert ws_client.reconnect_delay == 1.0

    def test_on_open_sets_connect_time(self, ws_client):
        """Test that connection time is recorded."""
        mock_ws = Mock()
        
        ws_client._on_open(mock_ws)
        
        assert ws_client.last_connect_time is not None


class TestCalculateBackoffDelay:
    """Tests for exponential backoff calculation."""

    def test_backoff_first_failure(self):
        """Test backoff for first failure is 1 second.
        
        Requirement 11.8: Backoff sequence starts at 1s.
        """
        assert calculate_backoff_delay(1) == 1.0

    def test_backoff_second_failure(self):
        """Test backoff for second failure is 2 seconds."""
        assert calculate_backoff_delay(2) == 2.0

    def test_backoff_third_failure(self):
        """Test backoff for third failure is 4 seconds."""
        assert calculate_backoff_delay(3) == 4.0

    def test_backoff_fourth_failure(self):
        """Test backoff for fourth failure is 8 seconds."""
        assert calculate_backoff_delay(4) == 8.0

    def test_backoff_fifth_failure(self):
        """Test backoff for fifth failure is 16 seconds."""
        assert calculate_backoff_delay(5) == 16.0

    def test_backoff_capped_at_30(self):
        """Test backoff is capped at 30 seconds.
        
        Requirement 11.8: Maximum backoff is 30 seconds.
        """
        assert calculate_backoff_delay(6) == 30.0
        assert calculate_backoff_delay(10) == 30.0
        assert calculate_backoff_delay(100) == 30.0

    def test_backoff_zero_failures(self):
        """Test backoff for zero failures returns 1 second."""
        assert calculate_backoff_delay(0) == 1.0

    def test_backoff_negative_failures(self):
        """Test backoff for negative failures returns 1 second."""
        assert calculate_backoff_delay(-1) == 1.0


class TestCreatePongMessage:
    """Tests for pong message creation."""

    def test_pong_message_is_valid_json(self):
        """Test that pong message is valid JSON.
        
        Requirement 11.5: The pong message SHALL be valid JSON.
        """
        message = create_pong_message()
        parsed = json.loads(message)
        assert isinstance(parsed, dict)

    def test_pong_message_has_action_field(self):
        """Test that pong message has action field set to pong.
        
        Requirement 11.5: The pong message SHALL have exactly the action
        field set to "pong".
        """
        message = create_pong_message()
        parsed = json.loads(message)
        assert parsed == {"action": "pong"}


class TestParseTimestamp:
    """Tests for timestamp parsing."""

    def test_parse_iso_timestamp_with_timezone(self, ws_client):
        """Test parsing ISO timestamp with timezone."""
        ts = ws_client._parse_timestamp("2026-01-20T10:30:00+05:30")
        assert ts is not None
        assert ts.hour == 10
        assert ts.minute == 30

    def test_parse_iso_timestamp_utc(self, ws_client):
        """Test parsing ISO timestamp with Z suffix."""
        ts = ws_client._parse_timestamp("2026-01-20T05:00:00Z")
        assert ts is not None
        # Should be converted to IST (+5:30)
        assert ts.hour == 10
        assert ts.minute == 30

    def test_parse_iso_timestamp_no_timezone(self, ws_client):
        """Test parsing ISO timestamp without timezone (assumes IST)."""
        ts = ws_client._parse_timestamp("2026-01-20T10:30:00")
        assert ts is not None
        assert ts.hour == 10

    def test_parse_none_timestamp(self, ws_client):
        """Test parsing None returns None."""
        assert ws_client._parse_timestamp(None) is None

    def test_parse_invalid_timestamp(self, ws_client):
        """Test parsing invalid timestamp returns None."""
        assert ws_client._parse_timestamp("not a timestamp") is None


class TestDisconnect:
    """Tests for disconnect functionality."""

    def test_disconnect_sets_running_false(self, ws_client):
        """Test that disconnect sets running to False."""
        ws_client.running = True
        ws_client.disconnect()
        assert ws_client.running is False

    def test_disconnect_updates_connection_status(self, ws_client, state_manager):
        """Test that disconnect updates connection status."""
        state_manager.set_ws_connected(True)
        ws_client.disconnect()
        assert not state_manager.get_connection_status().ws_connected


class TestUpdateJwtToken:
    """Tests for JWT token update."""

    def test_update_jwt_token(self, ws_client):
        """Test that JWT token can be updated."""
        ws_client.update_jwt_token("new_token_123")
        assert ws_client.jwt_token == "new_token_123"
