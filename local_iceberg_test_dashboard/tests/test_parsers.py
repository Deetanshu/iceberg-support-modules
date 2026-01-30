# Iceberg Test Dashboard - Parser Tests
"""
Unit tests for data parsers.

Tests for:
- Bootstrap response parsing (Requirement 5.4, 5.5)
- SSE event parsing (Requirement 12.3, 12.4, 12.5)
- Columnar data format handling
- Date filtering
"""

import pytest
from datetime import datetime, timedelta
import pytz

from src.parsers import (
    parse_timestamp,
    parse_columnar_candles,
    candles_to_columnar,
    filter_candles_to_today,
    parse_columnar_option_chain,
    parse_indicator_series,
    parse_bootstrap_response,
    parse_indicator_update,
    parse_option_chain_update,
    parse_snapshot_event,
    parse_sse_event,
    get_event_type,
    handle_sse_event,
)
from src.models import Candle, IndicatorData, OptionChainData, OptionStrike

IST = pytz.timezone("Asia/Kolkata")


class TestParseTimestamp:
    """Tests for timestamp parsing."""

    def test_parse_iso_string(self):
        """Should parse ISO format timestamp strings."""
        ts = parse_timestamp("2026-01-20T10:30:00")
        assert ts.year == 2026
        assert ts.month == 1
        assert ts.day == 20
        assert ts.hour == 10
        assert ts.minute == 30

    def test_parse_iso_string_with_timezone(self):
        """Should parse ISO format with timezone."""
        ts = parse_timestamp("2026-01-20T10:30:00+05:30")
        assert ts.tzinfo is not None

    def test_parse_unix_timestamp_seconds(self):
        """Should parse Unix timestamp in seconds."""
        # 2026-01-20 10:30:00 IST
        ts = parse_timestamp(1768893000)
        assert ts.tzinfo is not None

    def test_parse_unix_timestamp_milliseconds(self):
        """Should parse Unix timestamp in milliseconds."""
        ts = parse_timestamp(1768893000000)
        assert ts.tzinfo is not None

    def test_parse_datetime_object(self):
        """Should handle datetime objects."""
        dt = datetime(2026, 1, 20, 10, 30, 0, tzinfo=IST)
        ts = parse_timestamp(dt)
        assert ts == dt

    def test_parse_none_returns_now(self):
        """Should return current time for None input."""
        ts = parse_timestamp(None)
        assert ts.tzinfo is not None
        assert (datetime.now(IST) - ts).total_seconds() < 5


class TestParseColumnarCandles:
    """Tests for columnar candle parsing (Requirement 5.5)."""

    def test_parse_valid_columnar_data(self):
        """Should parse valid columnar candle data."""
        candles_raw = {
            "ts": ["2026-01-20T10:30:00", "2026-01-20T10:35:00"],
            "open": [22500.0, 22510.0],
            "high": [22520.0, 22530.0],
            "low": [22490.0, 22500.0],
            "close": [22510.0, 22525.0],
            "volume": [1000, 1200],
        }

        candles = parse_columnar_candles(candles_raw)

        assert len(candles) == 2
        assert candles[0].open == 22500.0
        assert candles[0].close == 22510.0
        assert candles[0].volume == 1000
        assert candles[1].open == 22510.0
        assert candles[1].close == 22525.0

    def test_parse_empty_data(self):
        """Should return empty list for empty data."""
        assert parse_columnar_candles({}) == []
        assert parse_columnar_candles(None) == []

    def test_parse_missing_ts(self):
        """Should return empty list if ts array is missing."""
        candles_raw = {
            "open": [22500.0],
            "high": [22520.0],
            "low": [22490.0],
            "close": [22510.0],
        }
        assert parse_columnar_candles(candles_raw) == []

    def test_parse_handles_missing_volume(self):
        """Should handle missing volume array."""
        candles_raw = {
            "ts": ["2026-01-20T10:30:00"],
            "open": [22500.0],
            "high": [22520.0],
            "low": [22490.0],
            "close": [22510.0],
        }

        candles = parse_columnar_candles(candles_raw)

        assert len(candles) == 1
        assert candles[0].volume == 0


class TestCandlesToColumnar:
    """Tests for candle to columnar conversion."""

    def test_convert_candles_to_columnar(self):
        """Should convert Candle objects to columnar format."""
        ts = datetime(2026, 1, 20, 10, 30, 0, tzinfo=IST)
        candles = [
            Candle(ts=ts, open=22500.0, high=22520.0, low=22490.0, close=22510.0, volume=1000),
        ]

        columnar = candles_to_columnar(candles)

        assert len(columnar["ts"]) == 1
        assert columnar["open"][0] == 22500.0
        assert columnar["close"][0] == 22510.0
        assert columnar["volume"][0] == 1000

    def test_convert_empty_list(self):
        """Should handle empty candle list."""
        columnar = candles_to_columnar([])

        assert columnar["ts"] == []
        assert columnar["open"] == []


class TestFilterCandlesToToday:
    """Tests for candle date filtering (Requirement 5.4)."""

    def test_filter_keeps_today_candles(self):
        """Should keep candles from today."""
        today = datetime.now(IST)
        candles = [
            Candle(ts=today, open=22500.0, high=22520.0, low=22490.0, close=22510.0, volume=1000),
        ]

        filtered = filter_candles_to_today(candles)

        assert len(filtered) == 1

    def test_filter_removes_yesterday_candles(self):
        """Should remove candles from yesterday."""
        today = datetime.now(IST)
        yesterday = today - timedelta(days=1)
        candles = [
            Candle(ts=yesterday, open=22500.0, high=22520.0, low=22490.0, close=22510.0, volume=1000),
        ]

        filtered = filter_candles_to_today(candles)

        assert len(filtered) == 0

    def test_filter_mixed_dates(self):
        """Should filter mixed date candles correctly."""
        today = datetime.now(IST)
        yesterday = today - timedelta(days=1)
        candles = [
            Candle(ts=yesterday, open=22400.0, high=22420.0, low=22390.0, close=22410.0, volume=800),
            Candle(ts=today, open=22500.0, high=22520.0, low=22490.0, close=22510.0, volume=1000),
            Candle(ts=today, open=22510.0, high=22530.0, low=22500.0, close=22525.0, volume=1200),
        ]

        filtered = filter_candles_to_today(candles)

        assert len(filtered) == 2
        assert all(c.ts.date() == today.date() for c in filtered)

    def test_filter_with_reference_date(self):
        """Should filter using provided reference date."""
        ref_date = datetime(2026, 1, 15, tzinfo=IST)
        candles = [
            Candle(ts=datetime(2026, 1, 14, 10, 0, tzinfo=IST), open=22400.0, high=22420.0, low=22390.0, close=22410.0, volume=800),
            Candle(ts=datetime(2026, 1, 15, 10, 0, tzinfo=IST), open=22500.0, high=22520.0, low=22490.0, close=22510.0, volume=1000),
        ]

        filtered = filter_candles_to_today(candles, reference_date=ref_date)

        assert len(filtered) == 1
        assert filtered[0].ts.day == 15


class TestParseColumnarOptionChain:
    """Tests for option chain parsing."""

    def test_parse_valid_option_chain(self):
        """Should parse valid option chain data."""
        oc_raw = {
            "expiry": "2026-01-23",
            "underlying": 22500.0,
            "columns": {
                "strike": [22400, 22500, 22600],
                "call_oi": [1000, 1500, 2000],
                "put_oi": [2000, 1800, 1500],
                "call_coi": [100, 150, 200],
                "put_coi": [-50, -100, -150],
                "skew": [0.3, 0.1, -0.2],
            },
            "ts": "2026-01-20T10:30:00",
        }

        result = parse_columnar_option_chain(oc_raw)

        assert result is not None
        assert result.expiry == "2026-01-23"
        assert result.underlying == 22500.0
        assert len(result.strikes) == 3
        assert result.strikes[0].strike == 22400
        assert result.strikes[0].call_oi == 1000
        assert result.strikes[1].strike_skew == 0.1

    def test_parse_empty_option_chain(self):
        """Should return None for empty data."""
        assert parse_columnar_option_chain({}) is None
        assert parse_columnar_option_chain(None) is None

    def test_parse_missing_columns(self):
        """Should return None if columns missing."""
        oc_raw = {"expiry": "2026-01-23", "underlying": 22500.0}
        assert parse_columnar_option_chain(oc_raw) is None


class TestParseIndicatorSeries:
    """Tests for indicator parsing."""

    def test_parse_valid_indicators(self):
        """Should parse valid indicator data."""
        indicator_raw = {
            "skew": 0.35,
            "pcr": 1.2,
            "signal": "BUY",
            "skew_confidence": 0.8,
            "rsi": 55.0,
            "ema_5": 22500.0,
            "ema_21": 22450.0,
            "ts": "2026-01-20T10:30:00",
        }

        result = parse_indicator_series(indicator_raw)

        assert result is not None
        assert result.skew == 0.35
        assert result.pcr == 1.2
        assert result.signal == "BUY"
        assert result.rsi == 55.0

    def test_parse_empty_indicators(self):
        """Should return None for empty data."""
        assert parse_indicator_series({}) is None
        assert parse_indicator_series(None) is None


class TestParseBootstrapResponse:
    """Tests for bootstrap response parsing."""

    def test_parse_valid_bootstrap(self):
        """Should parse valid bootstrap response."""
        response = {
            "data": {
                "nifty": {
                    "current": {
                        "candles_5m": {
                            "ts": [datetime.now(IST).isoformat()],
                            "open": [22500.0],
                            "high": [22520.0],
                            "low": [22490.0],
                            "close": [22510.0],
                            "volume": [1000],
                        },
                        "indicators": {
                            "skew": 0.35,
                            "signal": "BUY",
                        },
                    }
                }
            }
        }

        result = parse_bootstrap_response(response)

        assert "nifty" in result
        assert "current" in result["nifty"]
        assert len(result["nifty"]["current"].candles) == 1
        assert result["nifty"]["current"].indicators.skew == 0.35

    def test_parse_empty_bootstrap(self):
        """Should handle empty bootstrap response."""
        result = parse_bootstrap_response({})
        assert result == {}

        result = parse_bootstrap_response({"data": {}})
        assert result == {}

    def test_parse_filters_old_candles(self):
        """Should filter candles to today by default."""
        yesterday = (datetime.now(IST) - timedelta(days=1)).isoformat()
        response = {
            "data": {
                "nifty": {
                    "current": {
                        "candles_5m": {
                            "ts": [yesterday],
                            "open": [22500.0],
                            "high": [22520.0],
                            "low": [22490.0],
                            "close": [22510.0],
                            "volume": [1000],
                        },
                    }
                }
            }
        }

        result = parse_bootstrap_response(response, filter_to_today=True)

        assert "nifty" in result
        assert len(result["nifty"]["current"].candles) == 0

    def test_parse_without_date_filter(self):
        """Should keep all candles when filter disabled."""
        yesterday = (datetime.now(IST) - timedelta(days=1)).isoformat()
        response = {
            "data": {
                "nifty": {
                    "current": {
                        "candles_5m": {
                            "ts": [yesterday],
                            "open": [22500.0],
                            "high": [22520.0],
                            "low": [22490.0],
                            "close": [22510.0],
                            "volume": [1000],
                        },
                    }
                }
            }
        }

        result = parse_bootstrap_response(response, filter_to_today=False)

        assert len(result["nifty"]["current"].candles) == 1


class TestParseIndicatorUpdate:
    """Tests for SSE indicator_update parsing (Requirement 12.4)."""

    def test_parse_indicator_update(self):
        """Should parse indicator_update event."""
        event = {
            "symbol": "nifty",
            "mode": "current",
            "indicators": {
                "skew": 0.4,
                "pcr": 1.1,
                "signal": "BUY",
                "rsi": 60.0,
            },
            "timestamp": "2026-01-20T10:30:00",
        }

        symbol, mode, indicators = parse_indicator_update(event)

        assert symbol == "nifty"
        assert mode == "current"
        assert indicators.skew == 0.4
        assert indicators.signal == "BUY"

    def test_parse_indicator_update_normalizes_case(self):
        """Should normalize symbol and mode to lowercase."""
        event = {
            "symbol": "NIFTY",
            "mode": "CURRENT",
            "indicators": {"skew": 0.4},
        }

        symbol, mode, _ = parse_indicator_update(event)

        assert symbol == "nifty"
        assert mode == "current"


class TestParseOptionChainUpdate:
    """Tests for SSE option_chain_update parsing (Requirement 12.5)."""

    def test_parse_option_chain_update(self):
        """Should parse option_chain_update event."""
        event = {
            "symbol": "nifty",
            "mode": "current",
            "expiry": "2026-01-23",
            "underlying": 22500.0,
            "strikes": [
                {"strike": 22400, "call_oi": 1000, "put_oi": 2000, "call_coi": 100, "put_coi": -50},
                {"strike": 22500, "call_oi": 1500, "put_oi": 1800},
            ],
            "timestamp": "2026-01-20T10:30:00",
        }

        symbol, mode, option_chain = parse_option_chain_update(event)

        assert symbol == "nifty"
        assert mode == "current"
        assert option_chain.expiry == "2026-01-23"
        assert len(option_chain.strikes) == 2
        assert option_chain.strikes[0].call_coi == 100


class TestParseSSEEvent:
    """Tests for raw SSE event parsing."""

    def test_parse_data_prefix(self):
        """Should parse event with 'data:' prefix."""
        raw = 'data: {"event": "heartbeat", "ts": "2026-01-20T10:30:00"}'
        result = parse_sse_event(raw)

        assert result is not None
        assert result["event"] == "heartbeat"

    def test_parse_data_space_prefix(self):
        """Should parse event with 'data: ' prefix."""
        raw = 'data: {"event": "heartbeat"}'
        result = parse_sse_event(raw)

        assert result is not None

    def test_parse_invalid_json(self):
        """Should return None for invalid JSON."""
        result = parse_sse_event("data: not json")
        assert result is None

    def test_parse_empty_string(self):
        """Should return None for empty string."""
        assert parse_sse_event("") is None
        assert parse_sse_event(None) is None


class TestGetEventType:
    """Tests for event type extraction."""

    def test_get_event_type_from_event_type(self):
        """Should extract from event_type field."""
        event = {"event_type": "indicator_update"}
        assert get_event_type(event) == "indicator_update"

    def test_get_event_type_from_event(self):
        """Should extract from event field."""
        event = {"event": "heartbeat"}
        assert get_event_type(event) == "heartbeat"

    def test_get_event_type_from_type(self):
        """Should extract from type field."""
        event = {"type": "snapshot"}
        assert get_event_type(event) == "snapshot"

    def test_get_event_type_unknown(self):
        """Should return 'unknown' if no type field."""
        event = {"data": {}}
        assert get_event_type(event) == "unknown"


class TestHandleSSEEvent:
    """Tests for SSE event routing."""

    def test_handle_indicator_update(self):
        """Should route indicator_update to correct parser."""
        event = {
            "event_type": "indicator_update",
            "symbol": "nifty",
            "mode": "current",
            "indicators": {"skew": 0.5},
        }

        event_type, data = handle_sse_event(event)

        assert event_type == "indicator_update"
        assert data[0] == "nifty"  # symbol
        assert data[1] == "current"  # mode
        assert data[2].skew == 0.5  # IndicatorData

    def test_handle_option_chain_update(self):
        """Should route option_chain_update to correct parser."""
        event = {
            "event_type": "option_chain_update",
            "symbol": "nifty",
            "mode": "current",
            "expiry": "2026-01-23",
            "underlying": 22500.0,
            "strikes": [],
        }

        event_type, data = handle_sse_event(event)

        assert event_type == "option_chain_update"
        assert data[0] == "nifty"
        assert data[2].expiry == "2026-01-23"

    def test_handle_market_closed(self):
        """Should handle market_closed event."""
        event = {"event_type": "market_closed"}

        event_type, data = handle_sse_event(event)

        assert event_type == "market_closed"
        assert data is None

    def test_handle_heartbeat(self):
        """Should handle heartbeat event."""
        event = {"event_type": "heartbeat", "timestamp": "2026-01-20T10:30:00"}

        event_type, data = handle_sse_event(event)

        assert event_type == "heartbeat"
        assert data is not None  # timestamp

    def test_handle_refresh_recommended(self):
        """Should handle refresh_recommended event."""
        event = {"event_type": "refresh_recommended"}

        event_type, data = handle_sse_event(event)

        assert event_type == "refresh_recommended"
        assert data is None

    def test_handle_unknown_event(self):
        """Should pass through unknown events."""
        event = {"event_type": "custom_event", "data": "test"}

        event_type, data = handle_sse_event(event)

        assert event_type == "custom_event"
        assert data == event
