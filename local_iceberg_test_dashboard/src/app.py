# Iceberg Test Dashboard - Main Application
"""
Main Dash application entry point for the Iceberg Test Dashboard.

Assembles all components and implements callbacks for:
- Symbol selection (Requirement 6.7, 10.5)
- Mode switching (Requirement 13.3)
- Interval-based updates (Requirement 4.4, 10.4)
- Health monitoring (Requirement 4.4)
- Multi-page navigation (Requirement 19.1)

Requirements: 1.4, 4.4, 6.7, 10.4, 10.5, 13.3, 19.1, 19.2, 19.3, 19.7
"""

import asyncio
import json
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from dash import Dash, html, dcc, callback, Input, Output, State, ctx, MATCH, ALL
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import pytz

from .config import get_settings, init_logging
from .state_manager import StateManager
from .models import VALID_SYMBOLS, VALID_MODES, IndicatorData, OptionChainData
from .charts import create_candlestick_chart, create_ema_chart, create_empty_chart, create_adr_treemap, create_skew_pcr_chart
from .layouts import (
    COLORS,
    create_professional_style,
    create_header_style,
    create_card_style,
    create_card_header_style,
    create_symbol_selector_bar,
    create_indicators_panel,
    create_option_chain_table,
    create_mode_tabs_header,
    create_historical_controls,
    create_connection_status_panel,
    create_market_status_banner,
    create_error_display,
    create_staleness_warning,
    create_data_gap_warning,
    create_nav_dropdown,
    create_sidebar_nav,
)
from .api_client import IcebergAPIClient
from .advanced_page import (
    create_advanced_page_layout,
    fetch_adr_constituents,
    fetch_adr_history,
    create_adr_line_chart,
)
from .debugging_page import (
    create_debugging_page_layout,
    REST_ENDPOINTS as DEBUG_REST_ENDPOINTS,
    get_endpoint_by_id as debug_get_endpoint_by_id,
    execute_rest_endpoint as debug_execute_rest_endpoint,
    create_endpoint_card as debug_create_endpoint_card,
)
from .admin_page import (
    create_admin_page_layout,
    create_access_denied_page,
    get_users,
    set_strike_ranges,
)
from .login_page import (
    create_login_page_layout,
    parse_authorization_code,
    create_login_status_display,
    create_user_info_display,
)
from .ws_client import FastStreamClient
from .sse_client import TieredStreamClient

# Initialize logging early (writes to logs/dashboard.log in append mode)
init_logging()

IST = pytz.timezone("Asia/Kolkata")

# Global state manager instance
state_manager = StateManager()

# Global API client instance
api_client: Optional[IcebergAPIClient] = None

# Global streaming client instances
# Requirement 11.1, 12.1: WebSocket and SSE clients for real-time updates
ws_client: Optional[FastStreamClient] = None
sse_client: Optional[TieredStreamClient] = None


def get_api_client() -> IcebergAPIClient:
    """Get or create the API client instance."""
    global api_client
    if api_client is None:
        api_client = IcebergAPIClient()
    return api_client


def get_ws_client(jwt_token: str) -> FastStreamClient:
    """Get or create the WebSocket client instance.
    
    Requirement 11.1: Connect to wss://api.botbro.trade/v1/stream/fast with JWT token
    Requirement 11.2: Subscribe to all 4 symbols in the connection
    
    Args:
        jwt_token: JWT token for authentication
    
    Returns:
        FastStreamClient instance
    """
    global ws_client
    
    def on_jwt_refresh_needed() -> Optional[str]:
        """Callback to refresh JWT token when WebSocket receives 4001 close code."""
        client = get_api_client()
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(client.refresh_token())
            if result.ok and result.data:
                new_token = result.data.get("token")
                if new_token:
                    state_manager.update_jwt_token(new_token)
                    return new_token
        except Exception:
            pass
        finally:
            loop.close()
        return None
    
    def on_slow_client_warning():
        """Callback when slow client warning is received."""
        state_manager.set_error(
            message="WebSocket slow client warning - connection may be unstable",
            error_type="streaming",
            can_retry=True,
        )
    
    if ws_client is None or not ws_client.running:
        ws_client = FastStreamClient(
            state_manager=state_manager,
            jwt_token=jwt_token,
            symbols=["nifty", "banknifty", "sensex", "finnifty"],
            on_jwt_refresh_needed=on_jwt_refresh_needed,
            on_slow_client_warning=on_slow_client_warning,
        )
    else:
        # Update token if client exists
        ws_client.update_jwt_token(jwt_token)
    
    return ws_client


def get_sse_client(jwt_token: str) -> TieredStreamClient:
    """Get or create the SSE client instance.
    
    Requirement 12.1: Connect to GET /v1/stream/indicators/tiered with JWT as query param
    Requirement 12.2: Request all symbols and both modes (current, positional)
    
    Args:
        jwt_token: JWT token for authentication
    
    Returns:
        TieredStreamClient instance
    """
    global sse_client
    
    def on_refresh_recommended():
        """Callback when refresh_recommended event is received.
        
        Requirement 12.8: Re-fetch bootstrap data on refresh_recommended event.
        """
        client = get_api_client()
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                client.bootstrap(
                    symbols=["nifty", "banknifty", "sensex", "finnifty"],
                    include_candles=True,
                    include_option_chain=True,
                )
            )
            if result.ok and result.data:
                _populate_state_from_bootstrap(result.data, result.meta)
        except Exception:
            pass
        finally:
            loop.close()
    
    if sse_client is None or not sse_client.running:
        sse_client = TieredStreamClient(
            state_manager=state_manager,
            jwt_token=jwt_token,
            symbols=["nifty", "banknifty", "sensex", "finnifty"],
            modes=["current", "positional"],
            on_refresh_recommended=on_refresh_recommended,
        )
    else:
        # Update token if client exists
        sse_client.update_jwt_token(jwt_token)
    
    return sse_client


def connect_streaming_clients(jwt_token: str) -> None:
    """Connect both WebSocket and SSE streaming clients.
    
    Requirements:
        11.1, 11.2: Connect WebSocket for fast LTP updates
        12.1, 12.2: Connect SSE for indicator updates
    
    Args:
        jwt_token: JWT token for authentication
    """
    import structlog
    logger = structlog.get_logger(__name__)
    
    # Connect WebSocket client for fast LTP updates
    try:
        ws = get_ws_client(jwt_token)
        if not ws.running:
            ws.connect()
            logger.info("ws_client_started")
    except Exception as e:
        logger.error("ws_client_start_failed", error=str(e))
    
    # Connect SSE client for indicator updates
    try:
        sse = get_sse_client(jwt_token)
        if not sse.running:
            sse.connect()
            logger.info("sse_client_started")
    except Exception as e:
        logger.error("sse_client_start_failed", error=str(e))


def disconnect_streaming_clients() -> None:
    """Disconnect both WebSocket and SSE streaming clients."""
    global ws_client, sse_client
    
    if ws_client:
        ws_client.disconnect()
        ws_client = None
    
    if sse_client:
        sse_client.disconnect()
        sse_client = None


# =============================================================================
# Main Page Layout Components
# Requirements 19.2, 19.7: Vertical arrangement with clear separators
# =============================================================================

def create_section_separator() -> html.Hr:
    """Create a visual separator between sections.
    
    Requirement 19.7: Add clear separators between sections.
    """
    return html.Hr(
        style={
            "border": "none",
            "borderTop": f"1px solid {COLORS['content_bg']}",
            "margin": "20px 0",
        }
    )


def create_chart_section(symbol: str = "nifty") -> html.Div:
    """Create the candlestick chart section.
    
    Requirement 19.2: Main page displays symbol chart.
    """
    return html.Div(
        [
            html.Div(
                "Trading View",
                style=create_card_header_style()
            ),
            dcc.Graph(
                id="candlestick-chart",
                figure=create_empty_chart("Loading chart data..."),
                config={
                    "displayModeBar": True,
                    "modeBarButtonsToRemove": ["lasso2d", "select2d"],
                    "displaylogo": False,
                },
                style={"height": "400px"},
            ),
        ],
        style=create_card_style(),
    )


def create_ema_section(symbol: str = "nifty") -> html.Div:
    """Create the EMA indicator chart section.
    
    Requirement 19.2: Main page displays EMA chart.
    """
    return html.Div(
        [
            html.Div(
                "EMA Indicator",
                style=create_card_header_style()
            ),
            dcc.Graph(
                id="ema-chart",
                figure=create_empty_chart("Loading EMA data..."),
                config={
                    "displayModeBar": False,
                    "displaylogo": False,
                },
                style={"height": "250px"},
            ),
        ],
        style=create_card_style(),
    )


def create_skew_pcr_section(symbol: str = "nifty", mode: str = "current") -> html.Div:
    """Create the Skew/PCR timeseries chart section.
    
    Requirements:
        8.1: Display current Skew value with color coding
        8.2: Display current PCR value
        19.2: Main page displays indicators
    """
    return html.Div(
        [
            html.Div(
                "Skew & PCR Timeseries",
                style=create_card_header_style()
            ),
            dcc.Graph(
                id="skew-pcr-chart",
                figure=create_empty_chart("Loading Skew/PCR data..."),
                config={
                    "displayModeBar": False,
                    "displaylogo": False,
                },
                style={"height": "300px"},
            ),
        ],
        style=create_card_style(),
    )


def create_indicators_section() -> html.Div:
    """Create the indicators panel section.
    
    Requirement 19.2: Main page displays indicators.
    """
    return html.Div(
        id="indicators-section",
        children=[
            create_indicators_panel(IndicatorData(), None)
        ],
    )


def create_option_chain_section() -> html.Div:
    """Create the option chain table section.
    
    Requirement 19.2: Main page displays option chain.
    """
    return html.Div(
        id="option-chain-section",
        children=[
            create_option_chain_table(None, None)
        ],
    )


def create_main_header(
    current_symbol: str = "nifty",
    current_mode: str = "current",
    current_page: str = "main",
) -> html.Div:
    """Create the main header with logo, navigation dropdown, mode tabs, and account button.
    
    Requirement 19.1: Navigation with Main, Advanced, Admin, Debugging sections.
    """
    return html.Div(
        [
            # Logo and title
            html.Div(
                [
                    html.Span(
                        "❄",
                        style={
                            "fontSize": "24px",
                            "marginRight": "10px",
                        }
                    ),
                    html.Span(
                        "Iceberg",
                        style={
                            "fontSize": "20px",
                            "fontWeight": "bold",
                        }
                    ),
                    html.Span(
                        f" | {current_symbol.upper()}",
                        id="header-symbol-display",
                        style={
                            "fontSize": "14px",
                            "marginLeft": "15px",
                            "opacity": "0.8",
                        }
                    ),
                ],
                style={"display": "flex", "alignItems": "center"}
            ),
            
            # Navigation dropdown (Requirement 19.1)
            create_nav_dropdown(current_page),
            
            # Mode tabs and historical controls
            html.Div(
                [
                    create_mode_tabs_header(current_mode),
                    create_historical_controls(),
                ],
                style={"display": "flex", "alignItems": "center"}
            ),
            
            # Connection status and account
            html.Div(
                [
                    html.Div(
                        id="header-connection-status",
                        children=[
                            html.Span(
                                "●",
                                id="ws-status-dot",
                                style={
                                    "color": COLORS["disconnected"],
                                    "marginRight": "4px",
                                    "fontSize": "10px",
                                }
                            ),
                            html.Span(
                                "WS",
                                style={
                                    "fontSize": "11px",
                                    "marginRight": "10px",
                                }
                            ),
                            html.Span(
                                "●",
                                id="sse-status-dot",
                                style={
                                    "color": COLORS["disconnected"],
                                    "marginRight": "4px",
                                    "fontSize": "10px",
                                }
                            ),
                            html.Span(
                                "SSE",
                                style={
                                    "fontSize": "11px",
                                    "marginRight": "15px",
                                }
                            ),
                        ],
                        style={"display": "flex", "alignItems": "center"}
                    ),
                    html.Button(
                        "Account 👤",
                        id="account-button",
                        style={
                            "backgroundColor": COLORS["accent"],
                            "color": COLORS["text_light"],
                            "border": "none",
                            "borderRadius": "4px",
                            "padding": "8px 16px",
                            "cursor": "pointer",
                            "fontSize": "13px",
                            "fontWeight": "500",
                        }
                    ),
                ],
                style={"display": "flex", "alignItems": "center"}
            ),
        ],
        id="main-header",
        style=create_header_style(),
    )


def create_market_status_section() -> html.Div:
    """Create the market status banner section.
    
    Requirements 16.1, 16.2, 16.3, 16.4, 16.5: Market hours awareness.
    """
    return html.Div(
        id="market-status-section",
        children=[
            create_market_status_banner(state_manager.get_market_state())
        ],
    )


def create_error_section() -> html.Div:
    """Create the error display section.
    
    Requirements:
        17.1: WHEN an API call fails, THE Dashboard SHALL display the error message without crashing
        5.6: IF bootstrap fails, THEN THE Dashboard SHALL display error and allow retry
    """
    # Get current error state
    error_state = state_manager.get_error_state()
    
    return html.Div(
        id="error-section",
        children=[
            create_error_display(error_state, show_retry=True)
        ],
    )


def create_staleness_warning_section() -> html.Div:
    """Create the staleness warning section.
    
    Requirements:
        5.7: THE Dashboard SHALL display cache_stale warning from meta.cache_stale if true
        17.6: IF data is stale (>5 minutes old), THEN THE Dashboard SHALL display a staleness warning
    """
    # Get current staleness state
    staleness_state = state_manager.get_staleness_state()
    show_warning = state_manager.should_show_staleness_warning()
    data_age = state_manager.get_data_age_seconds()
    
    return html.Div(
        id="staleness-warning-section",
        children=[
            create_staleness_warning(
                show_warning=show_warning,
                cache_stale=staleness_state.cache_stale,
                data_age_seconds=data_age,
                last_update=staleness_state.last_data_update,
            )
        ],
    )


def create_data_gap_warning_section() -> html.Div:
    """Create the data gap warning section.
    
    FIX-032: Data Gap Detection & Auto-Bootstrap
    """
    # Get current data gap state
    data_gap_state = state_manager.get_data_gap_state()
    is_market_open = state_manager.is_market_open()
    
    return html.Div(
        id="data-gap-warning-section",
        children=[
            create_data_gap_warning(
                has_gap=data_gap_state.has_gap,
                gap_type=data_gap_state.gap_type,
                gap_message=data_gap_state.gap_message,
                is_market_open=is_market_open,
            )
        ],
    )


def create_main_page_content() -> html.Div:
    """Create the main dashboard page content (without header).
    
    Requirements:
        19.2: Main page displays symbol chart, EMA chart, indicators, option chain, symbol selector
        19.7: Charts displayed vertically, clearly separated
        16.1, 16.2, 16.3: Market hours awareness with status banner
        17.1, 5.6: Error display with retry functionality
        5.7, 17.6: Staleness warnings for stale data
        FIX-032: Data gap detection and auto-bootstrap
    
    Layout (top to bottom):
        1. Error display (if any)
        2. Data gap warning (if gap detected during market hours)
        3. Staleness warning (if data is stale)
        4. Market status banner
        5. Candlestick chart
        6. EMA chart
        7. Indicators panel + Option chain (side by side)
    """
    return html.Div(
        [
            # Error display section (Requirements 17.1, 5.6)
            create_error_section(),
            
            # Data gap warning section (FIX-032)
            create_data_gap_warning_section(),
            
            # Staleness warning section (Requirements 5.7, 17.6)
            create_staleness_warning_section(),
            
            # Market status banner (Requirements 16.1, 16.2, 16.3)
            create_market_status_section(),
            
            # Candlestick chart section
            create_chart_section(),
            
            # Separator
            create_section_separator(),
            
            # EMA chart section
            create_ema_section(),
            
            # Separator
            create_section_separator(),
            
            # Skew/PCR chart section (Requirements 8.1, 8.2)
            create_skew_pcr_section(),
            
            # Separator
            create_section_separator(),
            
            # Indicators and Option Chain row
            html.Div(
                [
                    # Indicators panel (left)
                    html.Div(
                        create_indicators_section(),
                        style={"flex": "1", "minWidth": "300px"},
                    ),
                    
                    # Option chain table (right)
                    html.Div(
                        create_option_chain_section(),
                        style={"flex": "2", "minWidth": "400px"},
                    ),
                ],
                style={
                    "display": "flex",
                    "gap": "20px",
                    "flexWrap": "wrap",
                }
            ),
        ],
        id="main-page-content",
        style={
            "padding": "20px",
            "paddingBottom": "100px",  # Space for fixed symbol selector
            "maxWidth": "1400px",
            "margin": "0 auto",
        }
    )


def create_main_page_layout() -> html.Div:
    """Create the complete main dashboard page layout.
    
    Requirements:
        19.2: Main page displays symbol chart, EMA chart, indicators, option chain, symbol selector
        19.7: Charts displayed vertically, clearly separated
    
    Layout (top to bottom):
        1. Header with logo, mode tabs, connection status
        2. Candlestick chart
        3. EMA chart
        4. Indicators panel + Option chain (side by side)
        5. Symbol selector bar (fixed at bottom)
    """
    return html.Div(
        [
            # Header
            create_main_header(),
            
            # Main content area
            html.Div(
                [
                    # Candlestick chart section
                    create_chart_section(),
                    
                    # Separator
                    create_section_separator(),
                    
                    # EMA chart section
                    create_ema_section(),
                    
                    # Separator
                    create_section_separator(),
                    
                    # Skew/PCR chart section (Requirements 8.1, 8.2)
                    create_skew_pcr_section(),
                    
                    # Separator
                    create_section_separator(),
                    
                    # Indicators and Option Chain row
                    html.Div(
                        [
                            # Indicators panel (left)
                            html.Div(
                                create_indicators_section(),
                                style={"flex": "1", "minWidth": "300px"},
                            ),
                            
                            # Option chain table (right)
                            html.Div(
                                create_option_chain_section(),
                                style={"flex": "2", "minWidth": "400px"},
                            ),
                        ],
                        style={
                            "display": "flex",
                            "gap": "20px",
                            "flexWrap": "wrap",
                        }
                    ),
                ],
                id="main-content",
                style={
                    "padding": "20px",
                    "paddingBottom": "100px",  # Space for fixed symbol selector
                    "maxWidth": "1400px",
                    "margin": "0 auto",
                }
            ),
            
            # Symbol selector bar (fixed at bottom)
            html.Div(
                id="symbol-selector-container",
                children=[
                    create_symbol_selector_bar(state_manager, "nifty")
                ],
                style={
                    "position": "fixed",
                    "bottom": "0",
                    "left": "0",
                    "right": "0",
                    "backgroundColor": COLORS["content_bg"],
                    "borderTop": f"1px solid {COLORS['card_bg']}",
                    "boxShadow": "0 -2px 10px rgba(0,0,0,0.1)",
                    "zIndex": "1000",
                }
            ),
            
            # Interval components for polling (Requirement 4.4, 10.4)
            dcc.Interval(
                id="fast-interval",
                interval=500,  # 500ms for LTP updates
                n_intervals=0,
            ),
            dcc.Interval(
                id="slow-interval",
                interval=5000,  # 5000ms for indicator updates
                n_intervals=0,
            ),
            dcc.Interval(
                id="health-interval",
                interval=30000,  # 30000ms for health checks
                n_intervals=0,
            ),
            
            # Store components for state persistence
            dcc.Store(id="selected-symbol-store", data="nifty"),
            dcc.Store(id="selected-mode-store", data="current"),
            dcc.Store(id="health-status-store", data={"healthy": False}),
            
            # Hidden div for callback outputs that don't need display
            html.Div(id="hidden-div", style={"display": "none"}),
        ],
        style=create_professional_style(),
    )


def create_multi_page_layout() -> html.Div:
    """Create the multi-page application layout with URL routing.
    
    Requirement 19.1: Sidebar navigation with Main, Advanced, Admin sections.
    """
    return html.Div(
        [
            # URL location component for routing
            dcc.Location(id="url", refresh=False),
            
            # Header (shared across pages)
            html.Div(id="page-header"),
            
            # Page content container
            html.Div(id="page-content"),
            
            # Symbol selector bar (fixed at bottom, shared)
            html.Div(
                id="symbol-selector-container",
                style={
                    "position": "fixed",
                    "bottom": "0",
                    "left": "0",
                    "right": "0",
                    "backgroundColor": COLORS["content_bg"],
                    "borderTop": f"1px solid {COLORS['card_bg']}",
                    "boxShadow": "0 -2px 10px rgba(0,0,0,0.1)",
                    "zIndex": "1000",
                }
            ),
            
            # Interval components for polling (Requirement 4.4, 10.4)
            dcc.Interval(
                id="fast-interval",
                interval=500,  # 500ms for LTP updates
                n_intervals=0,
            ),
            dcc.Interval(
                id="slow-interval",
                interval=5000,  # 5000ms for indicator updates
                n_intervals=0,
            ),
            dcc.Interval(
                id="health-interval",
                interval=30000,  # 30000ms for health checks
                n_intervals=0,
            ),
            # JWT refresh check interval (Requirement 3.9)
            dcc.Interval(
                id="jwt-refresh-interval",
                interval=60000,  # 60000ms (1 minute) for JWT expiry checks
                n_intervals=0,
            ),
            
            # Store components for state persistence (Requirement 19.5)
            dcc.Store(id="selected-symbol-store", data="nifty"),
            dcc.Store(id="selected-mode-store", data="current"),
            dcc.Store(id="health-status-store", data={"healthy": False}),
            dcc.Store(id="current-page-store", data="main"),
            dcc.Store(id="auth-store", data={"authenticated": False, "jwt_token": None}),
            dcc.Store(id="jwt-refresh-store", data={"last_refresh": None, "refresh_needed": False}),
            
            # Hidden div for callback outputs that don't need display
            html.Div(id="hidden-div", style={"display": "none"}),
        ],
        style=create_professional_style(),
    )


# =============================================================================
# Create Dash Application
# =============================================================================

def create_app() -> Dash:
    """Create and configure the Dash application.
    
    Requirement 1.4: Dashboard runs on port 8509.
    Requirement 19.1: Multi-page navigation support.
    """
    app = Dash(
        __name__,
        external_stylesheets=[dbc.themes.BOOTSTRAP],
        suppress_callback_exceptions=True,
        title="Iceberg Test Dashboard",
    )
    
    # Use multi-page layout for navigation support
    app.layout = create_multi_page_layout()
    
    return app


# Create the app instance
app = create_app()


# =============================================================================
# Callbacks - Page Routing
# Requirement 19.1: Navigation between Main, Advanced, Admin pages
# =============================================================================

@app.callback(
    [
        Output("page-header", "children"),
        Output("page-content", "children"),
        Output("current-page-store", "data"),
    ],
    [Input("url", "pathname")],
    [
        State("selected-symbol-store", "data"),
        State("selected-mode-store", "data"),
        State("auth-store", "data"),
    ],
)
def display_page(
    pathname: str,
    selected_symbol: str,
    selected_mode: str,
    auth_data: Dict[str, Any],
) -> Tuple[html.Div, html.Div, str]:
    """Route to the appropriate page based on URL pathname.
    
    Requirement 19.1: Sidebar navigation with Main, Advanced, Admin sections.
    Requirement 15.2: Admin page only accessible to users with admin role.
    Requirement 3.1: Provide login interface for Google OAuth authentication.
    
    Args:
        pathname: Current URL pathname
        selected_symbol: Currently selected symbol
        selected_mode: Currently selected mode
        auth_data: Authentication store data
    
    Returns:
        Tuple of (header, page content, current page name)
    """
    import structlog
    logger = structlog.get_logger(__name__)
    
    symbol = selected_symbol or "nifty"
    mode = selected_mode or "current"
    
    # Debug logging for auth state
    logger.info(
        "display_page_called",
        pathname=pathname,
        auth_data_keys=list(auth_data.keys()) if auth_data else None,
        auth_data_role=auth_data.get("role") if auth_data else None,
        auth_data_authenticated=auth_data.get("authenticated") if auth_data else None,
    )
    
    # Check if user is authenticated
    is_authenticated = auth_data.get("authenticated", False) if auth_data else False
    
    # Also check state manager for authentication status
    user_session = state_manager.get_user_session()
    if user_session.is_authenticated:
        is_authenticated = True
    
    logger.info(
        "auth_check",
        is_authenticated=is_authenticated,
        state_manager_authenticated=user_session.is_authenticated,
        state_manager_role=user_session.role,
    )
    
    # If not authenticated, always show login page (except for /login route itself)
    if not is_authenticated:
        return (
            html.Div(),  # No header on login page
            create_login_page_layout(),
            "login",
        )
    
    # Login page route - if already authenticated, redirect to main
    if pathname == "/login":
        return (
            create_main_header(symbol, mode, "main"),
            create_main_page_content(),
            "main",
        )
    
    if pathname == "/advanced":
        return (
            create_main_header(symbol, mode, "advanced"),
            create_advanced_page_layout(state_manager, symbol),
            "advanced",
        )
    elif pathname == "/debugging":
        return (
            create_main_header(symbol, mode, "debugging"),
            create_debugging_page_layout(state_manager),
            "debugging",
        )
    elif pathname == "/admin":
        # Requirement 15.2: Check user role before rendering admin page
        # FIX: Check role from auth-store first (more reliable), then fall back to state_manager
        user_role = auth_data.get("role") if auth_data else None
        if user_role is None:
            # Fallback to state manager
            user_role = state_manager.get_user_session().role
        
        logger.info(
            "admin_page_access_check",
            auth_data_role=auth_data.get("role") if auth_data else None,
            state_manager_role=state_manager.get_user_session().role,
            final_user_role=user_role,
            access_granted=(user_role == "admin"),
        )
        
        if user_role == "admin":
            # User has admin role - show admin page
            return (
                create_main_header(symbol, mode, "admin"),
                create_admin_page_layout(state_manager),
                "admin",
            )
        else:
            # User is not admin - show access denied page
            return (
                create_main_header(symbol, mode, "admin"),
                create_access_denied_page(),
                "admin",
            )
    else:
        # Default to main page
        return (
            create_main_header(symbol, mode, "main"),
            create_main_page_content(),
            "main",
        )


# =============================================================================
# Callbacks - Interval Updates
# Requirements 4.4, 10.4: Interval-based polling for updates
# =============================================================================

@app.callback(
    Output("symbol-selector-container", "children"),
    [Input("fast-interval", "n_intervals")],
    [State("selected-symbol-store", "data")],
    prevent_initial_call=True,
)
def update_ltp_display(n_intervals: int, selected_symbol: str) -> html.Div:
    """Update LTP display on fast interval (500ms).
    
    Requirement 10.4: Symbol selector updates LTPs in real-time.
    
    Args:
        n_intervals: Number of intervals elapsed
        selected_symbol: Currently selected symbol
    
    Returns:
        Symbol selector bar component
    """
    # Update symbol selector with current LTPs
    symbol_selector = create_symbol_selector_bar(state_manager, selected_symbol or "nifty")
    return symbol_selector


@app.callback(
    Output("url", "pathname", allow_duplicate=True),
    [Input("account-button", "n_clicks")],
    prevent_initial_call=True,
)
def handle_account_click(n_clicks: int) -> str:
    """Navigate to login page when account button is clicked.
    
    Args:
        n_clicks: Number of clicks on account button
    
    Returns:
        Pathname to navigate to
    """
    if n_clicks:
        return "/login"
    raise PreventUpdate


@app.callback(
    [
        Output("indicators-section", "children"),
        Output("candlestick-chart", "figure"),
        Output("ema-chart", "figure"),
        Output("skew-pcr-chart", "figure"),
    ],
    [
        Input("slow-interval", "n_intervals"),
        Input("selected-symbol-store", "data"),
        Input("selected-mode-store", "data"),
    ],
    [State("current-page-store", "data")],
    prevent_initial_call=True,
)
def update_indicators_and_charts(
    n_intervals: int,
    selected_symbol: str,
    selected_mode: str,
    current_page: str,
) -> Tuple[html.Div, go.Figure, go.Figure, go.Figure]:
    """Update indicators and charts on slow interval (5000ms) or when symbol/mode changes.
    
    Requirement 4.4: Auto-refresh health status every 30 seconds.
    Requirement 13.3: When user switches mode, update all displays with selected mode data.
    (Note: This callback handles indicator updates at 5s intervals)
    
    Args:
        n_intervals: Number of intervals elapsed
        selected_symbol: Currently selected symbol
        selected_mode: Currently selected mode
        current_page: Current page name
    
    Returns:
        Tuple of (indicators panel, candlestick chart, ema chart, skew/pcr chart)
    """
    # Only update if on main page (elements don't exist on login/admin pages)
    if current_page not in ["main", None]:
        raise PreventUpdate
    
    symbol = selected_symbol or "nifty"
    mode = selected_mode or "current"
    
    # Get indicator data
    indicators = state_manager.get_indicators(symbol, mode)
    conn_status = state_manager.get_connection_status()
    last_update = conn_status.last_sse_update
    
    # Create indicators panel
    indicators_panel = create_indicators_panel(indicators, last_update)
    
    # Get candle data and create candlestick chart
    candles = state_manager.get_candles(symbol)
    
    # Get RSI history for the RSI subplot (FIX: use history instead of single point)
    rsi_history = state_manager.get_rsi_history(symbol)
    rsi_values = rsi_history if rsi_history else None
    
    candlestick_fig = create_candlestick_chart(candles, symbol, rsi_values)
    
    # Get EMA history and create EMA chart
    ema_history = state_manager.get_ema_history(symbol)
    ema_fig = create_ema_chart(ema_history, symbol)
    
    # Get Skew/PCR history and create Skew/PCR chart (Requirements 8.1, 8.2)
    skew_pcr_history = state_manager.get_skew_pcr_history(symbol, mode)
    skew_pcr_fig = create_skew_pcr_chart(skew_pcr_history, symbol, mode)
    
    return indicators_panel, candlestick_fig, ema_fig, skew_pcr_fig


@app.callback(
    Output("health-status-store", "data"),
    [Input("health-interval", "n_intervals")],
    prevent_initial_call=True,
)
def check_health_status(n_intervals: int) -> Dict[str, Any]:
    """Check API health status on health interval (30000ms).
    
    Requirement 4.4: Auto-refresh health status every 30 seconds.
    
    Args:
        n_intervals: Number of intervals elapsed
    
    Returns:
        Health status dict
    """
    # Note: In a full implementation, this would make an async call to the API
    # For now, we return a placeholder
    return {"healthy": True, "checked_at": datetime.now(IST).isoformat()}


# =============================================================================
# Callbacks - Market Status Banner
# Requirements 16.1, 16.2, 16.3, 16.4, 16.5: Market hours awareness
# =============================================================================

@app.callback(
    Output("market-status-section", "children"),
    [Input("slow-interval", "n_intervals")],
    [State("current-page-store", "data")],
    prevent_initial_call=True,
)
def update_market_status_banner(n_intervals: int, current_page: str) -> html.Div:
    """Update market status banner based on current market state.
    
    Requirements:
        16.1: Display market state (OPEN, CLOSED, UNKNOWN) from bootstrap meta
        16.2: WHEN market is CLOSED, display a prominent banner
        16.3: Show market hours as 09:15-15:30 IST
        16.4: WHEN market_closed SSE event is received, update market state to CLOSED
        16.5: Continue displaying last known data when market is closed
    
    The market state is updated by:
    - Bootstrap response meta (Requirement 16.1)
    - SSE market_closed event (Requirement 16.4) - handled in sse_client.py
    
    Args:
        n_intervals: Number of intervals elapsed
        current_page: Current page name
    
    Returns:
        Updated market status banner component
    """
    # Only update if on main page
    if current_page not in ["main", None]:
        raise PreventUpdate
    
    # Get current market state from state manager
    # This is updated by SSE client when market_closed event is received (Req 16.4)
    market_state = state_manager.get_market_state()
    
    # Create and return the updated banner
    return create_market_status_banner(market_state)


# =============================================================================
# Callbacks - Staleness Warning
# Requirements 5.7, 17.6: Staleness warnings for stale data
# =============================================================================

@app.callback(
    Output("staleness-warning-section", "children"),
    [Input("slow-interval", "n_intervals")],
    [State("current-page-store", "data")],
    prevent_initial_call=True,
)
def update_staleness_warning(n_intervals: int, current_page: str) -> html.Div:
    """Update staleness warning based on current data freshness.
    
    Requirements:
        5.7: THE Dashboard SHALL display cache_stale warning from meta.cache_stale if true
        17.6: IF data is stale (>5 minutes old), THEN THE Dashboard SHALL display a staleness warning
    
    The staleness state is updated by:
    - Bootstrap response meta.cache_stale (Requirement 5.7)
    - Data update timestamps from SSE/WebSocket (Requirement 17.6)
    
    Args:
        n_intervals: Number of intervals elapsed
        current_page: Current page name
    
    Returns:
        Updated staleness warning component
    """
    # Only update if on main page
    if current_page not in ["main", None]:
        raise PreventUpdate
    
    # Get current staleness state from state manager
    staleness_state = state_manager.get_staleness_state()
    show_warning = state_manager.should_show_staleness_warning()
    data_age = state_manager.get_data_age_seconds()
    
    # Create and return the updated staleness warning
    return create_staleness_warning(
        show_warning=show_warning,
        cache_stale=staleness_state.cache_stale,
        data_age_seconds=data_age,
        last_update=staleness_state.last_data_update,
    )


# =============================================================================
# Callbacks - Data Gap Warning
# FIX-032: Data Gap Detection & Auto-Bootstrap
# =============================================================================

@app.callback(
    Output("data-gap-warning-section", "children"),
    [Input("slow-interval", "n_intervals")],
    [State("current-page-store", "data")],
    prevent_initial_call=True,
)
def update_data_gap_warning(n_intervals: int, current_page: str) -> html.Div:
    """Update data gap warning based on current data state.
    
    FIX-032: Data Gap Detection
    
    Checks for data gaps during market hours and displays warning if detected.
    Also triggers auto-bootstrap if conditions are met.
    
    Args:
        n_intervals: Number of intervals elapsed
        current_page: Current page name
    
    Returns:
        Updated data gap warning component
    """
    # Only update if on main page
    if current_page not in ["main", None]:
        raise PreventUpdate
    
    # Check if auto-bootstrap should be triggered
    if state_manager.should_auto_bootstrap():
        # Record the attempt to prevent spam
        state_manager.record_bootstrap_attempt()
        
        # Trigger bootstrap asynchronously
        client = get_api_client()
        user_session = state_manager.get_user_session()
        if user_session.jwt_token:
            client.jwt_token = user_session.jwt_token
            
            # Run async bootstrap
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(
                    client.bootstrap(
                        symbols=["nifty", "banknifty", "sensex", "finnifty"],
                        include_candles=True,
                        include_option_chain=True,
                    )
                )
                if result.ok and result.data:
                    _populate_state_from_bootstrap(result.data, result.meta)
                    state_manager.clear_data_gap()
            except Exception:
                pass
            finally:
                loop.close()
    
    # Get current data gap state
    data_gap_state = state_manager.get_data_gap_state()
    is_market_open = state_manager.is_market_open()
    
    # Create and return the updated data gap warning
    return create_data_gap_warning(
        has_gap=data_gap_state.has_gap,
        gap_type=data_gap_state.gap_type,
        gap_message=data_gap_state.gap_message,
        is_market_open=is_market_open,
    )


@app.callback(
    Output("data-gap-warning-section", "children", allow_duplicate=True),
    [Input("data-gap-bootstrap-btn", "n_clicks")],
    [State("auth-store", "data")],
    prevent_initial_call=True,
)
def handle_data_gap_bootstrap(n_clicks: int, auth_data: Dict[str, Any]) -> html.Div:
    """Handle manual bootstrap button click from data gap warning.
    
    FIX-032: Manual bootstrap trigger from data gap warning.
    
    Args:
        n_clicks: Button click count
        auth_data: Authentication store data
    
    Returns:
        Updated data gap warning component (with loading state)
    """
    if not n_clicks:
        raise PreventUpdate
    
    # Record the attempt
    state_manager.record_bootstrap_attempt()
    
    # Get JWT token
    jwt_token = None
    if auth_data and auth_data.get("jwt_token"):
        jwt_token = auth_data.get("jwt_token")
    else:
        user_session = state_manager.get_user_session()
        jwt_token = user_session.jwt_token
    
    if not jwt_token:
        raise PreventUpdate
    
    # Trigger bootstrap
    client = get_api_client()
    client.jwt_token = jwt_token
    
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(
            client.bootstrap(
                symbols=["nifty", "banknifty", "sensex", "finnifty"],
                include_candles=True,
                include_option_chain=True,
            )
        )
        if result.ok and result.data:
            _populate_state_from_bootstrap(result.data, result.meta)
            state_manager.clear_data_gap()
    except Exception:
        pass
    finally:
        loop.close()
    
    # Return updated warning (should now be hidden if bootstrap succeeded)
    data_gap_state = state_manager.get_data_gap_state()
    is_market_open = state_manager.is_market_open()
    
    return create_data_gap_warning(
        has_gap=data_gap_state.has_gap,
        gap_type=data_gap_state.gap_type,
        gap_message=data_gap_state.gap_message,
        is_market_open=is_market_open,
    )


# =============================================================================
# Callbacks - Error Display
# Requirements 17.1, 5.6: Error display with retry functionality
# =============================================================================

@app.callback(
    Output("error-section", "children"),
    [Input("slow-interval", "n_intervals")],
    [State("current-page-store", "data")],
    prevent_initial_call=True,
)
def update_error_display(n_intervals: int, current_page: str) -> html.Div:
    """Update error display based on current error state.
    
    Requirements:
        17.1: WHEN an API call fails, THE Dashboard SHALL display the error message without crashing
        5.6: IF bootstrap fails, THEN THE Dashboard SHALL display error and allow retry
    
    Args:
        n_intervals: Number of intervals elapsed
        current_page: Current page name
    
    Returns:
        Updated error display component
    """
    # Only update if on main page
    if current_page not in ["main", None]:
        raise PreventUpdate
    
    # Get current error state from state manager
    error_state = state_manager.get_error_state()
    
    # Create and return the error display
    return create_error_display(error_state, show_retry=True)


@app.callback(
    Output("error-section", "children", allow_duplicate=True),
    [Input("error-dismiss-btn", "n_clicks")],
    prevent_initial_call=True,
)
def handle_error_dismiss(n_clicks: int) -> html.Div:
    """Handle error dismiss button click.
    
    Requirement 17.1: Allow user to dismiss error messages.
    
    Args:
        n_clicks: Button click count
    
    Returns:
        Empty error display component
    """
    if not n_clicks:
        raise PreventUpdate
    
    # Clear the error state
    state_manager.clear_error()
    
    # Return empty error display
    from .state_manager import ErrorState
    return create_error_display(ErrorState(), show_retry=False)


@app.callback(
    Output("error-section", "children", allow_duplicate=True),
    [Input("error-retry-btn", "n_clicks")],
    [
        State("selected-symbol-store", "data"),
        State("selected-mode-store", "data"),
    ],
    prevent_initial_call=True,
)
def handle_error_retry(
    n_clicks: int,
    selected_symbol: str,
    selected_mode: str,
) -> html.Div:
    """Handle error retry button click.
    
    Requirements:
        5.6: IF bootstrap fails, THEN THE Dashboard SHALL display error and allow retry
        17.2: Implement retry logic for failed API calls (3 attempts with backoff)
    
    Args:
        n_clicks: Button click count
        selected_symbol: Currently selected symbol
        selected_mode: Currently selected mode
    
    Returns:
        Updated error display component (cleared if retry succeeds)
    """
    if not n_clicks:
        raise PreventUpdate
    
    # Get current error state
    error_state = state_manager.get_error_state()
    
    # Check if retry is allowed
    if not state_manager.can_retry_operation():
        # Max retries reached - update error message
        state_manager.set_error(
            message="Maximum retry attempts reached. Please refresh the page to try again.",
            error_type=error_state.error_type or "general",
            can_retry=False,
        )
        return create_error_display(state_manager.get_error_state(), show_retry=False)
    
    # Attempt retry based on error type
    error_type = error_state.error_type or "general"
    
    try:
        if error_type == "bootstrap":
            # Retry bootstrap data fetch
            client = get_api_client()
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(
                    client.bootstrap(symbols=["nifty", "banknifty", "sensex", "finnifty"])
                )
                
                if result.ok:
                    # Bootstrap succeeded - clear error
                    state_manager.clear_error()
                    return create_error_display(state_manager.get_error_state(), show_retry=False)
                else:
                    # Bootstrap failed again
                    error_msg = "Bootstrap failed"
                    if result.error:
                        error_msg = result.error.get("message", error_msg)
                    state_manager.set_error(
                        message=f"Retry failed: {error_msg}",
                        error_type="bootstrap",
                        can_retry=True,
                    )
            finally:
                loop.close()
        
        elif error_type == "api":
            # For general API errors, just clear and let the next interval retry
            state_manager.clear_error()
            return create_error_display(state_manager.get_error_state(), show_retry=False)
        
        else:
            # For other error types, clear the error
            state_manager.clear_error()
            return create_error_display(state_manager.get_error_state(), show_retry=False)
    
    except Exception as e:
        # Retry failed with exception
        state_manager.set_error(
            message=f"Retry failed: {str(e)}",
            error_type=error_type,
            can_retry=True,
        )
    
    return create_error_display(state_manager.get_error_state(), show_retry=True)


# =============================================================================
# Callbacks - JWT Refresh
# Requirement 3.9: Refresh JWT when <1 hour remaining
# =============================================================================

@app.callback(
    [
        Output("jwt-refresh-store", "data"),
        Output("auth-store", "data", allow_duplicate=True),
    ],
    [Input("jwt-refresh-interval", "n_intervals")],
    [State("auth-store", "data")],
    prevent_initial_call=True,
)
def check_and_refresh_jwt(
    n_intervals: int,
    auth_data: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Check JWT expiry and trigger refresh if needed.
    
    Requirement 3.9: WHEN JWT token has less than 1 hour remaining,
    THE Dashboard SHALL refresh via POST /v1/auth/refresh.
    
    Args:
        n_intervals: Number of intervals elapsed
        auth_data: Current auth store data
    
    Returns:
        Tuple of (jwt refresh store data, updated auth data)
    """
    # Check if user is authenticated
    if not auth_data or not auth_data.get("authenticated"):
        return (
            {"last_check": datetime.now(IST).isoformat(), "refresh_needed": False},
            auth_data or {"authenticated": False, "jwt_token": None},
        )
    
    # Check if JWT needs refresh using state manager
    if not state_manager.jwt_needs_refresh():
        # Get expiry info for logging
        expiry, seconds_remaining = state_manager.get_jwt_expiry_info()
        return (
            {
                "last_check": datetime.now(IST).isoformat(),
                "refresh_needed": False,
                "seconds_remaining": seconds_remaining,
            },
            auth_data,
        )
    
    # JWT needs refresh - attempt to refresh
    client = get_api_client()
    
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(client.refresh_token())
        
        if result.ok and result.data:
            new_token = result.data.get("token")
            
            if new_token:
                # Update API client
                client.jwt_token = new_token
                
                # Update state manager with new token
                state_manager.update_jwt_token(new_token)
                
                # Update auth store
                new_auth_data = {
                    "authenticated": True,
                    "jwt_token": new_token,
                }
                
                return (
                    {
                        "last_check": datetime.now(IST).isoformat(),
                        "refresh_needed": False,
                        "last_refresh": datetime.now(IST).isoformat(),
                        "refresh_success": True,
                    },
                    new_auth_data,
                )
        
        # Refresh failed but not a critical error - keep existing token
        return (
            {
                "last_check": datetime.now(IST).isoformat(),
                "refresh_needed": True,
                "refresh_success": False,
                "error": "Refresh returned no token",
            },
            auth_data,
        )
        
    except Exception as e:
        # Log error but don't clear session yet - token might still be valid
        return (
            {
                "last_check": datetime.now(IST).isoformat(),
                "refresh_needed": True,
                "refresh_success": False,
                "error": str(e),
            },
            auth_data,
        )
    finally:
        loop.close()


# =============================================================================
# Callbacks - Logout
# Requirement 3.10: Handle auth errors and allow retry
# =============================================================================

@app.callback(
    [
        Output("auth-store", "data", allow_duplicate=True),
        Output("url", "pathname", allow_duplicate=True),
    ],
    [Input("logout-btn", "n_clicks")],
    prevent_initial_call=True,
)
def handle_logout(n_clicks: int) -> Tuple[Dict[str, Any], str]:
    """Handle logout button click.
    
    Clears user session, disconnects streaming clients, and redirects to login page.
    
    Args:
        n_clicks: Button click count
    
    Returns:
        Tuple of (cleared auth data, login pathname)
    """
    if not n_clicks:
        raise PreventUpdate
    
    # Disconnect streaming clients
    disconnect_streaming_clients()
    
    # Clear state manager session
    state_manager.clear_user_session()
    
    # Clear API client token
    client = get_api_client()
    client.jwt_token = None
    
    # Return cleared auth data and redirect to login
    return (
        {"authenticated": False, "jwt_token": None},
        "/login",
    )


# =============================================================================
# Callbacks - Symbol Change
# Requirement 6.7, 10.5: Update displays when symbol changes
# =============================================================================

@app.callback(
    Output("selected-symbol-store", "data"),
    [Input({"type": "symbol-card", "symbol": ALL}, "n_clicks")],
    [State("selected-symbol-store", "data")],
    prevent_initial_call=True,
)
def handle_symbol_change(
    n_clicks_list: List[int],
    current_symbol: str,
) -> str:
    """Handle symbol card clicks to change selected symbol.
    
    Requirement 6.7: When user changes symbol, update chart with new symbol data.
    Requirement 10.5: When user clicks a symbol, switch all views to that symbol.
    
    Args:
        n_clicks_list: List of click counts for each symbol card
        current_symbol: Currently selected symbol
    
    Returns:
        New selected symbol
    """
    if not ctx.triggered_id:
        raise PreventUpdate
    
    # Get the clicked symbol from the pattern-matching callback
    triggered_id = ctx.triggered_id
    if isinstance(triggered_id, dict) and "symbol" in triggered_id:
        new_symbol = triggered_id["symbol"]
        return new_symbol
    
    raise PreventUpdate


@app.callback(
    Output("option-chain-section", "children"),
    [
        Input("selected-symbol-store", "data"),
        Input("selected-mode-store", "data"),
        Input("slow-interval", "n_intervals"),
    ],
    [State("current-page-store", "data")],
    prevent_initial_call=True,
)
def update_option_chain(
    selected_symbol: str,
    selected_mode: str,
    n_intervals: int,
    current_page: str,
) -> html.Div:
    """Update option chain table when symbol or mode changes.
    
    Requirement 6.7: Update all charts and displays when symbol changes.
    
    Args:
        selected_symbol: Currently selected symbol
        selected_mode: Currently selected mode
        n_intervals: Slow interval count (for periodic refresh)
        current_page: Current page name
    
    Returns:
        Updated option chain table component
    """
    # Only update if on main page
    if current_page not in ["main", None]:
        raise PreventUpdate
    
    symbol = selected_symbol or "nifty"
    mode = selected_mode or "current"
    
    # Get option chain data
    option_chain = state_manager.get_option_chain(symbol, mode)
    
    # Get underlying price for ATM detection
    tick = state_manager.get_ltp(symbol)
    underlying_price = tick.ltp if tick else None
    
    return create_option_chain_table(option_chain, underlying_price)


# =============================================================================
# Callbacks - Mode Change
# Requirement 13.3: Update displays when mode changes
# =============================================================================

@app.callback(
    Output("selected-mode-store", "data"),
    [Input({"type": "header-mode-tab", "mode": ALL}, "n_clicks")],
    [State("selected-mode-store", "data")],
    prevent_initial_call=True,
)
def handle_mode_change(
    n_clicks_list: List[int],
    current_mode: str,
) -> str:
    """Handle mode tab clicks to change selected mode.
    
    Requirement 13.3: When user switches mode, update all displays with selected mode data.
    
    Args:
        n_clicks_list: List of click counts for each mode tab
        current_mode: Currently selected mode
    
    Returns:
        New selected mode
    """
    if not ctx.triggered_id:
        raise PreventUpdate
    
    # Get the clicked mode from the pattern-matching callback
    triggered_id = ctx.triggered_id
    if isinstance(triggered_id, dict) and "mode" in triggered_id:
        new_mode = triggered_id["mode"]
        # Allow all modes including historical
        return new_mode
    
    raise PreventUpdate


# =============================================================================
# Callbacks - Historical Mode Controls
# =============================================================================

@app.callback(
    Output("historical-controls", "style"),
    [Input("selected-mode-store", "data")],
)
def toggle_historical_controls(mode: str) -> Dict[str, Any]:
    """Show/hide historical controls based on selected mode.
    
    Args:
        mode: Currently selected mode
    
    Returns:
        Style dict with display property
    """
    if mode == "historical":
        return {
            "display": "flex",
            "gap": "10px",
            "alignItems": "flex-start",
            "marginLeft": "15px",
        }
    return {"display": "none"}


@app.callback(
    [
        Output("candlestick-chart", "figure", allow_duplicate=True),
        Output("ema-chart", "figure", allow_duplicate=True),
        Output("skew-pcr-chart", "figure", allow_duplicate=True),
        Output("indicators-section", "children", allow_duplicate=True),
    ],
    [Input("historical-fetch-btn", "n_clicks")],
    [
        State("historical-symbol-picker", "value"),
        State("historical-date-picker", "date"),
        State("selected-mode-store", "data"),
        State("auth-store", "data"),
    ],
    prevent_initial_call=True,
)
def fetch_historical_data(
    n_clicks: int,
    symbol: str,
    date_str: str,
    mode: str,
    auth_data: Dict[str, Any],
) -> Tuple[go.Figure, go.Figure, go.Figure, html.Div]:
    """Fetch and display historical data for selected symbol and date.
    
    Args:
        n_clicks: Button click count
        symbol: Selected symbol
        date_str: Selected date (YYYY-MM-DD)
        mode: Current mode
        auth_data: Authentication data
    
    Returns:
        Tuple of (candlestick_fig, ema_fig, skew_pcr_fig, indicators_panel)
    """
    import structlog
    logger = structlog.get_logger(__name__)
    
    if not n_clicks or mode != "historical":
        raise PreventUpdate
    
    if not symbol or not date_str:
        raise PreventUpdate
    
    logger.info("historical_fetch_requested", symbol=symbol, date=date_str)
    
    client = get_api_client()
    
    # Fetch historical snapshot
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(
            client.historical_snapshot(date=date_str, symbols=[symbol])
        )
    finally:
        loop.close()
    
    if not result.ok or not result.data:
        logger.warning("historical_fetch_failed", error=result.error)
        empty_fig = create_empty_chart(f"No historical data for {symbol.upper()} on {date_str}")
        return (
            empty_fig,
            empty_fig,
            empty_fig,
            create_indicators_panel(IndicatorData(), None),
        )
    
    # Extract data for the symbol
    symbol_data = result.data.get(symbol, {})
    
    # Create charts from historical data
    candles = symbol_data.get("candles", [])
    indicators = symbol_data.get("indicators", {})
    skew_history = symbol_data.get("skew_history", [])
    pcr_history = symbol_data.get("pcr_history", [])
    
    # Candlestick chart
    if candles:
        candlestick_fig = create_candlestick_chart(candles, symbol)
    else:
        candlestick_fig = create_empty_chart(f"No candle data for {symbol.upper()}")
    
    # EMA chart
    if candles:
        ema_fig = create_ema_chart(candles, symbol)
    else:
        ema_fig = create_empty_chart(f"No EMA data for {symbol.upper()}")
    
    # Skew/PCR chart
    if skew_history or pcr_history:
        # Combine separate skew and pcr history lists into tuples
        # Historical API returns separate lists, but chart expects (ts, skew, pcr) tuples
        combined_history = []
        max_len = max(len(skew_history) if skew_history else 0, len(pcr_history) if pcr_history else 0)
        for i in range(max_len):
            ts = None
            skew_val = None
            pcr_val = None
            if skew_history and i < len(skew_history):
                entry = skew_history[i]
                if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                    ts = entry[0]
                    skew_val = entry[1]
            if pcr_history and i < len(pcr_history):
                entry = pcr_history[i]
                if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                    if ts is None:
                        ts = entry[0]
                    pcr_val = entry[1]
            if ts is not None:
                combined_history.append((ts, skew_val, pcr_val))
        skew_pcr_fig = create_skew_pcr_chart(combined_history, symbol)
    else:
        skew_pcr_fig = create_empty_chart(f"No Skew/PCR history for {symbol.upper()}")
    
    # Indicators panel
    indicator_data = IndicatorData(
        skew=indicators.get("skew"),
        pcr=indicators.get("pcr"),
        signal=indicators.get("signal", "NEUTRAL"),
        skew_confidence=indicators.get("skew_confidence"),
        adr=indicators.get("adr"),
        rsi=indicators.get("rsi"),
    )
    indicators_panel = create_indicators_panel(indicator_data, None)
    
    logger.info("historical_fetch_success", symbol=symbol, date=date_str)
    
    return (candlestick_fig, ema_fig, skew_pcr_fig, indicators_panel)


# =============================================================================
# Callbacks - Advanced Page
# Requirements 14.1: ADR Treemap
# =============================================================================

@app.callback(
    Output("page-nav-dropdown", "value"),
    [Input("url", "pathname")],
    prevent_initial_call=True,
)
def sync_nav_dropdown_with_url(pathname: str) -> str:
    """Sync navigation dropdown with current URL.
    
    Args:
        pathname: Current URL pathname
    
    Returns:
        Dropdown value matching the pathname
    """
    return pathname if pathname else "/"


@app.callback(
    Output("url", "pathname", allow_duplicate=True),
    [Input("page-nav-dropdown", "value")],
    prevent_initial_call=True,
)
def navigate_from_dropdown(value: str) -> str:
    """Navigate to page when dropdown selection changes.
    
    Args:
        value: Selected dropdown value (pathname)
    
    Returns:
        Pathname to navigate to
    """
    if value:
        return value
    raise PreventUpdate


@app.callback(
    [
        Output("adr-treemap-chart", "figure"),
        Output("adr-line-chart", "figure"),
    ],
    [
        Input("adr-refresh-btn", "n_clicks"),
        Input("advanced-symbol-selector", "value"),
    ],
    [State("auth-store", "data")],
    prevent_initial_call=True,
)
def update_adr_charts(
    n_clicks: int,
    symbol: str,
    auth_data: Dict[str, Any],
) -> Tuple[go.Figure, go.Figure]:
    """Update ADR treemap and line chart.
    
    Requirement 14.1: Display ADR data as a treemap on the Advanced tab.
    
    Args:
        n_clicks: Refresh button click count
        symbol: Selected symbol
        auth_data: Authentication data
    
    Returns:
        Tuple of (treemap figure, line chart figure)
    """
    import structlog
    logger = structlog.get_logger(__name__)
    
    if not symbol:
        symbol = "nifty"
    
    client = get_api_client()
    
    # Fetch ADR constituents for treemap
    loop = asyncio.new_event_loop()
    try:
        constituents = loop.run_until_complete(fetch_adr_constituents(symbol, client))
    finally:
        loop.close()
    
    # Get ADR history from state manager (accumulated from bootstrap + SSE)
    adr_history_loop = asyncio.new_event_loop()
    try:
        adr_history = adr_history_loop.run_until_complete(fetch_adr_history(symbol, state_manager))
    finally:
        adr_history_loop.close()
    
    # Create treemap
    if constituents:
        treemap_fig = create_adr_treemap(constituents, symbol)
    else:
        treemap_fig = create_empty_chart(f"No ADR data for {symbol.upper()}")
    
    # Create line chart
    line_fig = create_adr_line_chart(adr_history, symbol)
    
    return treemap_fig, line_fig


# =============================================================================
# Callbacks - Debugging Page
# Requirements 18.1-18.7: REST Testing
# =============================================================================

@app.callback(
    Output("debug-endpoint-form", "children"),
    [Input("debug-endpoint-selector", "value")],
    prevent_initial_call=True,
)
def update_debug_endpoint_form(endpoint_id: str) -> html.Div:
    """Update the endpoint form when a different endpoint is selected.
    
    Args:
        endpoint_id: Selected endpoint identifier
    
    Returns:
        Endpoint card component
    """
    endpoint = debug_get_endpoint_by_id(endpoint_id)
    if endpoint:
        return debug_create_endpoint_card(endpoint)
    raise PreventUpdate


@app.callback(
    [
        Output("debug-response-json", "children"),
        Output("debug-response-time", "children"),
        Output("debug-response-status", "children"),
        Output("debug-response-status", "style"),
    ],
    [Input({"type": "debug-execute-btn", "endpoint": ALL}, "n_clicks")],
    [
        State("debug-endpoint-selector", "value"),
        # Snapshot params
        State("debug-param-snapshot-symbol", "value"),
        State("debug-param-snapshot-mode", "value"),
        # Historical params
        State("debug-param-historical-date", "date"),
        State("debug-param-historical-symbols", "value"),
        # Candles params
        State("debug-param-candles-symbol", "value"),
        State("debug-param-candles-interval", "value"),
        State("debug-param-candles-start", "value"),
        State("debug-param-candles-end", "value"),
        # Spot params
        State("debug-param-spot-symbols", "value"),
        # ADR params
        State("debug-param-adr_constituents-symbol", "value"),
        # Bootstrap params
        State("debug-param-bootstrap-symbols", "value"),
    ],
    prevent_initial_call=True,
)
def execute_debug_rest_request(
    n_clicks_list: List[int],
    endpoint_id: str,
    # Snapshot params
    snapshot_symbol: str,
    snapshot_mode: str,
    # Historical params
    historical_date: str,
    historical_symbols: str,
    # Candles params
    candles_symbol: str,
    candles_interval: str,
    candles_start: str,
    candles_end: str,
    # Spot params
    spot_symbols: str,
    # ADR params
    adr_symbol: str,
    # Bootstrap params
    bootstrap_symbols: str,
) -> Tuple[str, str, str, Dict[str, Any]]:
    """Execute REST endpoint request and display results.
    
    Args:
        n_clicks_list: Click counts for execute buttons
        endpoint_id: Selected endpoint
        Various state params for each endpoint type
    
    Returns:
        Tuple of (json response, response time text, status text, status style)
    """
    if not ctx.triggered_id or not any(n_clicks_list):
        raise PreventUpdate
    
    # Build params dict based on endpoint
    params = {}
    if endpoint_id == "snapshot":
        params = {"symbol": snapshot_symbol, "mode": snapshot_mode}
    elif endpoint_id == "historical":
        params = {"date": historical_date, "symbols": historical_symbols}
    elif endpoint_id == "candles":
        params = {
            "symbol": candles_symbol,
            "interval": candles_interval,
            "start": candles_start,
            "end": candles_end,
        }
    elif endpoint_id == "spot":
        params = {"symbols": spot_symbols}
    elif endpoint_id == "adr_constituents":
        params = {"symbol": adr_symbol}
    elif endpoint_id == "bootstrap":
        params = {"symbols": bootstrap_symbols}
    
    client = get_api_client()
    
    # Execute request
    loop = asyncio.new_event_loop()
    try:
        response_data, elapsed_ms, status_code = loop.run_until_complete(
            debug_execute_rest_endpoint(endpoint_id, params, client)
        )
    finally:
        loop.close()
    
    # Format response
    json_str = json.dumps(response_data, indent=2, default=str)
    time_str = f"{elapsed_ms:.0f}ms"
    
    if response_data.get("ok"):
        status_str = f"✓ {status_code}"
        status_style = {
            "backgroundColor": COLORS["positive"],
            "color": COLORS["text_light"],
            "padding": "2px 8px",
            "borderRadius": "3px",
        }
    else:
        status_str = f"✗ {status_code}"
        status_style = {
            "backgroundColor": COLORS["negative"],
            "color": COLORS["text_light"],
            "padding": "2px 8px",
            "borderRadius": "3px",
        }
    
    return json_str, time_str, status_str, status_style


# =============================================================================
# Callbacks - Admin Page User Management
# Requirement 15.6: User list display
# =============================================================================

@app.callback(
    [
        Output("users-table", "data"),
        Output("users-info-message", "children"),
    ],
    [Input("users-load-btn", "n_clicks")],
    prevent_initial_call=True,
)
def load_users_list(
    n_clicks: int,
) -> Tuple[List[Dict], str]:
    """Load user list from API.
    
    Requirement 15.6: Display user list from GET /v1/admin/users
    
    Args:
        n_clicks: Button click count
    
    Returns:
        Tuple of (users data, info message)
    """
    if not n_clicks:
        raise PreventUpdate
    
    client = get_api_client()
    
    # Run async function in sync context
    loop = asyncio.new_event_loop()
    try:
        success, users, total, has_more, message = loop.run_until_complete(get_users(client))
    finally:
        loop.close()
    
    if success:
        # Format users for table display
        formatted_users = []
        for user in users:
            formatted_users.append({
                "email": user.get("email", "--"),
                "role": user.get("role", "--"),
                "status": user.get("status", "active"),
                "created_at": user.get("created_at", "--")[:10] if user.get("created_at") else "--",
                "last_login": user.get("last_login", "--")[:10] if user.get("last_login") else "--",
            })
        # Include pagination info in message
        if has_more:
            message = f"{message} (more available)"
        return formatted_users, message
    else:
        return [], message


@app.callback(
    [
        Output("strike-range-status", "children"),
        Output("strike-range-status", "style"),
    ],
    [Input("strike-range-submit-btn", "n_clicks")],
    [
        State("strike-range-symbol", "value"),
        State("strike-range-mode", "value"),
        State("strike-range-lower", "value"),
        State("strike-range-upper", "value"),
    ],
    prevent_initial_call=True,
)
def update_strike_ranges(
    n_clicks: int,
    symbol: str,
    mode: str,
    lower_strike: float,
    upper_strike: float,
) -> Tuple[str, Dict[str, Any]]:
    """Update strike ranges configuration.
    
    Requirement 15.7: Strike range configuration via POST /v1/admin/strike-ranges
    
    Args:
        n_clicks: Button click count
        symbol: Selected symbol
        mode: Selected mode
        lower_strike: Lower strike price
        upper_strike: Upper strike price
    
    Returns:
        Tuple of (status message, status style)
    """
    if not n_clicks:
        raise PreventUpdate
    
    # Validate inputs
    if not symbol or not mode:
        return (
            "Please select symbol and mode.",
            {"color": COLORS["negative"], "marginLeft": "15px", "fontSize": "12px"},
        )
    
    if lower_strike is None or upper_strike is None:
        return (
            "Please enter both lower and upper strike prices.",
            {"color": COLORS["negative"], "marginLeft": "15px", "fontSize": "12px"},
        )
    
    if lower_strike >= upper_strike:
        return (
            "Lower strike must be less than upper strike.",
            {"color": COLORS["negative"], "marginLeft": "15px", "fontSize": "12px"},
        )
    
    client = get_api_client()
    
    # Run async function in sync context
    loop = asyncio.new_event_loop()
    try:
        success, message = loop.run_until_complete(
            set_strike_ranges(client, symbol, mode, lower_strike, upper_strike)
        )
    finally:
        loop.close()
    
    if success:
        return (
            message,
            {"color": COLORS["positive"], "marginLeft": "15px", "fontSize": "12px"},
        )
    else:
        return (
            message,
            {"color": COLORS["negative"], "marginLeft": "15px", "fontSize": "12px"},
        )


# =============================================================================
# Callbacks - Login Page Authentication
# Requirements 3.1, 3.2, 3.4, 3.5, 3.6, 3.7, 3.8, 3.10
# =============================================================================

@app.callback(
    [
        Output("login-status", "children"),
        Output("login-status", "style"),
        Output("auth-store", "data"),
        Output("url", "pathname", allow_duplicate=True),
    ],
    [Input("submit-callback-btn", "n_clicks")],
    [
        State("callback-url-input", "value"),
        State("auth-store", "data"),
    ],
    prevent_initial_call=True,
)
def handle_callback_url_submit(
    n_clicks: int,
    callback_url: str,
    auth_data: Dict[str, Any],
) -> Tuple[str, Dict[str, Any], Dict[str, Any], str]:
    """Handle callback URL submission for OAuth code exchange.
    
    Requirements:
        3.5: Parse authorization code from pasted URL (extract 'code' query parameter)
        3.6: Exchange code via POST /v1/auth/google/exchange
        3.7: Store JWT token securely in session state
        3.10: Display error message and allow retry if authentication fails
    
    Args:
        n_clicks: Button click count
        callback_url: Pasted callback URL containing auth code
        auth_data: Current auth store data
    
    Returns:
        Tuple of (status message, status style, auth data, redirect pathname)
    """
    if not n_clicks:
        raise PreventUpdate
    
    if not callback_url:
        return (
            "Please paste the callback URL from your browser.",
            {
                "marginTop": "15px",
                "padding": "12px",
                "borderRadius": "6px",
                "textAlign": "center",
                "fontSize": "13px",
                "backgroundColor": f"{COLORS['negative']}20",
                "color": COLORS["negative"],
                "border": f"1px solid {COLORS['negative']}",
                "display": "block",
            },
            auth_data or {"authenticated": False, "jwt_token": None},
            "/login",
        )
    
    # Parse authorization code from URL (Requirement 3.5)
    auth_code = parse_authorization_code(callback_url)
    
    if not auth_code:
        return (
            "Could not find authorization code in the URL. Please make sure you copied the complete URL.",
            {
                "marginTop": "15px",
                "padding": "12px",
                "borderRadius": "6px",
                "textAlign": "center",
                "fontSize": "13px",
                "backgroundColor": f"{COLORS['negative']}20",
                "color": COLORS["negative"],
                "border": f"1px solid {COLORS['negative']}",
                "display": "block",
            },
            auth_data or {"authenticated": False, "jwt_token": None},
            "/login",
        )
    
    # Exchange code for JWT (Requirement 3.6)
    client = get_api_client()
    
    import structlog
    logger = structlog.get_logger(__name__)
    
    # Use a single event loop for all async operations
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        result = loop.run_until_complete(client.exchange_google_code(auth_code))
    except Exception as e:
        loop.close()
        # Requirement 3.10: Display error message and allow retry
        return (
            f"Authentication failed: {str(e)}",
            {
                "marginTop": "15px",
                "padding": "12px",
                "borderRadius": "6px",
                "textAlign": "center",
                "fontSize": "13px",
                "backgroundColor": f"{COLORS['negative']}20",
                "color": COLORS["negative"],
                "border": f"1px solid {COLORS['negative']}",
                "display": "block",
            },
            auth_data or {"authenticated": False, "jwt_token": None},
            "/login",
        )
    
    if result.ok and result.data:
        jwt_token = result.data.get("token")
        
        if jwt_token:
            # Store JWT in API client
            client.jwt_token = jwt_token
            
            # Fetch user info (Requirement 3.8)
            # FIX: Store role in auth-store to fix admin access race condition
            user_role = None
            user_email = None
            user_name = None
            
            try:
                user_result = loop.run_until_complete(client.get_me())
                logger.info(
                    "get_me_response",
                    ok=user_result.ok,
                    data=user_result.data,
                    error=user_result.error,
                )
                if user_result.ok and user_result.data:
                    # API returns {"user": {...}, "subscription": ...}
                    # Extract user info from nested structure
                    user_data = user_result.data.get("user", user_result.data)
                    user_role = user_data.get("role")
                    user_email = user_data.get("email")
                    user_name = user_data.get("name")
                    logger.info(
                        "user_info_extracted",
                        role=user_role,
                        email=user_email,
                        name=user_name,
                    )
                    # Update state manager with user session
                    state_manager.set_user_session(
                        email=user_email,
                        role=user_role,
                        name=user_name,
                        jwt_token=jwt_token,
                    )
            except Exception as e:
                logger.error("get_me_failed", error=str(e))
            
            # Close the loop after all async operations
            loop.close()
            
            # Update auth store (Requirement 3.7)
            # FIX: Include role in auth-store for reliable admin access check
            new_auth_data = {
                "authenticated": True,
                "jwt_token": jwt_token,
                "role": user_role,  # FIX: Store role for admin page access
                "email": user_email,
                "name": user_name,
            }
            
            return (
                "Authentication successful! Redirecting...",
                {
                    "marginTop": "15px",
                    "padding": "12px",
                    "borderRadius": "6px",
                    "textAlign": "center",
                    "fontSize": "13px",
                    "backgroundColor": f"{COLORS['positive']}20",
                    "color": COLORS["positive"],
                    "border": f"1px solid {COLORS['positive']}",
                    "display": "block",
                },
                new_auth_data,
                "/",  # Redirect to main page
            )
    
    # Close loop if we get here (auth failed but no exception)
    loop.close()
    
    # Authentication failed (Requirement 3.10)
    error_msg = "Authentication failed"
    if result.error:
        error_msg = result.error.get("message", error_msg)
    
    return (
        error_msg,
        {
            "marginTop": "15px",
            "padding": "12px",
            "borderRadius": "6px",
            "textAlign": "center",
            "fontSize": "13px",
            "backgroundColor": f"{COLORS['negative']}20",
            "color": COLORS["negative"],
            "border": f"1px solid {COLORS['negative']}",
            "display": "block",
        },
        auth_data or {"authenticated": False, "jwt_token": None},
        "/login",
    )


@app.callback(
    [
        Output("login-status", "children", allow_duplicate=True),
        Output("login-status", "style", allow_duplicate=True),
        Output("auth-store", "data", allow_duplicate=True),
        Output("url", "pathname", allow_duplicate=True),
    ],
    [Input("use-jwt-btn", "n_clicks")],
    [
        State("jwt-token-input", "value"),
        State("auth-store", "data"),
    ],
    prevent_initial_call=True,
)
def handle_direct_jwt_input(
    n_clicks: int,
    jwt_token: str,
    auth_data: Dict[str, Any],
) -> Tuple[str, Dict[str, Any], Dict[str, Any], str]:
    """Handle direct JWT token input for testing.
    
    This is an alternative authentication method for testing purposes.
    
    Args:
        n_clicks: Button click count
        jwt_token: JWT token entered by user
        auth_data: Current auth store data
    
    Returns:
        Tuple of (status message, status style, auth data, redirect pathname)
    """
    if not n_clicks:
        raise PreventUpdate
    
    if not jwt_token:
        return (
            "Please enter a JWT token.",
            {
                "marginTop": "15px",
                "padding": "12px",
                "borderRadius": "6px",
                "textAlign": "center",
                "fontSize": "13px",
                "backgroundColor": f"{COLORS['negative']}20",
                "color": COLORS["negative"],
                "border": f"1px solid {COLORS['negative']}",
                "display": "block",
            },
            auth_data or {"authenticated": False, "jwt_token": None},
            "/login",
        )
    
    # Set JWT in API client
    client = get_api_client()
    client.jwt_token = jwt_token
    
    # Verify token by fetching user info (Requirement 3.8)
    loop = asyncio.new_event_loop()
    try:
        user_result = loop.run_until_complete(client.get_me())
        
        if user_result.ok and user_result.data:
            # API returns {"user": {...}, "subscription": ...}
            # Extract user info from nested structure
            user_data = user_result.data.get("user", user_result.data)
            
            # Update state manager with user session
            state_manager.set_user_session(
                email=user_data.get("email"),
                role=user_data.get("role"),
                name=user_data.get("name"),
                jwt_token=jwt_token,
            )
            
            # Update auth store (include role for admin access check)
            new_auth_data = {
                "authenticated": True,
                "jwt_token": jwt_token,
                "role": user_data.get("role"),
                "email": user_data.get("email"),
                "name": user_data.get("name"),
            }
            
            return (
                "Token verified! Redirecting...",
                {
                    "marginTop": "15px",
                    "padding": "12px",
                    "borderRadius": "6px",
                    "textAlign": "center",
                    "fontSize": "13px",
                    "backgroundColor": f"{COLORS['positive']}20",
                    "color": COLORS["positive"],
                    "border": f"1px solid {COLORS['positive']}",
                    "display": "block",
                },
                new_auth_data,
                "/",  # Redirect to main page
            )
        else:
            error_msg = "Invalid token"
            if user_result.error:
                error_msg = user_result.error.get("message", error_msg)
            
            return (
                f"Token verification failed: {error_msg}",
                {
                    "marginTop": "15px",
                    "padding": "12px",
                    "borderRadius": "6px",
                    "textAlign": "center",
                    "fontSize": "13px",
                    "backgroundColor": f"{COLORS['negative']}20",
                    "color": COLORS["negative"],
                    "border": f"1px solid {COLORS['negative']}",
                    "display": "block",
                },
                auth_data or {"authenticated": False, "jwt_token": None},
                "/login",
            )
    except Exception as e:
        return (
            f"Token verification failed: {str(e)}",
            {
                "marginTop": "15px",
                "padding": "12px",
                "borderRadius": "6px",
                "textAlign": "center",
                "fontSize": "13px",
                "backgroundColor": f"{COLORS['negative']}20",
                "color": COLORS["negative"],
                "border": f"1px solid {COLORS['negative']}",
                "display": "block",
            },
            auth_data or {"authenticated": False, "jwt_token": None},
            "/login",
        )
    finally:
        loop.close()


# =============================================================================
# Callbacks - Bootstrap Data Fetch
# Requirement 5.1: Fetch bootstrap data after authentication
# =============================================================================

@app.callback(
    Output("hidden-div", "children", allow_duplicate=True),
    [Input("auth-store", "data")],
    prevent_initial_call=True,
)
def fetch_bootstrap_on_auth(auth_data: Dict[str, Any]) -> str:
    """Fetch bootstrap data and connect streaming clients when authentication state changes.
    
    Requirements:
        5.1: Fetch bootstrap data from GET /v1/dashboard/bootstrap
        5.2: Request all symbols (nifty, banknifty, sensex, finnifty) in bootstrap
        5.3: Include candles and option chain data in bootstrap request
        11.1, 11.2: Connect WebSocket for fast LTP updates
        12.1, 12.2: Connect SSE for indicator updates
    
    This callback triggers when the user successfully authenticates,
    fetching initial data for all symbols and populating the state manager,
    then connecting the streaming clients for real-time updates.
    
    Args:
        auth_data: Authentication store data
    
    Returns:
        Empty string (hidden div content)
    """
    if not auth_data or not auth_data.get("authenticated"):
        # User logged out - disconnect streaming clients
        disconnect_streaming_clients()
        raise PreventUpdate
    
    jwt_token = auth_data.get("jwt_token")
    if not jwt_token:
        raise PreventUpdate
    
    import structlog
    logger = structlog.get_logger(__name__)
    
    # Fetch bootstrap data
    client = get_api_client()
    client.jwt_token = jwt_token
    
    loop = asyncio.new_event_loop()
    try:
        # Requirement 5.1, 5.2, 5.3: Fetch bootstrap with all symbols, candles, option chain, and indicators
        result = loop.run_until_complete(
            client.bootstrap(
                symbols=["nifty", "banknifty", "sensex", "finnifty"],
                include_candles=True,
                include_option_chain=True,
                include_indicators=True,
            )
        )
        
        if result.ok and result.data:
            # Parse and populate state manager with bootstrap data
            _populate_state_from_bootstrap(result.data, result.meta)
            logger.info("bootstrap_data_loaded", symbols=["nifty", "banknifty", "sensex", "finnifty"])
        else:
            # Requirement 5.6: Display error if bootstrap fails
            error_msg = "Bootstrap failed"
            if result.error:
                error_msg = result.error.get("message", error_msg)
            state_manager.set_error(
                message=error_msg,
                error_type="bootstrap",
                can_retry=True,
            )
            logger.error("bootstrap_failed", error=error_msg)
            
    except Exception as e:
        # Log error but don't crash - data will be fetched via SSE/WS
        logger.error("bootstrap_fetch_failed", error=str(e))
        state_manager.set_error(
            message=f"Bootstrap failed: {str(e)}",
            error_type="bootstrap",
            can_retry=True,
        )
    finally:
        loop.close()
    
    # Connect streaming clients after bootstrap
    # Requirements 11.1, 11.2, 12.1, 12.2
    try:
        connect_streaming_clients(jwt_token)
        print(f"[BOOTSTRAP] Streaming clients connected successfully")
        logger.info("streaming_clients_connected")
    except Exception as e:
        print(f"[BOOTSTRAP] ERROR connecting streaming clients: {e}")
        logger.error("streaming_clients_connection_failed", error=str(e))
    
    return ""


def _populate_state_from_bootstrap(data: Dict[str, Any], meta: Optional[Dict[str, Any]]) -> None:
    """Populate state manager with bootstrap data.
    
    The bootstrap response uses COLUMNAR format:
    - candles_5m: { ts: [], open: [], high: [], low: [], close: [], volume: [] }
    - option_chain.columns: { strike: [], call_oi: [], put_oi: [], ... }
    - indicator_chart.series: { ts: [], skew: [], pcr: [] }
    
    Args:
        data: Bootstrap response data (nested by symbol/mode)
        meta: Bootstrap response meta
    """
    from .models import IndicatorData, OptionChainData, Candle, OptionStrike
    import structlog
    
    logger = structlog.get_logger(__name__)
    
    # Get today's date in IST for filtering candles
    today_ist = datetime.now(IST).date()
    logger.info("bootstrap_parsing_started", today_ist=str(today_ist))
    
    # Clear indicator history before re-populating from bootstrap
    # This prevents duplicate entries when bootstrap is called multiple times
    state_manager.clear_indicator_history()
    logger.info("indicator_history_cleared")
    
    # Update market state from meta
    if meta:
        market_state = meta.get("market_state", "UNKNOWN")
        state_manager.set_market_state(market_state)
        logger.info("market_state_set", market_state=market_state)
        
        # FIX-043: Parse and store market info fields
        is_trading_day = meta.get("is_trading_day")
        holiday_name = meta.get("holiday_name")
        previous_trading_day = meta.get("previous_trading_day")
        
        state_manager.set_market_info(
            market_state=market_state,
            is_trading_day=is_trading_day,
            holiday_name=holiday_name,
            previous_trading_day=previous_trading_day,
        )
        logger.info("market_info_set",
                   is_trading_day=is_trading_day,
                   holiday_name=holiday_name,
                   previous_trading_day=previous_trading_day)
        
        # Check for cache staleness
        if meta.get("cache_stale"):
            state_manager.set_error(
                message="Data may be stale - cache is outdated",
                error_type="staleness",
                can_retry=True,
            )
    
    # Parse bootstrap data for each symbol
    for symbol in ["nifty", "banknifty", "sensex", "finnifty"]:
        symbol_data = data.get(symbol, {})
        if not isinstance(symbol_data, dict):
            logger.warning("symbol_data_missing", symbol=symbol)
            continue
        
        logger.info("parsing_symbol", symbol=symbol)
        
        # FIX-023: Parse candles_5m at SYMBOL level (sibling of current/positional)
        candles_data = symbol_data.get("candles_5m", {})
        if isinstance(candles_data, dict):
            ts_arr = candles_data.get("ts", [])
            open_arr = candles_data.get("open", [])
            high_arr = candles_data.get("high", [])
            low_arr = candles_data.get("low", [])
            close_arr = candles_data.get("close", [])
            volume_arr = candles_data.get("volume", [])
            
            candles = []
            total_candles = 0
            for i in range(len(ts_arr)):
                try:
                    ts_str = ts_arr[i] if i < len(ts_arr) else ""
                    if ts_str:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        ts_ist = ts.astimezone(IST)
                    else:
                        continue
                except (ValueError, TypeError):
                    continue
                
                total_candles += 1
                
                # Filter to today's candles only
                if ts_ist.date() != today_ist:
                    continue
                
                # Filter to market hours: 9:15 AM - 3:30 PM IST (555 - 930 minutes)
                time_minutes = ts_ist.hour * 60 + ts_ist.minute
                if time_minutes < 555 or time_minutes > 930:
                    continue
                
                candles.append(Candle(
                    ts=ts_ist,
                    open=open_arr[i] if i < len(open_arr) else 0,
                    high=high_arr[i] if i < len(high_arr) else 0,
                    low=low_arr[i] if i < len(low_arr) else 0,
                    close=close_arr[i] if i < len(close_arr) else 0,
                    volume=volume_arr[i] if i < len(volume_arr) else 0,
                ))
            
            if candles:
                state_manager.update_candles(symbol, candles)
                # Update LTP from latest candle close
                state_manager.update_ltp(symbol, candles[-1].close, 0, 0)
                logger.info("candles_parsed_symbol_level",
                           symbol=symbol,
                           total_candles=total_candles,
                           filtered_candles=len(candles))
                print(f"[BOOTSTRAP] ✓ Candles for {symbol}: {len(candles)} candles (filtered from {total_candles})")
        
        # FIX-023: Parse technical_indicators at SYMBOL level
        tech_indicators = symbol_data.get("technical_indicators", {})
        if isinstance(tech_indicators, dict):
            ts_arr = tech_indicators.get("ts", [])
            ema_9_arr = tech_indicators.get("ema_9", [])  # FIX-023: ema_5 -> ema_9
            ema_21_arr = tech_indicators.get("ema_21", [])
            rsi_arr = tech_indicators.get("rsi", [])
            adr_arr = tech_indicators.get("adr", [])
            
            if ts_arr and (ema_9_arr or ema_21_arr):
                ema_count = 0
                for i in range(len(ts_arr)):
                    try:
                        ts_str = ts_arr[i] if i < len(ts_arr) else ""
                        if not ts_str:
                            continue
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        ts_ist = ts.astimezone(IST)
                        
                        # Filter to today's data only
                        if ts_ist.date() != today_ist:
                            continue
                        
                        # Filter to market hours: 9:15 AM - 3:30 PM IST
                        time_minutes = ts_ist.hour * 60 + ts_ist.minute
                        if time_minutes < 555 or time_minutes > 930:
                            continue
                        
                        ema_9_val = ema_9_arr[i] if i < len(ema_9_arr) else None
                        ema_21_val = ema_21_arr[i] if i < len(ema_21_arr) else None
                        
                        # Skip entries with null EMA values
                        if ema_9_val is None or ema_21_val is None:
                            continue
                        
                        # Get ADR and RSI values for this timestamp
                        adr_val = adr_arr[i] if i < len(adr_arr) else None
                        rsi_val = rsi_arr[i] if i < len(rsi_arr) else None
                        
                        # Update EMA, ADR, RSI history via indicators
                        ema_indicators = IndicatorData(
                            ema_5=ema_9_val,  # Map ema_9 to ema_5 field for state manager
                            ema_21=ema_21_val,
                            adr=adr_val,
                            rsi=rsi_val,
                            ts=ts_ist,
                        )
                        state_manager.update_indicators(symbol, "current", ema_indicators)
                        ema_count += 1
                    except (ValueError, TypeError):
                        continue
                
                if ema_count > 0:
                    print(f"[BOOTSTRAP] ✓ Technical indicators for {symbol}: {ema_count} EMA/ADR/RSI points")
                    logger.info("technical_indicators_parsed",
                               symbol=symbol,
                               ema_count=ema_count)
        
        for mode in ["current", "positional"]:
            mode_data = symbol_data.get(mode, {})
            if not isinstance(mode_data, dict):
                logger.warning("mode_data_missing", symbol=symbol, mode=mode)
                continue
            
            # Parse indicator_chart for indicators
            indicator_chart = mode_data.get("indicator_chart", {})
            if isinstance(indicator_chart, dict):
                series = indicator_chart.get("series", {})
                if isinstance(series, dict):
                    # Get columnar series data
                    ts_arr = series.get("ts", [])
                    skew_arr = series.get("skew", [])
                    pcr_arr = series.get("pcr", [])
                    
                    # Populate skew_pcr_history from bootstrap series data
                    # This provides initial timeseries data for the Skew/PCR chart
                    # Filter to today's data during market hours only (9:15 AM - 3:30 PM IST)
                    if ts_arr and skew_arr and pcr_arr:
                        filtered_count = 0
                        for i in range(len(ts_arr)):
                            try:
                                ts_str = ts_arr[i] if i < len(ts_arr) else ""
                                if not ts_str:
                                    continue
                                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                                ts_ist = ts.astimezone(IST)
                                
                                # Filter to today's data only
                                if ts_ist.date() != today_ist:
                                    continue
                                
                                # Filter to market hours only: 9:15 AM - 3:30 PM IST
                                hour = ts_ist.hour
                                minute = ts_ist.minute
                                time_minutes = hour * 60 + minute
                                market_start = 9 * 60 + 15  # 9:15 AM = 555 minutes
                                market_end = 15 * 60 + 30   # 3:30 PM = 930 minutes
                                
                                if time_minutes < market_start or time_minutes > market_end:
                                    continue
                                
                                skew_val = skew_arr[i] if i < len(skew_arr) else None
                                pcr_val = pcr_arr[i] if i < len(pcr_arr) else None
                                
                                # Skip entries with null values
                                if skew_val is None or pcr_val is None:
                                    continue
                                
                                # Create indicator data for this timestamp to populate history
                                hist_indicators = IndicatorData(
                                    skew=skew_val,
                                    pcr=pcr_val,
                                    ts=ts_ist,
                                )
                                state_manager.update_indicators(symbol, mode, hist_indicators)
                                filtered_count += 1
                            except (ValueError, TypeError):
                                continue
                        
                        logger.info("skew_pcr_history_populated",
                                   symbol=symbol,
                                   mode=mode,
                                   total_points=len(ts_arr),
                                   filtered_points=filtered_count)
                    
                    # Parse EMA data from series - REMOVED in FIX-023
            
            # FIX-030: Set latest indicator values including RSI, ADR from technical_indicators
            # and intuition_text from intuition_engine
            tech_indicators = symbol_data.get("technical_indicators", {})
            intuition_engine = mode_data.get("intuition_engine", {})
            
            # Get latest values from series
            latest_skew = None
            latest_pcr = None
            if isinstance(indicator_chart, dict):
                series = indicator_chart.get("series", {})
                if isinstance(series, dict):
                    skew_arr = series.get("skew", [])
                    pcr_arr = series.get("pcr", [])
                    for val in reversed(skew_arr):
                        if val is not None:
                            latest_skew = val
                            break
                    for val in reversed(pcr_arr):
                        if val is not None:
                            latest_pcr = val
                            break
            
            # Get latest RSI and ADR from technical_indicators
            latest_rsi = None
            latest_adr = None
            latest_ema_9 = None
            latest_ema_21 = None
            if isinstance(tech_indicators, dict):
                rsi_arr = tech_indicators.get("rsi", [])
                adr_arr = tech_indicators.get("adr", [])
                ema_9_arr = tech_indicators.get("ema_9", [])
                ema_21_arr = tech_indicators.get("ema_21", [])
                
                for val in reversed(rsi_arr):
                    if val is not None:
                        latest_rsi = val
                        break
                for val in reversed(adr_arr):
                    if val is not None:
                        latest_adr = val
                        break
                for val in reversed(ema_9_arr):
                    if val is not None:
                        latest_ema_9 = val
                        break
                for val in reversed(ema_21_arr):
                    if val is not None:
                        latest_ema_21 = val
                        break
            
            # FIX-042: Get intuition text, confidence, and recommendations
            intuition_text = None
            intuition_confidence = None
            intuition_recommendations = None
            if isinstance(intuition_engine, dict):
                intuition_text = intuition_engine.get("text")
                intuition_confidence = intuition_engine.get("confidence")
                intuition_recommendations = intuition_engine.get("recommendations")
            
            # Create comprehensive indicator data with all latest values
            if latest_skew is not None or latest_pcr is not None or latest_rsi is not None or latest_adr is not None:
                current_indicators = IndicatorData(
                    skew=latest_skew,
                    pcr=latest_pcr,
                    rsi=latest_rsi,
                    adr=latest_adr,
                    ema_5=latest_ema_9,  # Map ema_9 to ema_5 for legacy compatibility
                    ema_9=latest_ema_9,
                    ema_21=latest_ema_21,
                    intuition_text=intuition_text,
                    intuition_confidence=intuition_confidence,
                    intuition_recommendations=intuition_recommendations,
                    ts=datetime.now(IST),
                )
                state_manager.update_indicators(symbol, mode, current_indicators)
                logger.info("latest_indicators_set",
                           symbol=symbol,
                           mode=mode,
                           skew=latest_skew,
                           pcr=latest_pcr,
                           rsi=latest_rsi,
                           adr=latest_adr,
                           has_intuition=bool(intuition_text),
                           intuition_confidence=intuition_confidence,
                           has_recommendations=bool(intuition_recommendations))
                print(f"[BOOTSTRAP] ✓ Latest indicators for {symbol}/{mode}: skew={latest_skew}, pcr={latest_pcr}, rsi={latest_rsi}, adr={latest_adr}, confidence={intuition_confidence}")
            
            # Parse option_chain (columnar format)
            option_chain_data = mode_data.get("option_chain", {})
            if isinstance(option_chain_data, dict):
                columns = option_chain_data.get("columns", {})
                if isinstance(columns, dict):
                    strikes_arr = columns.get("strike", [])
                    call_oi_arr = columns.get("call_oi", [])
                    put_oi_arr = columns.get("put_oi", [])
                    skew_arr = columns.get("skew", [])
                    
                    logger.info("option_chain_parsing", 
                               symbol=symbol, 
                               mode=mode, 
                               strike_count=len(strikes_arr),
                               expiry=option_chain_data.get("expiry"))
                    print(f"[BOOTSTRAP] Parsing option chain for {symbol}/{mode}: {len(strikes_arr)} strikes, expiry={option_chain_data.get('expiry')}")
                    
                    # Only create option chain if we have strikes
                    if strikes_arr and len(strikes_arr) > 0:
                        parsed_strikes = []
                        for i in range(len(strikes_arr)):
                            parsed_strikes.append(OptionStrike(
                                strike=strikes_arr[i] if i < len(strikes_arr) else 0,
                                call_oi=call_oi_arr[i] if i < len(call_oi_arr) else 0,
                                put_oi=put_oi_arr[i] if i < len(put_oi_arr) else 0,
                                strike_skew=skew_arr[i] if i < len(skew_arr) else None,
                            ))
                        
                        # Get underlying LTP - prefer from bootstrap, fallback to current state LTP
                        # Backend may not include this field, so we use LTP from WebSocket/state
                        underlying = option_chain_data.get("underlying")
                        if underlying is None or underlying == 0.0:
                            # Fallback: use current LTP from state (populated by WebSocket or candles)
                            symbol_ltp = state_manager.get_ltp(symbol)
                            underlying = symbol_ltp.ltp if symbol_ltp else 0.0
                            logger.info("option_chain_underlying_fallback", 
                                       symbol=symbol, 
                                       mode=mode,
                                       underlying=underlying,
                                       from_state=True)
                        else:
                            logger.info("option_chain_underlying_from_bootstrap",
                                       symbol=symbol,
                                       mode=mode,
                                       underlying=underlying)
                        
                        option_chain = OptionChainData(
                            expiry=option_chain_data.get("expiry", ""),
                            underlying=underlying,
                            strikes=parsed_strikes,
                        )
                        state_manager.update_option_chain(symbol, mode, option_chain)
                        print(f"[BOOTSTRAP] ✓ Option chain updated for {symbol}/{mode}: {len(parsed_strikes)} strikes, underlying={underlying}")
                        logger.info("option_chain_updated", 
                                   symbol=symbol, 
                                   mode=mode, 
                                   strike_count=len(parsed_strikes),
                                   underlying=underlying)
                    else:
                        print(f"[BOOTSTRAP] ✗ No strikes for {symbol}/{mode} option chain")
                        logger.warning("option_chain_no_strikes", symbol=symbol, mode=mode)
            
            # FIX-023: candles_5m is now at symbol level, not mode level
            # Legacy fallback: check mode level for backward compatibility
            if mode == "current":
                mode_candles_data = mode_data.get("candles_5m", {})
                if isinstance(mode_candles_data, dict) and mode_candles_data.get("ts"):
                    # Legacy: candles at mode level (pre-FIX-023)
                    ts_arr = mode_candles_data.get("ts", [])
                    open_arr = mode_candles_data.get("open", [])
                    high_arr = mode_candles_data.get("high", [])
                    low_arr = mode_candles_data.get("low", [])
                    close_arr = mode_candles_data.get("close", [])
                    volume_arr = mode_candles_data.get("volume", [])
                    
                    candles = []
                    for i in range(len(ts_arr)):
                        try:
                            ts_str = ts_arr[i] if i < len(ts_arr) else ""
                            if ts_str:
                                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                                ts_ist = ts.astimezone(IST)
                            else:
                                continue
                        except (ValueError, TypeError):
                            continue
                        
                        if ts_ist.date() != today_ist:
                            continue
                        
                        time_minutes = ts_ist.hour * 60 + ts_ist.minute
                        if time_minutes < 555 or time_minutes > 930:
                            continue
                        
                        candles.append(Candle(
                            ts=ts_ist,
                            open=open_arr[i] if i < len(open_arr) else 0,
                            high=high_arr[i] if i < len(high_arr) else 0,
                            low=low_arr[i] if i < len(low_arr) else 0,
                            close=close_arr[i] if i < len(close_arr) else 0,
                            volume=volume_arr[i] if i < len(volume_arr) else 0,
                        ))
                    
                    if candles and not state_manager.get_candles(symbol):
                        # Only use mode-level candles if symbol-level wasn't found
                        state_manager.update_candles(symbol, candles)
                        state_manager.update_ltp(symbol, candles[-1].close, 0, 0)
                        print(f"[BOOTSTRAP] ✓ Legacy candles for {symbol}: {len(candles)} candles")


# =============================================================================
# Application Entry Point
# =============================================================================

def run_server(debug: bool = False, port: int = None) -> None:
    """Run the Dash server.
    
    Requirement 1.4: Dashboard runs on port 8509.
    
    Args:
        debug: Enable debug mode
        port: Port to run on (defaults to settings)
    """
    settings = get_settings()
    server_port = port or settings.dashboard_port
    
    app.run(
        debug=debug or settings.debug,
        port=server_port,
        host="0.0.0.0",
    )


if __name__ == "__main__":
    run_server(debug=True)
