# Iceberg Test Dashboard - Formatting Utilities
"""
Formatting utilities for prices, percentages, timestamps, and staleness detection.

Requirements: 2.4, 2.5, 17.6
"""

from datetime import datetime, timedelta
from typing import Optional, Union
import pytz

IST = pytz.timezone("Asia/Kolkata")

# Staleness threshold in seconds (5 minutes)
STALENESS_THRESHOLD_SECONDS = 300


def format_price(value: Optional[Union[float, int]]) -> str:
    """Format a price value with exactly 2 decimal places.

    Requirement 2.5: Prices formatted with 2 decimal places.

    Args:
        value: The price value to format. Can be None, float, or int.

    Returns:
        Formatted price string with 2 decimal places, or "--" if value is None/invalid.

    Examples:
        >>> format_price(12345.6789)
        '12345.68'
        >>> format_price(100)
        '100.00'
        >>> format_price(None)
        '--'
    """
    if value is None:
        return "--"
    try:
        return f"{float(value):.2f}"
    except (ValueError, TypeError):
        return "--"


def format_percentage(value: Optional[Union[float, int]]) -> str:
    """Format a percentage value with exactly 2 decimal places and percent sign.

    Requirement 2.5: Percentages formatted with 2 decimal places.

    Args:
        value: The percentage value to format. Can be None, float, or int.

    Returns:
        Formatted percentage string with 2 decimal places and % sign,
        or "--" if value is None/invalid.

    Examples:
        >>> format_percentage(12.3456)
        '12.35%'
        >>> format_percentage(-5.1)
        '-5.10%'
        >>> format_percentage(None)
        '--'
    """
    if value is None:
        return "--"
    try:
        return f"{float(value):.2f}%"
    except (ValueError, TypeError):
        return "--"


def format_timestamp(
    ts: Optional[datetime],
    include_date: bool = False,
    include_timezone: bool = True,
) -> str:
    """Format a timestamp in IST timezone.

    Requirement 2.4: Timestamps displayed in IST (Asia/Kolkata) timezone.

    Args:
        ts: The datetime to format. Can be None or a datetime object.
        include_date: If True, include the date in the output.
        include_timezone: If True, include IST label in the output.

    Returns:
        Formatted timestamp string in IST, or "--" if ts is None.

    Examples:
        >>> from datetime import datetime
        >>> import pytz
        >>> ts = datetime(2026, 1, 20, 10, 30, 45, tzinfo=pytz.UTC)
        >>> format_timestamp(ts)  # Converts to IST
        '16:00:45 IST'
        >>> format_timestamp(ts, include_date=True)
        '2026-01-20 16:00:45 IST'
    """
    if ts is None:
        return "--"

    try:
        # Convert to IST if timezone-aware, or assume IST if naive
        if ts.tzinfo is None:
            ts_ist = IST.localize(ts)
        else:
            ts_ist = ts.astimezone(IST)

        if include_date:
            time_str = ts_ist.strftime("%Y-%m-%d %H:%M:%S")
        else:
            time_str = ts_ist.strftime("%H:%M:%S")

        if include_timezone:
            return f"{time_str} IST"
        return time_str

    except (ValueError, AttributeError, TypeError):
        return "--"


def format_timestamp_iso(ts: Optional[datetime]) -> str:
    """Format a timestamp in ISO format with IST timezone offset.

    Requirement 2.4: Timestamps include IST timezone offset (+05:30).

    Args:
        ts: The datetime to format. Can be None or a datetime object.

    Returns:
        ISO formatted timestamp string with +05:30 offset, or "--" if ts is None.

    Examples:
        >>> from datetime import datetime
        >>> import pytz
        >>> ts = datetime(2026, 1, 20, 10, 30, 45, tzinfo=pytz.UTC)
        >>> format_timestamp_iso(ts)
        '2026-01-20T16:00:45+05:30'
    """
    if ts is None:
        return "--"

    try:
        # Convert to IST if timezone-aware, or assume IST if naive
        if ts.tzinfo is None:
            ts_ist = IST.localize(ts)
        else:
            ts_ist = ts.astimezone(IST)

        return ts_ist.strftime("%Y-%m-%dT%H:%M:%S+05:30")

    except (ValueError, AttributeError, TypeError):
        return "--"


def check_staleness(
    data_ts: Optional[datetime],
    threshold_seconds: int = STALENESS_THRESHOLD_SECONDS,
) -> bool:
    """Check if data is stale (older than threshold).

    Requirement 17.6: Data staleness detection (>5 minutes = stale).

    Args:
        data_ts: The timestamp of the data to check.
        threshold_seconds: Staleness threshold in seconds (default: 300 = 5 minutes).

    Returns:
        True if data is stale (older than threshold), False otherwise.
        Returns True if data_ts is None (missing timestamp = stale).

    Examples:
        >>> from datetime import datetime, timedelta
        >>> import pytz
        >>> now = datetime.now(pytz.timezone("Asia/Kolkata"))
        >>> recent = now - timedelta(minutes=2)
        >>> check_staleness(recent)
        False
        >>> old = now - timedelta(minutes=10)
        >>> check_staleness(old)
        True
    """
    if data_ts is None:
        return True

    try:
        now = datetime.now(IST)

        # Handle naive datetime by assuming IST
        if data_ts.tzinfo is None:
            data_ts = IST.localize(data_ts)
        else:
            data_ts = data_ts.astimezone(IST)

        age = now - data_ts
        return age.total_seconds() > threshold_seconds

    except (ValueError, AttributeError, TypeError):
        return True


def get_staleness_age(data_ts: Optional[datetime]) -> Optional[timedelta]:
    """Get the age of data as a timedelta.

    Args:
        data_ts: The timestamp of the data.

    Returns:
        timedelta representing the age of the data, or None if data_ts is None.
    """
    if data_ts is None:
        return None

    try:
        now = datetime.now(IST)

        # Handle naive datetime by assuming IST
        if data_ts.tzinfo is None:
            data_ts = IST.localize(data_ts)
        else:
            data_ts = data_ts.astimezone(IST)

        return now - data_ts

    except (ValueError, AttributeError, TypeError):
        return None


def format_staleness_message(data_ts: Optional[datetime]) -> str:
    """Format a human-readable staleness message.

    Args:
        data_ts: The timestamp of the data.

    Returns:
        Human-readable message about data freshness.
    """
    age = get_staleness_age(data_ts)

    if age is None:
        return "No timestamp available"

    total_seconds = int(age.total_seconds())

    if total_seconds < 60:
        return f"Updated {total_seconds}s ago"
    elif total_seconds < 3600:
        minutes = total_seconds // 60
        return f"Updated {minutes}m ago"
    else:
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        return f"Updated {hours}h {minutes}m ago"
