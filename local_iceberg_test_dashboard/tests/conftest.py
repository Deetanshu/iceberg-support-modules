# Iceberg Test Dashboard - Shared Test Fixtures
"""Shared pytest fixtures for the test dashboard."""

import pytest
from datetime import datetime
import pytz

IST = pytz.timezone("Asia/Kolkata")


@pytest.fixture
def ist_timezone():
    """Return IST timezone for tests."""
    return IST


@pytest.fixture
def sample_timestamp():
    """Return a sample IST timestamp for tests."""
    return datetime(2026, 1, 20, 10, 30, 0, tzinfo=IST)
