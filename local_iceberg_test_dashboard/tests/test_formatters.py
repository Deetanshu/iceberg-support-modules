# Iceberg Test Dashboard - Formatter Tests
"""
Unit tests for formatting utilities.

Tests: format_price, format_percentage, format_timestamp, check_staleness
Requirements: 2.4, 2.5, 17.6
"""

import pytest
from datetime import datetime, timedelta
import pytz

from src.formatters import (
    format_price,
    format_percentage,
    format_timestamp,
    format_timestamp_iso,
    check_staleness,
    get_staleness_age,
    format_staleness_message,
    IST,
    STALENESS_THRESHOLD_SECONDS,
)


class TestFormatPrice:
    """Tests for format_price function - Requirement 2.5"""

    def test_format_price_with_float(self):
        """Price with float value has exactly 2 decimal places."""
        assert format_price(12345.6789) == "12345.68"

    def test_format_price_with_integer(self):
        """Price with integer value has exactly 2 decimal places."""
        assert format_price(100) == "100.00"

    def test_format_price_with_zero(self):
        """Zero price formatted correctly."""
        assert format_price(0) == "0.00"

    def test_format_price_with_none(self):
        """None value returns placeholder."""
        assert format_price(None) == "--"

    def test_format_price_rounds_correctly(self):
        """Price rounds to 2 decimal places correctly."""
        assert format_price(99.995) == "100.00"
        assert format_price(99.994) == "99.99"

    def test_format_price_large_number(self):
        """Large price formatted correctly."""
        assert format_price(50000.12) == "50000.12"


class TestFormatPercentage:
    """Tests for format_percentage function - Requirement 2.5"""

    def test_format_percentage_positive(self):
        """Positive percentage has 2 decimal places and % sign."""
        assert format_percentage(12.3456) == "12.35%"

    def test_format_percentage_negative(self):
        """Negative percentage has 2 decimal places and % sign."""
        assert format_percentage(-5.1) == "-5.10%"

    def test_format_percentage_zero(self):
        """Zero percentage formatted correctly."""
        assert format_percentage(0) == "0.00%"

    def test_format_percentage_with_none(self):
        """None value returns placeholder."""
        assert format_percentage(None) == "--"

    def test_format_percentage_integer(self):
        """Integer percentage has 2 decimal places."""
        assert format_percentage(5) == "5.00%"


class TestFormatTimestamp:
    """Tests for format_timestamp function - Requirement 2.4"""

    def test_format_timestamp_includes_ist(self):
        """Timestamp includes IST label."""
        ts = datetime(2026, 1, 20, 10, 30, 45, tzinfo=IST)
        result = format_timestamp(ts)
        assert "IST" in result

    def test_format_timestamp_time_only(self):
        """Timestamp without date shows time only."""
        ts = datetime(2026, 1, 20, 10, 30, 45, tzinfo=IST)
        result = format_timestamp(ts, include_date=False)
        assert result == "10:30:45 IST"

    def test_format_timestamp_with_date(self):
        """Timestamp with date shows full datetime."""
        ts = datetime(2026, 1, 20, 10, 30, 45, tzinfo=IST)
        result = format_timestamp(ts, include_date=True)
        assert result == "2026-01-20 10:30:45 IST"

    def test_format_timestamp_without_timezone_label(self):
        """Timestamp without timezone label."""
        ts = datetime(2026, 1, 20, 10, 30, 45, tzinfo=IST)
        result = format_timestamp(ts, include_timezone=False)
        assert result == "10:30:45"
        assert "IST" not in result

    def test_format_timestamp_converts_utc_to_ist(self):
        """UTC timestamp converted to IST (+5:30)."""
        utc = pytz.UTC
        ts = datetime(2026, 1, 20, 5, 0, 0, tzinfo=utc)  # 5:00 UTC
        result = format_timestamp(ts)
        assert "10:30:00 IST" in result  # 5:00 UTC = 10:30 IST

    def test_format_timestamp_with_none(self):
        """None timestamp returns placeholder."""
        assert format_timestamp(None) == "--"

    def test_format_timestamp_naive_datetime(self):
        """Naive datetime assumed to be IST."""
        ts = datetime(2026, 1, 20, 10, 30, 45)  # No timezone
        result = format_timestamp(ts)
        assert "10:30:45 IST" in result


class TestFormatTimestampIso:
    """Tests for format_timestamp_iso function - Requirement 2.4"""

    def test_format_timestamp_iso_includes_offset(self):
        """ISO timestamp includes +05:30 offset."""
        ts = datetime(2026, 1, 20, 10, 30, 45, tzinfo=IST)
        result = format_timestamp_iso(ts)
        assert "+05:30" in result

    def test_format_timestamp_iso_format(self):
        """ISO timestamp has correct format."""
        ts = datetime(2026, 1, 20, 10, 30, 45, tzinfo=IST)
        result = format_timestamp_iso(ts)
        assert result == "2026-01-20T10:30:45+05:30"

    def test_format_timestamp_iso_with_none(self):
        """None timestamp returns placeholder."""
        assert format_timestamp_iso(None) == "--"


class TestCheckStaleness:
    """Tests for check_staleness function - Requirement 17.6"""

    def test_recent_data_not_stale(self):
        """Data less than 5 minutes old is not stale."""
        recent = datetime.now(IST) - timedelta(minutes=2)
        assert check_staleness(recent) is False

    def test_old_data_is_stale(self):
        """Data more than 5 minutes old is stale."""
        old = datetime.now(IST) - timedelta(minutes=10)
        assert check_staleness(old) is True

    def test_exactly_5_minutes_not_stale(self):
        """Data exactly 5 minutes old is not stale (boundary)."""
        # Use 299 seconds to avoid timing issues in test execution
        boundary = datetime.now(IST) - timedelta(seconds=299)
        assert check_staleness(boundary) is False

    def test_just_over_5_minutes_is_stale(self):
        """Data just over 5 minutes old is stale."""
        just_over = datetime.now(IST) - timedelta(seconds=301)
        assert check_staleness(just_over) is True

    def test_none_timestamp_is_stale(self):
        """None timestamp is considered stale."""
        assert check_staleness(None) is True

    def test_custom_threshold(self):
        """Custom staleness threshold works."""
        ts = datetime.now(IST) - timedelta(seconds=120)
        # Not stale with default 5 min threshold
        assert check_staleness(ts, threshold_seconds=300) is False
        # Stale with 1 min threshold
        assert check_staleness(ts, threshold_seconds=60) is True

    def test_naive_datetime_handled(self):
        """Naive datetime is handled correctly."""
        naive = datetime.now() - timedelta(minutes=2)
        # Should not raise, should return False (recent)
        result = check_staleness(naive)
        assert result is False


class TestGetStalenessAge:
    """Tests for get_staleness_age function."""

    def test_returns_timedelta(self):
        """Returns a timedelta for valid timestamp."""
        ts = datetime.now(IST) - timedelta(minutes=5)
        age = get_staleness_age(ts)
        assert isinstance(age, timedelta)
        assert 290 < age.total_seconds() < 310  # ~5 minutes

    def test_returns_none_for_none_input(self):
        """Returns None for None input."""
        assert get_staleness_age(None) is None


class TestFormatStalenessMessage:
    """Tests for format_staleness_message function."""

    def test_seconds_ago(self):
        """Recent data shows seconds."""
        ts = datetime.now(IST) - timedelta(seconds=30)
        msg = format_staleness_message(ts)
        assert "s ago" in msg

    def test_minutes_ago(self):
        """Data minutes old shows minutes."""
        ts = datetime.now(IST) - timedelta(minutes=5)
        msg = format_staleness_message(ts)
        assert "m ago" in msg

    def test_hours_ago(self):
        """Data hours old shows hours and minutes."""
        ts = datetime.now(IST) - timedelta(hours=2, minutes=30)
        msg = format_staleness_message(ts)
        assert "h" in msg and "m ago" in msg

    def test_none_timestamp(self):
        """None timestamp shows appropriate message."""
        msg = format_staleness_message(None)
        assert "No timestamp" in msg
