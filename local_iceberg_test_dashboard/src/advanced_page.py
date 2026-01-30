# Iceberg Test Dashboard - Advanced Page
"""
Advanced page layout and callbacks for the Iceberg Test Dashboard.

Provides:
- ADR treemap visualization (Requirement 14.1)
- ADR movement line chart (ADR across the day)
- Symbol changer for advanced page

Requirements: 14.1, 14.2, 19.3
"""

import asyncio
import json
import time
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Tuple

from dash import html, dcc, callback, Input, Output, State, ctx
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import pytz

from .layouts import COLORS, create_card_style, create_card_header_style, create_professional_style
from .charts import create_adr_treemap, create_empty_chart
from .models import VALID_SYMBOLS
from .api_client import IcebergAPIClient, APIError, APIResponse
from .state_manager import StateManager

IST = pytz.timezone("Asia/Kolkata")


# =============================================================================
# Symbol Selector for Advanced Page
# =============================================================================

def create_advanced_symbol_selector(selected_symbol: str = "nifty") -> html.Div:
    """Create symbol selector dropdown for advanced page.
    
    Args:
        selected_symbol: Currently selected symbol
    
    Returns:
        Dash html.Div with symbol dropdown
    """
    return html.Div(
        [
            html.Label(
                "Select Symbol",
                style={
                    "fontSize": "12px",
                    "color": COLORS["text_secondary"],
                    "marginBottom": "5px",
                    "display": "block",
                }
            ),
            dcc.Dropdown(
                id="advanced-symbol-selector",
                options=[
                    {"label": s.upper(), "value": s} for s in VALID_SYMBOLS
                ],
                value=selected_symbol,
                clearable=False,
                style={
                    "width": "200px",
                }
            ),
        ],
        style={"marginBottom": "15px"}
    )


# =============================================================================
# ADR Treemap Section
# Requirement 14.1: Display ADR data as a treemap on the Advanced tab
# =============================================================================

def create_adr_treemap_section(symbol: str = "nifty") -> html.Div:
    """Create ADR treemap section.
    
    Requirement 14.1: Display ADR data as a treemap on the Advanced tab.
    
    Args:
        symbol: Index symbol for treemap
    
    Returns:
        Dash html.Div with treemap chart
    """
    return html.Div(
        [
            html.Div(
                [
                    html.Span(
                        f"ADR Treemap - {symbol.upper()} Constituents",
                        style={"fontWeight": "600"}
                    ),
                    html.Button(
                        "Refresh",
                        id="adr-refresh-btn",
                        style={
                            "marginLeft": "15px",
                            "padding": "4px 12px",
                            "fontSize": "12px",
                            "backgroundColor": COLORS["accent"],
                            "color": COLORS["text_light"],
                            "border": "none",
                            "borderRadius": "4px",
                            "cursor": "pointer",
                        }
                    ),
                ],
                style={
                    **create_card_header_style(),
                    "display": "flex",
                    "alignItems": "center",
                    "justifyContent": "space-between",
                }
            ),
            dcc.Loading(
                id="adr-loading",
                type="circle",
                children=[
                    dcc.Graph(
                        id="adr-treemap-chart",
                        figure=create_empty_chart("Click 'Refresh' to load ADR data"),
                        config={
                            "displayModeBar": False,
                            "displaylogo": False,
                        },
                        style={"height": "450px"},
                    ),
                ],
            ),
        ],
        id="adr-treemap-section",
        style=create_card_style(),
    )


# =============================================================================
# ADR Line Chart Section
# ADR movement across the day
# =============================================================================

def create_adr_line_chart(adr_history: List[Dict[str, Any]], symbol: str = "nifty") -> go.Figure:
    """Create ADR movement line chart.
    
    Args:
        adr_history: List of {timestamp, adr} dicts
        symbol: Symbol name for title
    
    Returns:
        Plotly figure with ADR line chart
    """
    if not adr_history:
        return create_empty_chart(f"No ADR history data for {symbol.upper()}")
    
    # Extract timestamps and ADR values
    timestamps = []
    adr_values = []
    
    for entry in adr_history:
        ts = entry.get("timestamp") or entry.get("ts")
        adr = entry.get("adr")
        if ts and adr is not None:
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                except:
                    continue
            timestamps.append(ts)
            adr_values.append(adr)
    
    if not timestamps:
        return create_empty_chart(f"No valid ADR history for {symbol.upper()}")
    
    # Create figure
    fig = go.Figure()
    
    # ADR line
    fig.add_trace(go.Scatter(
        x=timestamps,
        y=adr_values,
        mode='lines+markers',
        name='ADR',
        line=dict(color=COLORS["accent"], width=2),
        marker=dict(size=4),
        hovertemplate='%{x|%H:%M}<br>ADR: %{y:.2f}<extra></extra>',
    ))
    
    # Add reference line at ADR = 1.0 (neutral)
    fig.add_hline(
        y=1.0,
        line_dash="dash",
        line_color=COLORS["text_muted"],
        annotation_text="Neutral (1.0)",
        annotation_position="right",
    )
    
    # Layout
    fig.update_layout(
        title=dict(
            text=f"ADR Movement - {symbol.upper()}",
            font=dict(size=14, color=COLORS["text_primary"]),
        ),
        xaxis=dict(
            title="Time (IST)",
            showgrid=True,
            gridcolor=COLORS["content_bg"],
            tickformat="%H:%M",
        ),
        yaxis=dict(
            title="ADR Ratio",
            showgrid=True,
            gridcolor=COLORS["content_bg"],
        ),
        plot_bgcolor=COLORS["card_bg"],
        paper_bgcolor=COLORS["card_bg"],
        margin=dict(l=50, r=20, t=40, b=40),
        showlegend=False,
        hovermode="x unified",
    )
    
    return fig


def create_adr_line_chart_section(symbol: str = "nifty") -> html.Div:
    """Create ADR line chart section.
    
    Args:
        symbol: Index symbol for chart
    
    Returns:
        Dash html.Div with line chart
    """
    return html.Div(
        [
            html.Div(
                [
                    html.Span(
                        f"ADR Movement - {symbol.upper()}",
                        style={"fontWeight": "600"}
                    ),
                    html.Span(
                        "Advancing/Declining ratio across the trading day",
                        style={
                            "fontSize": "11px",
                            "color": COLORS["text_muted"],
                            "marginLeft": "10px",
                        }
                    ),
                ],
                style=create_card_header_style(),
            ),
            dcc.Loading(
                id="adr-line-loading",
                type="circle",
                children=[
                    dcc.Graph(
                        id="adr-line-chart",
                        figure=create_empty_chart("ADR history will load with treemap refresh"),
                        config={
                            "displayModeBar": False,
                            "displaylogo": False,
                        },
                        style={"height": "300px"},
                    ),
                ],
            ),
        ],
        id="adr-line-chart-section",
        style=create_card_style(),
    )


# =============================================================================
# Advanced Page Layout
# Requirement 19.3: Advanced page displays ADR treemap
# =============================================================================

def create_advanced_page_layout(
    state_manager: StateManager,
    selected_symbol: str = "nifty",
) -> html.Div:
    """Create the complete Advanced page layout.
    
    Requirement 19.3: Advanced page displays ADR treemap.
    
    Args:
        state_manager: StateManager instance
        selected_symbol: Currently selected symbol
    
    Returns:
        Dash html.Div with complete Advanced page
    """
    return html.Div(
        [
            # Page header
            html.Div(
                [
                    html.H4(
                        "📈 Advanced",
                        style={
                            "margin": "0",
                            "color": COLORS["text_primary"],
                        }
                    ),
                    html.Span(
                        "ADR Visualization & Analysis",
                        style={
                            "fontSize": "13px",
                            "color": COLORS["text_secondary"],
                            "marginLeft": "15px",
                        }
                    ),
                ],
                style={
                    "display": "flex",
                    "alignItems": "center",
                    "marginBottom": "20px",
                }
            ),
            
            # Symbol selector
            create_advanced_symbol_selector(selected_symbol),
            
            # Vertical layout - ADR Treemap on top, Line chart below
            html.Div(
                [
                    # ADR Treemap
                    create_adr_treemap_section(selected_symbol),
                    
                    # ADR Line Chart
                    create_adr_line_chart_section(selected_symbol),
                ],
                style={
                    "display": "flex",
                    "flexDirection": "column",
                    "gap": "20px",
                }
            ),
        ],
        id="advanced-page-content",
        style={
            "padding": "20px",
            "paddingBottom": "100px",  # Space for fixed symbol selector at bottom
            "maxWidth": "1200px",
            "margin": "0 auto",
        }
    )


# =============================================================================
# Helper Functions for API Calls
# =============================================================================

async def fetch_adr_constituents(
    symbol: str,
    api_client: IcebergAPIClient,
) -> List[Dict[str, Any]]:
    """Fetch ADR constituent data for treemap.
    
    Requirement 14.2: Fetch constituent data from GET /v1/dashboard/adr/constituents
    
    Args:
        symbol: Index symbol
        api_client: API client instance
    
    Returns:
        List of constituent dicts with symbol and change_pct
    """
    import structlog
    logger = structlog.get_logger(__name__)
    
    try:
        logger.info(
            "adr_fetch_starting",
            symbol=symbol,
            has_jwt=bool(api_client.jwt_token),
        )
        
        result = await api_client.adr_constituents(symbol=symbol)
        
        logger.info(
            "adr_fetch_raw_response",
            symbol=symbol,
            ok=result.ok,
            data_keys=list(result.data.keys()) if result.data else None,
        )
        
        if result.ok and result.data:
            constituents = result.data.get("constituents", [])
            logger.info(
                "adr_fetch_success",
                symbol=symbol,
                constituent_count=len(constituents),
            )
            return constituents
        
        logger.warning(
            "adr_fetch_failed",
            symbol=symbol,
            ok=result.ok,
            error=result.error,
        )
        return []
    except Exception as e:
        print(f"Error fetching ADR constituents: {e}")
        return []


async def fetch_adr_history(
    symbol: str,
    state_manager: StateManager,
) -> List[Dict[str, Any]]:
    """Fetch ADR history from state manager.
    
    ADR history is populated from bootstrap and accumulated from SSE indicator_update events.
    
    Args:
        symbol: Index symbol
        state_manager: StateManager instance with accumulated history
    
    Returns:
        List of {timestamp, adr} dicts
    """
    import structlog
    logger = structlog.get_logger(__name__)
    
    try:
        # Get ADR history from state manager (accumulated from bootstrap + SSE)
        adr_history = state_manager.get_adr_history(symbol)
        
        if adr_history:
            # Convert tuples to dicts for chart consumption
            return [
                {"timestamp": ts.isoformat(), "adr": adr}
                for ts, adr in adr_history
            ]
        
        # Fallback: try to get current ADR from indicators
        indicators = state_manager.get_indicators(symbol, "current")
        if indicators and indicators.adr is not None:
            return [{
                "timestamp": datetime.now(IST).isoformat(),
                "adr": indicators.adr,
            }]
        
        return []
    except Exception as e:
        logger.error("adr_history_fetch_error", error=str(e))
        return []
