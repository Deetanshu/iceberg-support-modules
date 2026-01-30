# Iceberg Test Dashboard - Source Package
"""
Iceberg Test Dashboard

A comprehensive Python test dashboard for the Iceberg Trading Platform API
using Dash by Plotly. Provides real-time market data visualization,
indicator monitoring, and API endpoint testing with an 80s terminal aesthetic.
"""

__version__ = "0.1.0"

from .config import Settings, get_settings
from .models import (
    SymbolTick,
    IndicatorData,
    OptionStrike,
    OptionChainData,
    Candle,
    SymbolData,
    VALID_SYMBOLS,
    VALID_MODES,
    VALID_SIGNALS,
)
from .state_manager import StateManager, ConnectionStatus
from .ws_client import FastStreamClient, calculate_backoff_delay, create_pong_message
from .sse_client import TieredStreamClient, calculate_sse_backoff_delay
from .api_client import IcebergAPIClient, APIError, APIResponse
from .parsers import (
    parse_timestamp,
    parse_columnar_candles,
    candles_to_columnar,
    filter_candles_to_today,
    parse_columnar_option_chain,
    parse_indicator_series,
    parse_response_meta,
    parse_bootstrap_response,
    parse_indicator_update,
    parse_option_chain_update,
    parse_snapshot_event,
    parse_sse_event,
    get_event_type,
    handle_sse_event,
)

__all__ = [
    # Config
    "Settings",
    "get_settings",
    # Models
    "SymbolTick",
    "IndicatorData",
    "OptionStrike",
    "OptionChainData",
    "Candle",
    "SymbolData",
    "VALID_SYMBOLS",
    "VALID_MODES",
    "VALID_SIGNALS",
    # State
    "StateManager",
    "ConnectionStatus",
    # Clients
    "FastStreamClient",
    "TieredStreamClient",
    "IcebergAPIClient",
    "APIError",
    "APIResponse",
    # Utilities
    "calculate_backoff_delay",
    "calculate_sse_backoff_delay",
    "create_pong_message",
    # Parsers
    "parse_timestamp",
    "parse_columnar_candles",
    "candles_to_columnar",
    "filter_candles_to_today",
    "parse_columnar_option_chain",
    "parse_indicator_series",
    "parse_response_meta",
    "parse_bootstrap_response",
    "parse_indicator_update",
    "parse_option_chain_update",
    "parse_snapshot_event",
    "parse_sse_event",
    "get_event_type",
    "handle_sse_event",
]
