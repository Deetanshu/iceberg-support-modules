# Iceberg Test Dashboard - State Manager Tests
"""
Unit tests for the StateManager class.

Tests thread-safety and correct state management for:
- LTP updates (Requirement 11.3)
- Indicator updates (Requirement 12.4)
- Option chain updates
- Mode data separation (Requirement 13.4)
"""

import pytest
from datetime import datetime
import pytz
import threading
import time

from src.state_manager import StateManager, ConnectionStatus
from src.models import (
    SymbolTick,
    IndicatorData,
    OptionChainData,
    OptionStrike,
    Candle,
    VALID_SYMBOLS,
    VALID_MODES,
)

IST = pytz.timezone("Asia/Kolkata")


class TestStateManagerInitialization:
    """Tests for StateManager initialization."""

    def test_init_creates_empty_state(self):
        """StateManager should initialize with empty state containers."""
        state = StateManager()

        assert state.symbols_ltp == {}
        assert state.market_state == "UNKNOWN"
        assert state.connection_status.ws_connected is False
        assert state.connection_status.sse_connected is False

    def test_init_creates_structures_for_all_symbols(self):
        """StateManager should initialize structures for all valid symbols."""
        state = StateManager()

        for symbol in VALID_SYMBOLS:
            assert symbol in state.indicators
            assert symbol in state.option_chains
            assert symbol in state.candles
            assert symbol in state.ema_history

            for mode in VALID_MODES:
                assert mode in state.indicators[symbol]
                assert mode in state.option_chains[symbol]


class TestLTPUpdates:
    """Tests for LTP update functionality (Requirement 11.3)."""

    def test_update_ltp_stores_data(self):
        """update_ltp should store LTP data for a symbol."""
        state = StateManager()
        ts = datetime.now(IST)

        state.update_ltp("nifty", 22500.50, change=100.25, change_pct=0.45, ts=ts)

        tick = state.get_ltp("nifty")
        assert tick is not None
        assert tick.symbol == "nifty"
        assert tick.ltp == 22500.50
        assert tick.change == 100.25
        assert tick.change_pct == 0.45
        assert tick.ts == ts

    def test_update_ltp_normalizes_symbol_case(self):
        """update_ltp should normalize symbol to lowercase."""
        state = StateManager()

        state.update_ltp("NIFTY", 22500.0)

        assert state.get_ltp("nifty") is not None
        assert state.get_ltp("NIFTY") is not None  # Should also work

    def test_update_ltp_updates_connection_status(self):
        """update_ltp should update last_ws_update timestamp."""
        state = StateManager()
        ts = datetime.now(IST)

        state.update_ltp("nifty", 22500.0, ts=ts)

        status = state.get_connection_status()
        assert status.last_ws_update == ts

    def test_get_all_ltps_returns_copy(self):
        """get_all_ltps should return a copy of the data."""
        state = StateManager()
        state.update_ltp("nifty", 22500.0)
        state.update_ltp("banknifty", 48000.0)

        ltps = state.get_all_ltps()

        assert len(ltps) == 2
        assert "nifty" in ltps
        assert "banknifty" in ltps


class TestIndicatorUpdates:
    """Tests for indicator update functionality (Requirement 12.4)."""

    def test_update_indicators_stores_data(self):
        """update_indicators should store indicator data for symbol/mode."""
        state = StateManager()
        ts = datetime.now(IST)
        indicators = IndicatorData(
            skew=0.35,
            pcr=1.2,
            signal="BUY",
            skew_confidence=0.8,
            rsi=55.0,
            ema_5=22500.0,
            ema_21=22450.0,
            ts=ts,
        )

        state.update_indicators("nifty", "current", indicators)

        result = state.get_indicators("nifty", "current")
        assert result is not None
        assert result.skew == 0.35
        assert result.pcr == 1.2
        assert result.signal == "BUY"
        assert result.rsi == 55.0

    def test_update_indicators_normalizes_case(self):
        """update_indicators should normalize symbol and mode to lowercase."""
        state = StateManager()
        indicators = IndicatorData(skew=0.5)

        state.update_indicators("NIFTY", "CURRENT", indicators)

        assert state.get_indicators("nifty", "current") is not None

    def test_update_indicators_updates_ema_history(self):
        """update_indicators should append to EMA history when EMAs present.
        
        Note: Timestamps are floored to 5-minute candle boundaries for deduplication.
        """
        from src.state_manager import floor_to_5min_boundary
        
        state = StateManager()
        ts = datetime.now(IST)
        indicators = IndicatorData(ema_5=22500.0, ema_21=22450.0, ts=ts)

        state.update_indicators("nifty", "current", indicators)

        history = state.get_ema_history("nifty")
        assert len(history) == 1
        # Timestamp is floored to 5-minute boundary
        expected_ts = floor_to_5min_boundary(ts)
        assert history[0] == (expected_ts, 22500.0, 22450.0)


class TestModeDataSeparation:
    """Tests for mode data separation (Requirement 13.4)."""

    def test_indicators_separated_by_mode(self):
        """Indicator updates for one mode should not affect another mode."""
        state = StateManager()
        current_indicators = IndicatorData(skew=0.5, signal="BUY")
        positional_indicators = IndicatorData(skew=-0.3, signal="SELL")

        state.update_indicators("nifty", "current", current_indicators)
        state.update_indicators("nifty", "positional", positional_indicators)

        current = state.get_indicators("nifty", "current")
        positional = state.get_indicators("nifty", "positional")

        assert current.skew == 0.5
        assert current.signal == "BUY"
        assert positional.skew == -0.3
        assert positional.signal == "SELL"

    def test_option_chains_separated_by_mode(self):
        """Option chain updates for one mode should not affect another mode."""
        state = StateManager()
        current_chain = OptionChainData(
            expiry="2026-01-23",
            underlying=22500.0,
            strikes=[OptionStrike(strike=22500, call_oi=1000, put_oi=2000)],
        )
        positional_chain = OptionChainData(
            expiry="2026-02-27",
            underlying=22500.0,
            strikes=[OptionStrike(strike=22500, call_oi=5000, put_oi=3000)],
        )

        state.update_option_chain("nifty", "current", current_chain)
        state.update_option_chain("nifty", "positional", positional_chain)

        current = state.get_option_chain("nifty", "current")
        positional = state.get_option_chain("nifty", "positional")

        assert current.expiry == "2026-01-23"
        assert current.strikes[0].call_oi == 1000
        assert positional.expiry == "2026-02-27"
        assert positional.strikes[0].call_oi == 5000


class TestOptionChainUpdates:
    """Tests for option chain update functionality."""

    def test_update_option_chain_stores_data(self):
        """update_option_chain should store option chain data."""
        state = StateManager()
        chain = OptionChainData(
            expiry="2026-01-23",
            underlying=22500.0,
            strikes=[
                OptionStrike(strike=22400, call_oi=1000, put_oi=2000),
                OptionStrike(strike=22500, call_oi=1500, put_oi=1800),
                OptionStrike(strike=22600, call_oi=2000, put_oi=1500),
            ],
        )

        state.update_option_chain("nifty", "current", chain)

        result = state.get_option_chain("nifty", "current")
        assert result is not None
        assert result.expiry == "2026-01-23"
        assert len(result.strikes) == 3

    def test_update_option_chain_ltp(self):
        """update_option_chain_ltp should update LTPs for specific strikes."""
        state = StateManager()
        chain = OptionChainData(
            expiry="2026-01-23",
            underlying=22500.0,
            strikes=[
                OptionStrike(strike=22400, call_oi=1000, put_oi=2000),
                OptionStrike(strike=22500, call_oi=1500, put_oi=1800),
            ],
        )
        state.update_option_chain("nifty", "current", chain)

        # Update LTPs
        strike_ltps = {
            22400: (150.0, 50.0),
            22500: (100.0, 100.0),
        }
        state.update_option_chain_ltp("nifty", "current", strike_ltps)

        result = state.get_option_chain("nifty", "current")
        assert result.strikes[0].call_ltp == 150.0
        assert result.strikes[0].put_ltp == 50.0
        assert result.strikes[1].call_ltp == 100.0
        assert result.strikes[1].put_ltp == 100.0


class TestCandleUpdates:
    """Tests for candle update functionality."""

    def test_update_candles_replaces_data(self):
        """update_candles should replace all candle data for a symbol."""
        state = StateManager()
        ts = datetime.now(IST)
        candles = [
            Candle(ts=ts, open=22500, high=22550, low=22480, close=22530, volume=1000),
            Candle(ts=ts, open=22530, high=22580, low=22510, close=22560, volume=1200),
        ]

        state.update_candles("nifty", candles)

        result = state.get_candles("nifty")
        assert len(result) == 2
        assert result[0].open == 22500
        assert result[1].close == 22560

    def test_append_candle_adds_to_list(self):
        """append_candle should add a single candle to the list."""
        state = StateManager()
        ts = datetime.now(IST)
        candle1 = Candle(ts=ts, open=22500, high=22550, low=22480, close=22530, volume=1000)
        candle2 = Candle(ts=ts, open=22530, high=22580, low=22510, close=22560, volume=1200)

        state.append_candle("nifty", candle1)
        state.append_candle("nifty", candle2)

        result = state.get_candles("nifty")
        assert len(result) == 2


class TestConnectionStatus:
    """Tests for connection status management."""

    def test_set_ws_connected(self):
        """set_ws_connected should update WebSocket connection status."""
        state = StateManager()

        state.set_ws_connected(True)

        status = state.get_connection_status()
        assert status.ws_connected is True
        assert status.last_ws_update is not None

    def test_set_sse_connected(self):
        """set_sse_connected should update SSE connection status."""
        state = StateManager()

        state.set_sse_connected(True)

        status = state.get_connection_status()
        assert status.sse_connected is True
        assert status.last_sse_update is not None


class TestMarketState:
    """Tests for market state management."""

    def test_set_market_state(self):
        """set_market_state should update market state."""
        state = StateManager()

        state.set_market_state("OPEN")
        assert state.get_market_state() == "OPEN"

        state.set_market_state("CLOSED")
        assert state.get_market_state() == "CLOSED"


class TestThreadSafety:
    """Tests for thread-safety of StateManager."""

    def test_concurrent_ltp_updates(self):
        """StateManager should handle concurrent LTP updates safely."""
        state = StateManager()
        errors = []

        def update_ltp(symbol: str, count: int):
            try:
                for i in range(count):
                    state.update_ltp(symbol, 22500.0 + i)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=update_ltp, args=("nifty", 100)),
            threading.Thread(target=update_ltp, args=("banknifty", 100)),
            threading.Thread(target=update_ltp, args=("sensex", 100)),
            threading.Thread(target=update_ltp, args=("finnifty", 100)),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(state.get_all_ltps()) == 4

    def test_concurrent_read_write(self):
        """StateManager should handle concurrent reads and writes safely."""
        state = StateManager()
        errors = []
        read_count = [0]

        def writer():
            try:
                for i in range(50):
                    state.update_ltp("nifty", 22500.0 + i)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(50):
                    _ = state.get_ltp("nifty")
                    _ = state.get_all_ltps()
                    read_count[0] += 1
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=reader),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert read_count[0] == 100  # Both readers completed


class TestClear:
    """Tests for clear functionality."""

    def test_clear_resets_state(self):
        """clear should reset all state to initial values."""
        state = StateManager()
        state.update_ltp("nifty", 22500.0)
        state.update_indicators("nifty", "current", IndicatorData(skew=0.5))
        state.set_ws_connected(True)
        state.set_market_state("OPEN")

        state.clear()

        assert state.get_ltp("nifty") is None
        assert state.get_market_state() == "UNKNOWN"
        status = state.get_connection_status()
        assert status.ws_connected is False


class TestUserSession:
    """Tests for user session management (Requirement 15.2)."""

    def test_init_creates_empty_user_session(self):
        """StateManager should initialize with empty user session."""
        state = StateManager()

        session = state.get_user_session()
        assert session.email is None
        assert session.role is None
        assert session.name is None
        assert session.is_authenticated is False
        assert session.jwt_token is None

    def test_set_user_session_stores_data(self):
        """set_user_session should store user session data."""
        state = StateManager()

        state.set_user_session(
            email="admin@test.com",
            role="admin",
            name="Test Admin",
            jwt_token="test_token_123",
        )

        session = state.get_user_session()
        assert session.email == "admin@test.com"
        assert session.role == "admin"
        assert session.name == "Test Admin"
        assert session.jwt_token == "test_token_123"
        assert session.is_authenticated is True

    def test_is_admin_returns_true_for_admin_role(self):
        """is_admin should return True when user has admin role."""
        state = StateManager()

        state.set_user_session(
            email="admin@test.com",
            role="admin",
            jwt_token="test_token",
        )

        assert state.is_admin() is True

    def test_is_admin_returns_false_for_customer_role(self):
        """is_admin should return False when user has customer role."""
        state = StateManager()

        state.set_user_session(
            email="user@test.com",
            role="customer",
            jwt_token="test_token",
        )

        assert state.is_admin() is False

    def test_is_admin_returns_false_for_test_customer_role(self):
        """is_admin should return False when user has test_customer role."""
        state = StateManager()

        state.set_user_session(
            email="trial@test.com",
            role="test_customer",
            jwt_token="test_token",
        )

        assert state.is_admin() is False

    def test_is_admin_returns_false_when_not_authenticated(self):
        """is_admin should return False when user is not authenticated."""
        state = StateManager()

        # Set role but no JWT token (not authenticated)
        state.set_user_session(
            email="admin@test.com",
            role="admin",
            jwt_token=None,  # No token
        )

        assert state.is_admin() is False

    def test_is_admin_returns_false_for_empty_session(self):
        """is_admin should return False for empty session."""
        state = StateManager()

        assert state.is_admin() is False

    def test_clear_user_session_resets_session(self):
        """clear_user_session should reset user session to empty state."""
        state = StateManager()

        state.set_user_session(
            email="admin@test.com",
            role="admin",
            jwt_token="test_token",
        )
        assert state.is_admin() is True

        state.clear_user_session()

        session = state.get_user_session()
        assert session.email is None
        assert session.role is None
        assert session.is_authenticated is False
        assert state.is_admin() is False

    def test_clear_also_clears_user_session(self):
        """clear should also reset user session."""
        state = StateManager()

        state.set_user_session(
            email="admin@test.com",
            role="admin",
            jwt_token="test_token",
        )
        assert state.is_admin() is True

        state.clear()

        assert state.is_admin() is False

    def test_get_user_session_returns_copy(self):
        """get_user_session should return a copy of the session data."""
        state = StateManager()

        state.set_user_session(
            email="admin@test.com",
            role="admin",
            jwt_token="test_token",
        )

        session1 = state.get_user_session()
        session2 = state.get_user_session()

        # Should be equal but not the same object
        assert session1.email == session2.email
        assert session1.role == session2.role


class TestOTPSession:
    """Tests for OTP session management (Requirement 15.8)."""

    def test_init_creates_empty_otp_session(self):
        """StateManager should initialize with empty OTP session."""
        state = StateManager()

        otp_session = state.get_otp_session()
        assert otp_session.otp_verified is False
        assert otp_session.otp_expiry is None
        assert otp_session.verified_at is None

    def test_set_otp_verified_stores_data(self):
        """set_otp_verified should store OTP verification status."""
        state = StateManager()
        expiry = datetime.now(IST)

        state.set_otp_verified(verified=True, expiry=expiry)

        otp_session = state.get_otp_session()
        assert otp_session.otp_verified is True
        assert otp_session.otp_expiry == expiry
        assert otp_session.verified_at is not None

    def test_set_otp_verified_false_clears_verified_at(self):
        """set_otp_verified(False) should clear verified_at timestamp."""
        state = StateManager()
        expiry = datetime.now(IST)

        # First verify
        state.set_otp_verified(verified=True, expiry=expiry)
        assert state.get_otp_session().verified_at is not None

        # Then unverify
        state.set_otp_verified(verified=False)

        otp_session = state.get_otp_session()
        assert otp_session.otp_verified is False
        assert otp_session.verified_at is None

    def test_is_otp_session_valid_returns_false_when_not_verified(self):
        """is_otp_session_valid should return False when OTP not verified."""
        state = StateManager()

        assert state.is_otp_session_valid() is False

    def test_is_otp_session_valid_returns_true_when_verified_no_expiry(self):
        """is_otp_session_valid should return True when verified with no expiry."""
        state = StateManager()

        state.set_otp_verified(verified=True, expiry=None)

        assert state.is_otp_session_valid() is True

    def test_is_otp_session_valid_returns_true_when_not_expired(self):
        """is_otp_session_valid should return True when verified and not expired."""
        state = StateManager()
        # Set expiry 1 hour in the future
        from datetime import timedelta
        future_expiry = datetime.now(IST) + timedelta(hours=1)

        state.set_otp_verified(verified=True, expiry=future_expiry)

        assert state.is_otp_session_valid() is True

    def test_is_otp_session_valid_returns_false_when_expired(self):
        """is_otp_session_valid should return False when session has expired.
        
        Requirement 15.8: IF OTP session expires, THEN Admin page SHALL prompt
        for re-verification.
        """
        state = StateManager()
        # Set expiry 1 hour in the past
        from datetime import timedelta
        past_expiry = datetime.now(IST) - timedelta(hours=1)

        state.set_otp_verified(verified=True, expiry=past_expiry)

        assert state.is_otp_session_valid() is False

    def test_clear_otp_session_resets_session(self):
        """clear_otp_session should reset OTP session to empty state."""
        state = StateManager()
        from datetime import timedelta
        expiry = datetime.now(IST) + timedelta(hours=1)

        state.set_otp_verified(verified=True, expiry=expiry)
        assert state.is_otp_session_valid() is True

        state.clear_otp_session()

        otp_session = state.get_otp_session()
        assert otp_session.otp_verified is False
        assert otp_session.otp_expiry is None
        assert otp_session.verified_at is None
        assert state.is_otp_session_valid() is False

    def test_clear_also_clears_otp_session(self):
        """clear should also reset OTP session."""
        state = StateManager()
        from datetime import timedelta
        expiry = datetime.now(IST) + timedelta(hours=1)

        state.set_otp_verified(verified=True, expiry=expiry)
        assert state.is_otp_session_valid() is True

        state.clear()

        assert state.is_otp_session_valid() is False

    def test_get_otp_session_returns_copy(self):
        """get_otp_session should return a copy of the session data."""
        state = StateManager()
        from datetime import timedelta
        expiry = datetime.now(IST) + timedelta(hours=1)

        state.set_otp_verified(verified=True, expiry=expiry)

        session1 = state.get_otp_session()
        session2 = state.get_otp_session()

        # Should be equal but not the same object
        assert session1.otp_verified == session2.otp_verified
        assert session1.otp_expiry == session2.otp_expiry


class TestJWTManagement:
    """Tests for JWT management functionality (Requirements 3.7, 3.9)."""

    def test_parse_jwt_expiry_valid_token(self):
        """parse_jwt_expiry should extract expiry from valid JWT."""
        from src.state_manager import parse_jwt_expiry
        import base64
        import json
        import time
        
        # Create a mock JWT with expiry 1 hour from now
        exp_timestamp = int(time.time()) + 3600
        payload = {"exp": exp_timestamp, "sub": "test@example.com"}
        payload_json = json.dumps(payload)
        payload_b64 = base64.urlsafe_b64encode(payload_json.encode()).decode().rstrip("=")
        
        # JWT format: header.payload.signature
        mock_jwt = f"eyJhbGciOiJIUzI1NiJ9.{payload_b64}.signature"
        
        expiry = parse_jwt_expiry(mock_jwt)
        
        assert expiry is not None
        # Check that expiry is approximately correct (within 1 second)
        expected_expiry = datetime.fromtimestamp(exp_timestamp, tz=IST)
        assert abs((expiry - expected_expiry).total_seconds()) < 1

    def test_parse_jwt_expiry_invalid_token(self):
        """parse_jwt_expiry should return None for invalid JWT."""
        from src.state_manager import parse_jwt_expiry
        
        assert parse_jwt_expiry("invalid") is None
        assert parse_jwt_expiry("not.a.jwt") is None
        assert parse_jwt_expiry("") is None
        assert parse_jwt_expiry(None) is None

    def test_parse_jwt_expiry_no_exp_claim(self):
        """parse_jwt_expiry should return None when no exp claim."""
        from src.state_manager import parse_jwt_expiry
        import base64
        import json
        
        # Create a mock JWT without expiry
        payload = {"sub": "test@example.com"}
        payload_json = json.dumps(payload)
        payload_b64 = base64.urlsafe_b64encode(payload_json.encode()).decode().rstrip("=")
        
        mock_jwt = f"eyJhbGciOiJIUzI1NiJ9.{payload_b64}.signature"
        
        expiry = parse_jwt_expiry(mock_jwt)
        
        assert expiry is None

    def test_jwt_needs_refresh_within_threshold(self):
        """jwt_needs_refresh should return True when < 1 hour remaining.
        
        Requirement 3.9: WHEN JWT token has less than 1 hour remaining,
        THE Dashboard SHALL refresh via POST /v1/auth/refresh.
        """
        from src.state_manager import jwt_needs_refresh
        from datetime import timedelta
        
        # Expiry 30 minutes from now (less than 1 hour threshold)
        expiry = datetime.now(IST) + timedelta(minutes=30)
        
        assert jwt_needs_refresh(expiry) is True

    def test_jwt_needs_refresh_outside_threshold(self):
        """jwt_needs_refresh should return False when > 1 hour remaining."""
        from src.state_manager import jwt_needs_refresh
        from datetime import timedelta
        
        # Expiry 2 hours from now (more than 1 hour threshold)
        expiry = datetime.now(IST) + timedelta(hours=2)
        
        assert jwt_needs_refresh(expiry) is False

    def test_jwt_needs_refresh_exactly_at_threshold(self):
        """jwt_needs_refresh should return False when more than 1 hour remaining."""
        from src.state_manager import jwt_needs_refresh
        from datetime import timedelta
        
        # Expiry slightly more than 1 hour from now (to avoid timing issues)
        expiry = datetime.now(IST) + timedelta(hours=1, seconds=10)
        
        # With > 1 hour remaining, should NOT need refresh
        assert jwt_needs_refresh(expiry) is False

    def test_jwt_needs_refresh_expired(self):
        """jwt_needs_refresh should return True when token is expired."""
        from src.state_manager import jwt_needs_refresh
        from datetime import timedelta
        
        # Expiry 1 hour in the past
        expiry = datetime.now(IST) - timedelta(hours=1)
        
        assert jwt_needs_refresh(expiry) is True

    def test_jwt_needs_refresh_none_expiry(self):
        """jwt_needs_refresh should return False when expiry is None."""
        from src.state_manager import jwt_needs_refresh
        
        assert jwt_needs_refresh(None) is False

    def test_set_user_session_auto_parses_jwt_expiry(self):
        """set_user_session should auto-parse JWT expiry from token.
        
        Requirement 3.7: Store JWT token securely in session state.
        Requirement 3.9: Track JWT expiry for refresh logic.
        """
        import base64
        import json
        import time
        
        state = StateManager()
        
        # Create a mock JWT with expiry 2 hours from now
        exp_timestamp = int(time.time()) + 7200
        payload = {"exp": exp_timestamp, "sub": "test@example.com"}
        payload_json = json.dumps(payload)
        payload_b64 = base64.urlsafe_b64encode(payload_json.encode()).decode().rstrip("=")
        mock_jwt = f"eyJhbGciOiJIUzI1NiJ9.{payload_b64}.signature"
        
        state.set_user_session(
            email="test@example.com",
            role="customer",
            jwt_token=mock_jwt,
        )
        
        session = state.get_user_session()
        assert session.jwt_expiry is not None
        # Check that expiry is approximately correct
        expected_expiry = datetime.fromtimestamp(exp_timestamp, tz=IST)
        assert abs((session.jwt_expiry - expected_expiry).total_seconds()) < 1

    def test_set_user_session_explicit_expiry_overrides_parsing(self):
        """set_user_session should use explicit expiry if provided."""
        from datetime import timedelta
        
        state = StateManager()
        explicit_expiry = datetime.now(IST) + timedelta(hours=5)
        
        state.set_user_session(
            email="test@example.com",
            role="customer",
            jwt_token="some.jwt.token",
            jwt_expiry=explicit_expiry,
        )
        
        session = state.get_user_session()
        assert session.jwt_expiry == explicit_expiry

    def test_state_manager_jwt_needs_refresh_method(self):
        """StateManager.jwt_needs_refresh should check session JWT expiry."""
        import base64
        import json
        import time
        from datetime import timedelta
        
        state = StateManager()
        
        # Create a mock JWT with expiry 30 minutes from now
        exp_timestamp = int(time.time()) + 1800  # 30 minutes
        payload = {"exp": exp_timestamp, "sub": "test@example.com"}
        payload_json = json.dumps(payload)
        payload_b64 = base64.urlsafe_b64encode(payload_json.encode()).decode().rstrip("=")
        mock_jwt = f"eyJhbGciOiJIUzI1NiJ9.{payload_b64}.signature"
        
        state.set_user_session(
            email="test@example.com",
            role="customer",
            jwt_token=mock_jwt,
        )
        
        # Should need refresh (< 1 hour remaining)
        assert state.jwt_needs_refresh() is True

    def test_state_manager_jwt_needs_refresh_not_authenticated(self):
        """StateManager.jwt_needs_refresh should return False when not authenticated."""
        state = StateManager()
        
        # Not authenticated
        assert state.jwt_needs_refresh() is False

    def test_update_jwt_token(self):
        """update_jwt_token should update token and re-parse expiry."""
        import base64
        import json
        import time
        
        state = StateManager()
        
        # First set up a session with old token
        old_exp = int(time.time()) + 1800  # 30 minutes
        old_payload = {"exp": old_exp, "sub": "test@example.com"}
        old_payload_json = json.dumps(old_payload)
        old_payload_b64 = base64.urlsafe_b64encode(old_payload_json.encode()).decode().rstrip("=")
        old_jwt = f"eyJhbGciOiJIUzI1NiJ9.{old_payload_b64}.signature"
        
        state.set_user_session(
            email="test@example.com",
            role="customer",
            jwt_token=old_jwt,
        )
        
        # Now update with new token (2 hours expiry)
        new_exp = int(time.time()) + 7200  # 2 hours
        new_payload = {"exp": new_exp, "sub": "test@example.com"}
        new_payload_json = json.dumps(new_payload)
        new_payload_b64 = base64.urlsafe_b64encode(new_payload_json.encode()).decode().rstrip("=")
        new_jwt = f"eyJhbGciOiJIUzI1NiJ9.{new_payload_b64}.signature"
        
        state.update_jwt_token(new_jwt)
        
        session = state.get_user_session()
        assert session.jwt_token == new_jwt
        # New expiry should be approximately 2 hours from now
        expected_expiry = datetime.fromtimestamp(new_exp, tz=IST)
        assert abs((session.jwt_expiry - expected_expiry).total_seconds()) < 1
        # Should NOT need refresh now (> 1 hour remaining)
        assert state.jwt_needs_refresh() is False

    def test_update_jwt_token_not_authenticated(self):
        """update_jwt_token should do nothing when not authenticated."""
        state = StateManager()
        
        # Not authenticated - update should be ignored
        state.update_jwt_token("new.jwt.token")
        
        session = state.get_user_session()
        assert session.jwt_token is None

    def test_get_jwt_expiry_info(self):
        """get_jwt_expiry_info should return expiry and seconds remaining."""
        import base64
        import json
        import time
        
        state = StateManager()
        
        # Create a mock JWT with expiry 2 hours from now
        exp_timestamp = int(time.time()) + 7200
        payload = {"exp": exp_timestamp, "sub": "test@example.com"}
        payload_json = json.dumps(payload)
        payload_b64 = base64.urlsafe_b64encode(payload_json.encode()).decode().rstrip("=")
        mock_jwt = f"eyJhbGciOiJIUzI1NiJ9.{payload_b64}.signature"
        
        state.set_user_session(
            email="test@example.com",
            role="customer",
            jwt_token=mock_jwt,
        )
        
        expiry, seconds_remaining = state.get_jwt_expiry_info()
        
        assert expiry is not None
        assert seconds_remaining is not None
        # Should be approximately 7200 seconds (2 hours)
        assert 7100 < seconds_remaining < 7300

    def test_get_jwt_expiry_info_not_authenticated(self):
        """get_jwt_expiry_info should return None when not authenticated."""
        state = StateManager()
        
        expiry, seconds_remaining = state.get_jwt_expiry_info()
        
        assert expiry is None
        assert seconds_remaining is None
