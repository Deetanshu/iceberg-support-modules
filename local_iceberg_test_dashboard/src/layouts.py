# Iceberg Test Dashboard - Layout Components
"""
Layout components for the Iceberg Test Dashboard.

Provides professional light-mode styling with dark teal header/sidebar
and white content cards. Implements all UI components including:
- Symbol selector cards
- Indicators panel
- Option chain table
- Mode toggle
- Connection status indicators

Requirements: 2.1, 2.2, 2.6, 8.1-8.8, 9.1-9.7, 10.1-10.6, 13.1-13.5, 17.5
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
from dash import html, dcc, dash_table
import dash_bootstrap_components as dbc

from .models import (
    SymbolTick,
    IndicatorData,
    OptionChainData,
    OptionStrike,
    VALID_SYMBOLS,
    VALID_MODES,
)
from .state_manager import StateManager, ConnectionStatus, ErrorState, StalenessState
from .formatters import format_price, format_percentage, format_timestamp


# =============================================================================
# Color Palette - Professional Light Mode Theme
# Requirements 2.1, 2.2: Light mode with dark teal header/sidebar
# =============================================================================

COLORS = {
    # Primary colors
    "header_bg": "#2D4A5E",      # Dark teal for header and sidebar
    "sidebar_bg": "#2D4A5E",     # Dark teal for sidebar
    "content_bg": "#F5F5F5",     # Light gray for main content
    "card_bg": "#FFFFFF",        # White for cards
    
    # Text colors
    "text_primary": "#333333",   # Dark gray for main text
    "text_secondary": "#666666", # Medium gray for secondary text
    "text_light": "#FFFFFF",     # White text on dark backgrounds
    "text_muted": "#999999",     # Muted text
    
    # Accent colors
    "accent": "#4A90A4",         # Lighter teal accent
    "accent_hover": "#3D7A8C",   # Darker teal for hover
    
    # Status colors
    "positive": "#4CAF50",       # Green for gains/positive values
    "negative": "#F44336",       # Red for losses/negative values
    "neutral": "#9E9E9E",        # Gray for neutral
    "warning": "#FF9800",        # Orange for warnings
    
    # Option chain colors
    "call_oi_bg": "#E8F5E9",     # Light green for call OI
    "put_oi_bg": "#FFEBEE",      # Light red for put OI
    "atm_highlight": "#FFF9C4",  # Yellow for ATM strike
    
    # Chart colors (dark teal background)
    "chart_bg": "#2D4A5E",       # Dark teal for chart area
    "chart_grid": "#3D5A6E",     # Slightly lighter grid
    
    # Connection status
    "connected": "#4CAF50",      # Green for connected
    "disconnected": "#F44336",   # Red for disconnected
    "unknown": "#9E9E9E",        # Gray for unknown
}


# =============================================================================
# CSS Style Generators
# =============================================================================

def create_professional_style() -> Dict[str, Any]:
    """CSS for professional light-mode dashboard container.
    
    Requirement 2.1: Light mode design with light gray content background.
    Requirement 2.2: Clean sans-serif font.
    
    Returns:
        Dict of CSS properties for the main container
    """
    return {
        "backgroundColor": COLORS["content_bg"],
        "color": COLORS["text_primary"],
        "fontFamily": "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
        "minHeight": "100vh",
        "margin": "0",
        "padding": "0",
    }


def create_header_style() -> Dict[str, Any]:
    """CSS for dark teal header.
    
    Requirement 2.1: Dark teal (#2D4A5E) header.
    
    Returns:
        Dict of CSS properties for the header
    """
    return {
        "backgroundColor": COLORS["header_bg"],
        "color": COLORS["text_light"],
        "padding": "12px 20px",
        "display": "flex",
        "justifyContent": "space-between",
        "alignItems": "center",
        "boxShadow": "0 2px 4px rgba(0,0,0,0.1)",
        "position": "sticky",
        "top": "0",
        "zIndex": "1000",
    }


def create_sidebar_style() -> Dict[str, Any]:
    """CSS for dark teal sidebar.
    
    Requirement 2.1: Dark teal (#2D4A5E) sidebar.
    
    Returns:
        Dict of CSS properties for the sidebar
    """
    return {
        "backgroundColor": COLORS["sidebar_bg"],
        "color": COLORS["text_light"],
        "width": "220px",
        "minHeight": "calc(100vh - 56px)",
        "padding": "15px",
        "position": "fixed",
        "left": "0",
        "top": "56px",
    }


def create_card_style() -> Dict[str, Any]:
    """CSS for white content cards.
    
    Requirement 2.1: White card backgrounds with subtle shadows.
    
    Returns:
        Dict of CSS properties for cards
    """
    return {
        "backgroundColor": COLORS["card_bg"],
        "borderRadius": "8px",
        "boxShadow": "0 2px 4px rgba(0,0,0,0.08)",
        "padding": "15px",
        "marginBottom": "15px",
    }


def create_card_header_style() -> Dict[str, Any]:
    """CSS for card headers."""
    return {
        "fontSize": "14px",
        "fontWeight": "600",
        "color": COLORS["text_primary"],
        "marginBottom": "12px",
        "paddingBottom": "8px",
        "borderBottom": f"1px solid {COLORS['content_bg']}",
    }


# =============================================================================
# Sidebar Navigation Component
# =============================================================================

def create_sidebar_nav(current_page: str = "main") -> html.Div:
    """Create sidebar navigation component.
    
    Args:
        current_page: Currently active page
    
    Returns:
        Dash html.Div with sidebar navigation
    """
    pages = [
        {"id": "main", "label": "📊 Dashboard", "href": "/"},
        {"id": "advanced", "label": "📈 Advanced", "href": "/advanced"},
        {"id": "admin", "label": "⚙️ Admin", "href": "/admin"},
        {"id": "debugging", "label": "🔧 Debugging", "href": "/debugging"},
    ]
    
    nav_items = []
    for page in pages:
        is_active = page["id"] == current_page
        nav_items.append(
            dcc.Link(
                page["label"],
                href=page["href"],
                style={
                    "display": "block",
                    "padding": "12px 15px",
                    "marginBottom": "5px",
                    "borderRadius": "6px",
                    "textDecoration": "none",
                    "color": COLORS["text_light"],
                    "backgroundColor": COLORS["accent"] if is_active else "transparent",
                    "fontWeight": "500" if is_active else "normal",
                    "fontSize": "14px",
                    "transition": "all 0.2s ease",
                },
            )
        )
    
    return html.Div(
        [
            # Sidebar header
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
                            "fontSize": "18px",
                            "fontWeight": "bold",
                        }
                    ),
                ],
                style={
                    "display": "flex",
                    "alignItems": "center",
                    "marginBottom": "25px",
                    "paddingBottom": "15px",
                    "borderBottom": f"1px solid {COLORS['accent']}",
                }
            ),
            # Navigation items
            html.Nav(
                nav_items,
                style={"marginBottom": "20px"}
            ),
        ],
        id="sidebar-nav",
        style={
            "backgroundColor": COLORS["sidebar_bg"],
            "color": COLORS["text_light"],
            "width": "200px",
            "minHeight": "100vh",
            "padding": "20px 15px",
            "position": "fixed",
            "left": "0",
            "top": "0",
            "zIndex": "1001",
        }
    )


def create_nav_dropdown(current_page: str = "main") -> html.Div:
    """Create dropdown navigation component (alternative to sidebar).
    
    Args:
        current_page: Currently active page
    
    Returns:
        Dash html.Div with dropdown navigation
    """
    page_labels = {
        "main": "📊 Dashboard",
        "advanced": "📈 Advanced",
        "admin": "⚙️ Admin",
        "debugging": "🔧 Debugging",
    }
    
    return html.Div(
        [
            dcc.Dropdown(
                id="page-nav-dropdown",
                options=[
                    {"label": "📊 Dashboard", "value": "/"},
                    {"label": "📈 Advanced", "value": "/advanced"},
                    {"label": "⚙️ Admin", "value": "/admin"},
                    {"label": "🔧 Debugging", "value": "/debugging"},
                ],
                value=f"/{current_page}" if current_page != "main" else "/",
                clearable=False,
                style={
                    "width": "180px",
                    "fontSize": "13px",
                },
            ),
        ],
        style={"marginRight": "15px"}
    )


# =============================================================================
# Symbol Selector Component
# Requirements 10.1, 10.2, 10.3, 10.6, 2.7
# =============================================================================

def create_symbol_card(
    symbol: str,
    tick: Optional[SymbolTick],
    is_selected: bool = False,
) -> html.Div:
    """Create a single symbol card showing LTP and change.
    
    Requirements:
        10.1: Display symbol selector showing all 4 symbols
        10.2: Show current LTP for each symbol
        10.3: Show change percentage for each symbol
        10.6: Highlight currently selected symbol
        2.7: Teal background for selected, white for unselected
    
    Args:
        symbol: Trading symbol (lowercase)
        tick: SymbolTick with LTP data, or None
        is_selected: Whether this symbol is currently selected
    
    Returns:
        Dash html.Div component for the symbol card
    """
    # Format display values
    display_symbol = symbol.upper()
    ltp_text = format_price(tick.ltp) if tick else "--"
    
    if tick and tick.change_pct != 0:
        change_text = format_percentage(tick.change_pct)
        change_color = COLORS["positive"] if tick.change_pct > 0 else COLORS["negative"]
    else:
        change_text = "0.00%"
        change_color = COLORS["text_muted"]
    
    # Card styling based on selection state
    card_style = {
        "backgroundColor": COLORS["header_bg"] if is_selected else COLORS["card_bg"],
        "color": COLORS["text_light"] if is_selected else COLORS["text_primary"],
        "padding": "12px 24px",
        "borderRadius": "8px",
        "textAlign": "center",
        "cursor": "pointer",
        "border": f"2px solid {COLORS['header_bg']}" if is_selected else f"2px solid {COLORS['content_bg']}",
        "minWidth": "140px",
        "transition": "all 0.2s ease",
    }
    
    return html.Div(
        [
            html.Div(
                display_symbol,
                style={
                    "fontWeight": "bold",
                    "fontSize": "14px",
                    "marginBottom": "4px",
                }
            ),
            html.Div(
                ltp_text,
                style={
                    "fontSize": "18px",
                    "fontWeight": "600",
                }
            ),
            html.Div(
                change_text,
                style={
                    "fontSize": "12px",
                    "color": change_color if not is_selected else (
                        "#90EE90" if tick and tick.change_pct > 0 else 
                        "#FFB6C1" if tick and tick.change_pct < 0 else 
                        COLORS["text_light"]
                    ),
                }
            ),
        ],
        id={"type": "symbol-card", "symbol": symbol},
        n_clicks=0,  # Initialize n_clicks for callback to work
        style=card_style,
    )


def create_symbol_selector_bar(
    state: StateManager,
    selected_symbol: str = "nifty",
) -> html.Div:
    """Create horizontal symbol selector bar at bottom.
    
    Requirement 10.1: Display symbol selector showing all 4 symbols.
    Requirement 2.7: Horizontal cards at bottom.
    
    Args:
        state: StateManager with current LTP data
        selected_symbol: Currently selected symbol
    
    Returns:
        Dash html.Div component with all symbol cards
    """
    ltps = state.get_all_ltps()
    
    cards = []
    for symbol in VALID_SYMBOLS:
        tick = ltps.get(symbol)
        is_selected = symbol == selected_symbol.lower()
        cards.append(create_symbol_card(symbol, tick, is_selected))
    
    return html.Div(
        cards,
        id="symbol-selector-bar",
        style={
            "display": "flex",
            "justifyContent": "center",
            "gap": "15px",
            "padding": "15px 20px",
            "backgroundColor": COLORS["content_bg"],
            "borderTop": f"1px solid {COLORS['card_bg']}",
        }
    )



# =============================================================================
# Indicators Panel Component
# Requirements 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.8
# =============================================================================

def create_indicator_value(
    label: str,
    value: Optional[float],
    format_func: callable = None,
    color_func: callable = None,
) -> html.Div:
    """Create a single indicator value display.
    
    Args:
        label: Indicator label
        value: Indicator value (or None)
        format_func: Optional function to format the value
        color_func: Optional function to determine color based on value
    
    Returns:
        Dash html.Div component for the indicator
    """
    if value is None:
        display_value = "--"
        color = COLORS["text_muted"]
    else:
        display_value = format_func(value) if format_func else f"{value:.2f}"
        color = color_func(value) if color_func else COLORS["text_primary"]
    
    return html.Div(
        [
            html.Div(
                label,
                style={
                    "fontSize": "11px",
                    "color": COLORS["text_secondary"],
                    "textTransform": "uppercase",
                    "letterSpacing": "0.5px",
                }
            ),
            html.Div(
                display_value,
                style={
                    "fontSize": "16px",
                    "fontWeight": "600",
                    "color": color,
                }
            ),
        ],
        style={
            "textAlign": "center",
            "padding": "8px 12px",
        }
    )


def get_skew_color(value: float) -> str:
    """Get color for skew value (green positive, red negative).
    
    Requirement 8.1: Color-code Skew (green positive, red negative).
    """
    if value > 0:
        return COLORS["positive"]
    elif value < 0:
        return COLORS["negative"]
    return COLORS["text_primary"]


def get_rsi_color(value: float) -> str:
    """Get color for RSI value (highlight overbought/oversold).
    
    Requirement 8.6: Highlight RSI overbought/oversold.
    """
    if value >= 70:
        return COLORS["negative"]  # Overbought
    elif value <= 30:
        return COLORS["positive"]  # Oversold
    return COLORS["text_primary"]


def get_signal_color(signal: str) -> str:
    """Get color for trading signal."""
    if signal in ["STRONG_BUY", "BUY"]:
        return COLORS["positive"]
    elif signal in ["STRONG_SELL", "SELL"]:
        return COLORS["negative"]
    return COLORS["text_secondary"]


def create_indicators_panel(
    indicators: Optional[IndicatorData],
    last_update: Optional[datetime] = None,
) -> html.Div:
    """Create indicators panel displaying all computed metrics.
    
    Requirements:
        8.1: Display current Skew value with color coding
        8.2: Display current PCR value
        8.3: Display Signal value
        8.4: Display Skew Confidence value
        8.5: Display ADR value
        8.6: Display RSI value with overbought/oversold highlighting
        8.8: Show timestamp of last indicator update
    
    Args:
        indicators: IndicatorData object with current values
        last_update: Timestamp of last update
    
    Returns:
        Dash html.Div component for the indicators panel
    """
    if indicators is None:
        indicators = IndicatorData()
    
    # Format functions
    def format_skew(v): return f"{v:+.3f}"
    def format_pcr(v): return f"{v:.2f}"
    def format_pct(v): return f"{v:.1f}%"
    def format_rsi(v): return f"{v:.1f}"
    def format_coi(v): return f"{v/1000:+,.0f}K" if abs(v) >= 1000 else f"{v:+,.0f}"
    
    # Create indicator grid
    indicator_items = [
        create_indicator_value("Skew", indicators.skew, format_skew, get_skew_color),
        create_indicator_value("PCR", indicators.pcr, format_pcr),
        create_indicator_value(
            "Signal", 
            None,  # Signal is a string, handle specially
        ),
        create_indicator_value("Confidence", indicators.skew_confidence, format_pct),
        create_indicator_value("ADR", indicators.adr, format_pcr),
        create_indicator_value("RSI", indicators.rsi, format_rsi, get_rsi_color),
        create_indicator_value("Call COI", indicators.call_coi_sum, format_coi, lambda v: COLORS["positive"] if v and v > 0 else COLORS["negative"]),
        create_indicator_value("Put COI", indicators.put_coi_sum, format_coi, lambda v: COLORS["negative"] if v and v > 0 else COLORS["positive"]),
    ]
    
    # Replace Signal indicator with custom display
    signal_display = html.Div(
        [
            html.Div(
                "Signal",
                style={
                    "fontSize": "11px",
                    "color": COLORS["text_secondary"],
                    "textTransform": "uppercase",
                    "letterSpacing": "0.5px",
                }
            ),
            html.Div(
                indicators.signal,
                style={
                    "fontSize": "14px",
                    "fontWeight": "600",
                    "color": get_signal_color(indicators.signal),
                }
            ),
        ],
        style={
            "textAlign": "center",
            "padding": "8px 12px",
        }
    )
    indicator_items[2] = signal_display
    
    # Last update timestamp
    update_text = format_timestamp(last_update) if last_update else "--"
    
    # Intuition text section (AI-generated insight)
    # FIX-042: Added confidence and recommendations display
    intuition_section = None
    if indicators.intuition_text:
        # Build recommendations display if available
        recommendations_display = None
        if indicators.intuition_recommendations:
            rec_items = []
            for risk_level, strike in indicators.intuition_recommendations.items():
                risk_label = risk_level.replace("_", " ").title()
                rec_items.append(
                    html.Span(
                        [
                            html.Span(
                                f"{risk_label}: ",
                                style={
                                    "color": COLORS["text_secondary"],
                                    "fontSize": "11px",
                                }
                            ),
                            html.Span(
                                strike,
                                style={
                                    "color": COLORS["accent"],
                                    "fontWeight": "600",
                                    "fontSize": "12px",
                                }
                            ),
                        ],
                        style={"marginRight": "15px"}
                    )
                )
            if rec_items:
                recommendations_display = html.Div(
                    [
                        html.Div(
                            "Suggested Strikes",
                            style={
                                "fontSize": "10px",
                                "color": COLORS["text_muted"],
                                "marginBottom": "3px",
                            }
                        ),
                        html.Div(rec_items),
                    ],
                    style={
                        "marginTop": "8px",
                        "padding": "6px 8px",
                        "backgroundColor": COLORS["content_bg"],
                        "borderRadius": "4px",
                    }
                )
        
        # Build confidence badge if available
        confidence_badge = None
        if indicators.intuition_confidence is not None:
            conf_pct = int(indicators.intuition_confidence * 100)
            conf_color = COLORS["positive"] if conf_pct >= 70 else (
                COLORS["warning"] if conf_pct >= 50 else COLORS["text_muted"]
            )
            confidence_badge = html.Span(
                f"{conf_pct}%",
                style={
                    "fontSize": "10px",
                    "color": conf_color,
                    "marginLeft": "8px",
                    "padding": "2px 6px",
                    "backgroundColor": COLORS["content_bg"],
                    "borderRadius": "10px",
                }
            )
        
        intuition_section = html.Div(
            [
                html.Div(
                    [
                        html.Span(
                            "AI Insight",
                            style={
                                "fontSize": "11px",
                                "color": COLORS["text_secondary"],
                                "textTransform": "uppercase",
                                "letterSpacing": "0.5px",
                            }
                        ),
                        confidence_badge if confidence_badge else html.Span(),
                    ],
                    style={"marginBottom": "5px"}
                ),
                html.Div(
                    indicators.intuition_text,
                    style={
                        "fontSize": "12px",
                        "color": COLORS["text_primary"],
                        "lineHeight": "1.4",
                        "padding": "8px",
                        "backgroundColor": COLORS["card_bg"],
                        "borderRadius": "4px",
                        "borderLeft": f"3px solid {COLORS['header_bg']}",
                    }
                ),
                recommendations_display if recommendations_display else html.Div(),
            ],
            style={"marginTop": "10px"}
        )
    
    return html.Div(
        [
            html.Div("Indicators", style=create_card_header_style()),
            html.Div(
                indicator_items,
                style={
                    "display": "grid",
                    "gridTemplateColumns": "repeat(3, 1fr)",
                    "gap": "5px",
                }
            ),
            intuition_section if intuition_section else html.Div(),
            html.Div(
                f"Last update: {update_text}",
                style={
                    "fontSize": "10px",
                    "color": COLORS["text_muted"],
                    "textAlign": "right",
                    "marginTop": "10px",
                }
            ),
        ],
        id="indicators-panel",
        style=create_card_style(),
    )


# =============================================================================
# Option Chain Table Component
# Requirements 9.1, 9.2, 9.3, 9.6, 9.7, 2.6
# =============================================================================

def create_option_chain_table(
    option_chain: Optional[OptionChainData],
    underlying_price: Optional[float] = None,
) -> html.Div:
    """Create option chain table with color-coded cells.
    
    Requirements:
        9.1: Display option chain as a table with strikes as rows
        9.2: Show columns: Strike, Call_OI, Put_OI, Strike_Skew
        9.3: Highlight ATM strike row
        9.6: Color-code Strike_Skew (green positive, red negative)
        9.7: Show expiry date in the header
        2.6: Green shades for Call OI, red shades for Put OI, yellow for ATM
    
    Args:
        option_chain: OptionChainData object with strikes
        underlying_price: Current underlying price for ATM detection
    
    Returns:
        Dash html.Div component with the option chain table
    """
    # Header with expiry date
    expiry_text = option_chain.expiry if option_chain else "--"
    
    if not option_chain or not option_chain.strikes:
        return html.Div(
            [
                html.Div(
                    f"Option Chain (Expiry: {expiry_text})",
                    style=create_card_header_style()
                ),
                html.Div(
                    "No option chain data available",
                    style={
                        "textAlign": "center",
                        "color": COLORS["text_muted"],
                        "padding": "20px",
                    }
                ),
            ],
            id="option-chain-container",
            style=create_card_style(),
        )
    
    # Determine ATM strike
    atm_strike = None
    if underlying_price and option_chain.strikes:
        strikes = [s.strike for s in option_chain.strikes]
        atm_strike = min(strikes, key=lambda x: abs(x - underlying_price))
    
    # Prepare table data
    table_data = []
    for strike in option_chain.strikes:
        is_atm = strike.strike == atm_strike if atm_strike else False
        table_data.append({
            "call_oi": f"{strike.call_oi:,}" if strike.call_oi else "--",
            "strike": f"{strike.strike:.0f}",
            "strike_skew": f"{strike.strike_skew:+.3f}" if strike.strike_skew is not None else "--",
            "put_oi": f"{strike.put_oi:,}" if strike.put_oi else "--",
            "is_atm": is_atm,
            "skew_value": strike.strike_skew if strike.strike_skew is not None else 0,
            "signal": strike.signal or "NEUTRAL",
        })
    
    # Create DataTable with conditional styling
    table = dash_table.DataTable(
        id="option-chain-table",
        columns=[
            {"name": "Call OI", "id": "call_oi"},
            {"name": "Strike", "id": "strike"},
            {"name": "Skew", "id": "strike_skew"},
            {"name": "Put OI", "id": "put_oi"},
        ],
        data=table_data,
        style_header={
            "backgroundColor": COLORS["header_bg"],
            "color": COLORS["text_light"],
            "fontWeight": "bold",
            "textAlign": "center",
            "padding": "10px",
            "fontSize": "12px",
        },
        style_cell={
            "textAlign": "center",
            "padding": "8px 10px",
            "fontSize": "12px",
            "border": "none",
            "borderBottom": f"1px solid {COLORS['content_bg']}",
        },
        style_data={
            "backgroundColor": COLORS["card_bg"],
            "color": COLORS["text_primary"],
        },
        style_data_conditional=[
            # Signal-based row coloring for strike column
            # STRONG_BUY - dark green background
            {
                "if": {
                    "filter_query": '{signal} eq "STRONG_BUY"',
                    "column_id": "strike",
                },
                "backgroundColor": "rgba(76, 175, 80, 0.4)",
                "color": COLORS["text_light"],
                "fontWeight": "bold",
            },
            # BUY - light green background
            {
                "if": {
                    "filter_query": '{signal} eq "BUY"',
                    "column_id": "strike",
                },
                "backgroundColor": "rgba(76, 175, 80, 0.2)",
                "fontWeight": "600",
            },
            # STRONG_SELL - dark red background
            {
                "if": {
                    "filter_query": '{signal} eq "STRONG_SELL"',
                    "column_id": "strike",
                },
                "backgroundColor": "rgba(244, 67, 54, 0.4)",
                "color": COLORS["text_light"],
                "fontWeight": "bold",
            },
            # SELL - light red background
            {
                "if": {
                    "filter_query": '{signal} eq "SELL"',
                    "column_id": "strike",
                },
                "backgroundColor": "rgba(244, 67, 54, 0.2)",
                "fontWeight": "600",
            },
            # NEUTRAL - gray background (subtle)
            {
                "if": {
                    "filter_query": '{signal} eq "NEUTRAL"',
                    "column_id": "strike",
                },
                "backgroundColor": "rgba(158, 158, 158, 0.1)",
            },
            # Green background for Call OI column (Requirement 2.6)
            {
                "if": {"column_id": "call_oi"},
                "backgroundColor": COLORS["call_oi_bg"],
            },
            # Red background for Put OI column (Requirement 2.6)
            {
                "if": {"column_id": "put_oi"},
                "backgroundColor": COLORS["put_oi_bg"],
            },
            # Yellow highlight for ATM strike row (Requirement 9.3, 2.6)
            {
                "if": {
                    "filter_query": "{is_atm} eq true",
                },
                "backgroundColor": COLORS["atm_highlight"],
                "fontWeight": "bold",
            },
            # Green text for positive skew (Requirement 9.6)
            {
                "if": {
                    "filter_query": "{skew_value} > 0",
                    "column_id": "strike_skew",
                },
                "color": COLORS["positive"],
                "fontWeight": "600",
            },
            # Red text for negative skew (Requirement 9.6)
            {
                "if": {
                    "filter_query": "{skew_value} < 0",
                    "column_id": "strike_skew",
                },
                "color": COLORS["negative"],
                "fontWeight": "600",
            },
        ],
        style_table={
            "overflowY": "auto",
            "maxHeight": "400px",
        },
        fixed_rows={"headers": True},
    )
    
    return html.Div(
        [
            html.Div(
                f"Option Chain (Expiry: {expiry_text})",
                style=create_card_header_style()
            ),
            table,
        ],
        id="option-chain-container",
        style=create_card_style(),
    )



# =============================================================================
# Mode Toggle Component
# Requirements 13.1, 13.2, 13.5
# =============================================================================

def create_mode_toggle(
    current_mode: str = "current",
    expiry_date: Optional[str] = None,
) -> html.Div:
    """Create tab-style toggle for mode selection.
    
    Requirements:
        13.1: Provide mode toggle in the sidebar
        13.2: Show "Current" (weekly) and "Positional" (monthly) options
        13.5: Display current mode's expiry date prominently
    
    Note: The design mentions "Indicator/Positional/Historical" tabs,
    but requirements specify "current" and "positional" modes.
    We implement both current/positional as the core modes.
    
    Args:
        current_mode: Currently selected mode ('current' or 'positional')
        expiry_date: Expiry date string for display
    
    Returns:
        Dash html.Div component with mode toggle tabs
    """
    modes = [
        {"id": "current", "label": "Indicator", "description": "Weekly Expiry"},
        {"id": "positional", "label": "Positional", "description": "Monthly Expiry"},
    ]
    
    tabs = []
    for mode in modes:
        is_active = mode["id"] == current_mode.lower()
        tab_style = {
            "padding": "10px 20px",
            "cursor": "pointer",
            "borderRadius": "4px 4px 0 0",
            "backgroundColor": COLORS["card_bg"] if is_active else "transparent",
            "color": COLORS["text_primary"] if is_active else COLORS["text_light"],
            "fontWeight": "600" if is_active else "normal",
            "fontSize": "13px",
            "border": "none",
            "borderBottom": f"2px solid {COLORS['accent']}" if is_active else "none",
            "transition": "all 0.2s ease",
        }
        
        tabs.append(
            html.Div(
                mode["label"],
                id={"type": "mode-tab", "mode": mode["id"]},
                style=tab_style,
                n_clicks=0,
            )
        )
    
    # Expiry date display
    expiry_display = html.Div(
        f"Expiry: {expiry_date}" if expiry_date else "Expiry: --",
        style={
            "fontSize": "11px",
            "color": COLORS["text_muted"],
            "marginTop": "5px",
        }
    )
    
    return html.Div(
        [
            html.Div(
                tabs,
                style={
                    "display": "flex",
                    "gap": "5px",
                }
            ),
            expiry_display,
        ],
        id="mode-toggle",
        style={
            "marginBottom": "15px",
        }
    )


def create_mode_tabs_header(
    current_mode: str = "current",
) -> html.Div:
    """Create mode tabs for the header area.
    
    This is an alternative placement for mode toggle in the header.
    
    Args:
        current_mode: Currently selected mode
    
    Returns:
        Dash html.Div component with mode tabs
    """
    modes = [
        {"id": "current", "label": "Intraday"},
        {"id": "positional", "label": "Positional"},
        {"id": "historical", "label": "Historical"},
    ]
    
    tabs = []
    for mode in modes:
        is_active = mode["id"] == current_mode.lower()
        tab_style = {
            "padding": "8px 16px",
            "cursor": "pointer",
            "borderRadius": "4px",
            "backgroundColor": COLORS["accent"] if is_active else "transparent",
            "color": COLORS["text_light"],
            "fontWeight": "500",
            "fontSize": "13px",
            "border": "none",
            "transition": "all 0.2s ease",
        }
        
        tabs.append(
            html.Div(
                mode["label"],
                id={"type": "header-mode-tab", "mode": mode["id"]},
                style=tab_style,
                n_clicks=0,
            )
        )
    
    return html.Div(
        tabs,
        style={
            "display": "flex",
            "gap": "8px",
            "backgroundColor": "rgba(255,255,255,0.1)",
            "padding": "4px",
            "borderRadius": "6px",
        }
    )


def create_historical_controls(
    selected_symbol: str = "nifty",
    selected_date: str = None,
) -> html.Div:
    """Create historical mode controls (date picker + symbol selector).
    
    These controls are shown only when Historical mode is active.
    
    Args:
        selected_symbol: Currently selected symbol
        selected_date: Currently selected date (YYYY-MM-DD format)
    
    Returns:
        Dash html.Div with historical controls
    """
    from datetime import date
    from .models import VALID_SYMBOLS
    
    if selected_date is None:
        selected_date = date.today().isoformat()
    
    return html.Div(
        [
            # Symbol selector
            html.Div(
                [
                    html.Label(
                        "Symbol",
                        style={
                            "fontSize": "11px",
                            "color": COLORS["text_light"],
                            "marginBottom": "3px",
                            "display": "block",
                        }
                    ),
                    dcc.Dropdown(
                        id="historical-symbol-picker",
                        options=[
                            {"label": s.upper(), "value": s} for s in VALID_SYMBOLS
                        ],
                        value=selected_symbol,
                        clearable=False,
                        style={
                            "width": "120px",
                            "fontSize": "12px",
                        },
                    ),
                ],
            ),
            # Date picker
            html.Div(
                [
                    html.Label(
                        "Date",
                        style={
                            "fontSize": "11px",
                            "color": COLORS["text_light"],
                            "marginBottom": "3px",
                            "display": "block",
                        }
                    ),
                    dcc.DatePickerSingle(
                        id="historical-date-picker",
                        date=selected_date,
                        display_format="YYYY-MM-DD",
                        style={
                            "fontSize": "12px",
                        },
                    ),
                ],
            ),
            # Fetch button
            html.Button(
                "Load Historical",
                id="historical-fetch-btn",
                style={
                    "padding": "6px 12px",
                    "fontSize": "12px",
                    "backgroundColor": COLORS["accent"],
                    "color": COLORS["text_light"],
                    "border": "none",
                    "borderRadius": "4px",
                    "cursor": "pointer",
                    "marginTop": "18px",
                },
                n_clicks=0,
            ),
        ],
        id="historical-controls",
        style={
            "display": "none",  # Hidden by default, shown when historical mode active
            "gap": "10px",
            "alignItems": "flex-start",
            "marginLeft": "15px",
        }
    )


# =============================================================================
# Market Status Banner Component
# Requirements 16.1, 16.2, 16.3, 16.4, 16.5
# =============================================================================

def get_market_state_color(state: str) -> str:
    """Get color for market state display.
    
    Args:
        state: Market state (OPEN, CLOSED, UNKNOWN)
    
    Returns:
        Color string for the state
    """
    if state == "OPEN":
        return COLORS["positive"]
    elif state == "CLOSED":
        return COLORS["negative"]
    return COLORS["text_muted"]


def get_market_state_icon(state: str) -> str:
    """Get icon for market state display.
    
    Args:
        state: Market state (OPEN, CLOSED, UNKNOWN)
    
    Returns:
        Icon string for the state
    """
    if state == "OPEN":
        return "🟢"
    elif state == "CLOSED":
        return "🔴"
    return "⚪"


def create_market_status_banner(
    market_state: str = "UNKNOWN",
    show_banner: bool = True,
) -> html.Div:
    """Create market status banner component.
    
    Requirements:
        16.1: Display market state (OPEN, CLOSED, UNKNOWN) from bootstrap meta
        16.2: WHEN market is CLOSED, display a prominent banner
        16.3: Show market hours as 09:15-15:30 IST
        16.4: WHEN market_closed SSE event is received, update market state to CLOSED
        16.5: Continue displaying last known data when market is closed
    
    Args:
        market_state: Current market state (OPEN, CLOSED, UNKNOWN)
        show_banner: Whether to show the banner (always show for CLOSED)
    
    Returns:
        Dash html.Div component for the market status banner
    """
    state_color = get_market_state_color(market_state)
    state_icon = get_market_state_icon(market_state)
    
    # Determine banner visibility and styling based on market state
    # Requirement 16.2: Prominent banner when market is CLOSED
    if market_state == "CLOSED":
        banner_style = {
            "backgroundColor": f"{COLORS['negative']}15",
            "border": f"1px solid {COLORS['negative']}",
            "borderRadius": "6px",
            "padding": "12px 20px",
            "marginBottom": "15px",
            "display": "flex",
            "justifyContent": "space-between",
            "alignItems": "center",
        }
        banner_text = "Market is currently CLOSED"
        show_last_data_note = True
    elif market_state == "OPEN":
        banner_style = {
            "backgroundColor": f"{COLORS['positive']}10",
            "border": f"1px solid {COLORS['positive']}40",
            "borderRadius": "6px",
            "padding": "8px 20px",
            "marginBottom": "15px",
            "display": "flex",
            "justifyContent": "space-between",
            "alignItems": "center",
        }
        banner_text = "Market is OPEN"
        show_last_data_note = False
    else:
        # UNKNOWN state - subtle display
        banner_style = {
            "backgroundColor": f"{COLORS['text_muted']}10",
            "border": f"1px solid {COLORS['text_muted']}40",
            "borderRadius": "6px",
            "padding": "8px 20px",
            "marginBottom": "15px",
            "display": "flex",
            "justifyContent": "space-between",
            "alignItems": "center",
        }
        banner_text = "Market status unknown"
        show_last_data_note = False
    
    # Build banner content
    left_content = html.Div(
        [
            html.Span(
                state_icon,
                style={
                    "marginRight": "10px",
                    "fontSize": "14px",
                }
            ),
            html.Span(
                banner_text,
                style={
                    "fontWeight": "600",
                    "color": state_color,
                    "fontSize": "14px",
                }
            ),
            # Requirement 16.5: Note about last known data when closed
            html.Span(
                " — Displaying last known data",
                style={
                    "color": COLORS["text_secondary"],
                    "fontSize": "12px",
                    "marginLeft": "10px",
                }
            ) if show_last_data_note else None,
        ],
        style={"display": "flex", "alignItems": "center"}
    )
    
    # Requirement 16.3: Show market hours as 09:15-15:30 IST
    right_content = html.Div(
        [
            html.Span(
                "Market Hours: ",
                style={
                    "color": COLORS["text_secondary"],
                    "fontSize": "12px",
                }
            ),
            html.Span(
                "09:15 - 15:30 IST",
                style={
                    "color": COLORS["text_primary"],
                    "fontSize": "12px",
                    "fontWeight": "500",
                }
            ),
        ],
        style={"display": "flex", "alignItems": "center"}
    )
    
    return html.Div(
        [left_content, right_content],
        id="market-status-banner",
        style=banner_style,
    )


# =============================================================================
# Connection Status Indicators
# Requirement 17.5
# =============================================================================


# =============================================================================
# Error Display Component
# Requirements 17.1, 5.6
# =============================================================================

def get_error_type_icon(error_type: str) -> str:
    """Get icon for error type display.
    
    Args:
        error_type: Type of error ('bootstrap', 'api', 'websocket', 'sse', 'general')
    
    Returns:
        Icon string for the error type
    """
    icons = {
        "bootstrap": "🔄",
        "api": "🌐",
        "websocket": "📡",
        "sse": "📶",
        "general": "⚠️",
    }
    return icons.get(error_type, "⚠️")


def get_error_type_label(error_type: str) -> str:
    """Get human-readable label for error type.
    
    Args:
        error_type: Type of error
    
    Returns:
        Human-readable label
    """
    labels = {
        "bootstrap": "Bootstrap Error",
        "api": "API Error",
        "websocket": "WebSocket Error",
        "sse": "SSE Stream Error",
        "general": "Error",
    }
    return labels.get(error_type, "Error")


def create_error_display(
    error_state: ErrorState,
    show_retry: bool = True,
) -> html.Div:
    """Create error display component.
    
    Requirements:
        17.1: WHEN an API call fails, THE Dashboard SHALL display the error message without crashing
        5.6: IF bootstrap fails, THEN THE Dashboard SHALL display error and allow retry
    
    Args:
        error_state: ErrorState object with current error information
        show_retry: Whether to show the retry button
    
    Returns:
        Dash html.Div component for error display, or empty div if no error
    """
    # Return empty div if no error
    if not error_state or not error_state.has_error:
        return html.Div(id="error-display-container", style={"display": "none"})
    
    error_icon = get_error_type_icon(error_state.error_type)
    error_label = get_error_type_label(error_state.error_type)
    
    # Determine if retry is available
    can_retry = (
        show_retry 
        and error_state.can_retry 
        and error_state.retry_count < error_state.max_retries
    )
    
    # Build retry info text
    retry_info = ""
    if error_state.retry_count > 0:
        retry_info = f" (Attempt {error_state.retry_count}/{error_state.max_retries})"
    
    # Format timestamp if available
    timestamp_text = ""
    if error_state.error_timestamp:
        timestamp_text = error_state.error_timestamp.strftime("%H:%M:%S IST")
    
    # Build error content
    error_content = [
        # Error header with icon and type
        html.Div(
            [
                html.Span(
                    error_icon,
                    style={
                        "fontSize": "18px",
                        "marginRight": "10px",
                    }
                ),
                html.Span(
                    f"{error_label}{retry_info}",
                    style={
                        "fontWeight": "600",
                        "fontSize": "14px",
                        "color": COLORS["negative"],
                    }
                ),
                # Timestamp on the right
                html.Span(
                    timestamp_text,
                    style={
                        "fontSize": "11px",
                        "color": COLORS["text_muted"],
                        "marginLeft": "auto",
                    }
                ) if timestamp_text else None,
            ],
            style={
                "display": "flex",
                "alignItems": "center",
                "marginBottom": "8px",
            }
        ),
        
        # Error message
        html.Div(
            error_state.error_message or "An unexpected error occurred.",
            style={
                "fontSize": "13px",
                "color": COLORS["text_primary"],
                "lineHeight": "1.4",
                "marginBottom": "12px",
            }
        ),
        
        # Action buttons row
        html.Div(
            [
                # Retry button (Requirement 5.6: allow retry)
                html.Button(
                    "🔄 Retry",
                    id="error-retry-btn",
                    n_clicks=0,
                    style={
                        "backgroundColor": COLORS["accent"],
                        "color": COLORS["text_light"],
                        "border": "none",
                        "borderRadius": "4px",
                        "padding": "6px 16px",
                        "cursor": "pointer",
                        "fontSize": "12px",
                        "fontWeight": "500",
                        "marginRight": "10px",
                    }
                ) if can_retry else None,
                
                # Dismiss button
                html.Button(
                    "✕ Dismiss",
                    id="error-dismiss-btn",
                    n_clicks=0,
                    style={
                        "backgroundColor": "transparent",
                        "color": COLORS["text_secondary"],
                        "border": f"1px solid {COLORS['text_muted']}",
                        "borderRadius": "4px",
                        "padding": "6px 16px",
                        "cursor": "pointer",
                        "fontSize": "12px",
                    }
                ),
                
                # Max retries reached message
                html.Span(
                    "Maximum retry attempts reached. Please refresh the page.",
                    style={
                        "fontSize": "11px",
                        "color": COLORS["text_muted"],
                        "marginLeft": "10px",
                    }
                ) if (error_state.retry_count >= error_state.max_retries and show_retry) else None,
            ],
            style={
                "display": "flex",
                "alignItems": "center",
            }
        ),
    ]
    
    # Error container styling
    container_style = {
        "backgroundColor": f"{COLORS['negative']}10",
        "border": f"1px solid {COLORS['negative']}40",
        "borderRadius": "8px",
        "padding": "15px 20px",
        "marginBottom": "15px",
    }
    
    return html.Div(
        error_content,
        id="error-display-container",
        style=container_style,
    )


def create_error_banner(
    message: str,
    error_type: str = "general",
    dismissible: bool = True,
) -> html.Div:
    """Create a simple error banner for inline display.
    
    Requirement 17.1: Display error message without crashing.
    
    Args:
        message: Error message to display
        error_type: Type of error for icon selection
        dismissible: Whether the banner can be dismissed
    
    Returns:
        Dash html.Div component for the error banner
    """
    error_icon = get_error_type_icon(error_type)
    
    return html.Div(
        [
            html.Span(
                error_icon,
                style={
                    "marginRight": "8px",
                    "fontSize": "14px",
                }
            ),
            html.Span(
                message,
                style={
                    "flex": "1",
                    "fontSize": "13px",
                }
            ),
            html.Button(
                "✕",
                id="error-banner-dismiss",
                n_clicks=0,
                style={
                    "backgroundColor": "transparent",
                    "border": "none",
                    "color": COLORS["negative"],
                    "cursor": "pointer",
                    "fontSize": "16px",
                    "padding": "0 5px",
                }
            ) if dismissible else None,
        ],
        style={
            "display": "flex",
            "alignItems": "center",
            "backgroundColor": f"{COLORS['negative']}15",
            "border": f"1px solid {COLORS['negative']}",
            "borderRadius": "6px",
            "padding": "10px 15px",
            "marginBottom": "10px",
            "color": COLORS["negative"],
        }
    )


def create_connection_status_indicator(
    label: str,
    is_connected: bool,
    last_update: Optional[datetime] = None,
) -> html.Div:
    """Create a single connection status indicator.
    
    Args:
        label: Connection type label (e.g., "WebSocket", "SSE")
        is_connected: Whether the connection is active
        last_update: Timestamp of last update
    
    Returns:
        Dash html.Div component for the status indicator
    """
    status_color = COLORS["connected"] if is_connected else COLORS["disconnected"]
    status_text = "Connected" if is_connected else "Disconnected"
    
    update_text = ""
    if last_update:
        update_text = format_timestamp(last_update)
    
    return html.Div(
        [
            html.Div(
                [
                    html.Span(
                        "●",
                        style={
                            "color": status_color,
                            "marginRight": "6px",
                            "fontSize": "10px",
                        }
                    ),
                    html.Span(
                        label,
                        style={
                            "fontSize": "12px",
                            "fontWeight": "500",
                        }
                    ),
                ],
                style={"display": "flex", "alignItems": "center"}
            ),
            html.Div(
                update_text,
                style={
                    "fontSize": "10px",
                    "color": COLORS["text_muted"],
                    "marginLeft": "16px",
                }
            ) if update_text else None,
        ],
        style={
            "marginBottom": "8px",
        }
    )


# =============================================================================
# Staleness Warning Component
# Requirements 5.7, 17.6
# =============================================================================

def create_staleness_warning(
    show_warning: bool,
    cache_stale: bool = False,
    data_age_seconds: Optional[int] = None,
    last_update: Optional[datetime] = None,
) -> html.Div:
    """Create staleness warning banner component.
    
    Requirements:
        5.7: THE Dashboard SHALL display cache_stale warning from meta.cache_stale if true
        17.6: IF data is stale (>5 minutes old), THEN THE Dashboard SHALL display a staleness warning
    
    Args:
        show_warning: Whether to show the warning banner
        cache_stale: Whether cache_stale flag is set from bootstrap (Requirement 5.7)
        data_age_seconds: Age of data in seconds (for Requirement 17.6)
        last_update: Timestamp of last data update
    
    Returns:
        Dash html.Div component for the staleness warning, or empty div if no warning
    """
    # Return empty div if no warning needed
    if not show_warning:
        return html.Div(id="staleness-warning-container", style={"display": "none"})
    
    # Determine warning message based on staleness type
    warning_messages = []
    
    # Requirement 5.7: cache_stale warning from bootstrap
    if cache_stale:
        warning_messages.append("Cache data is stale from server")
    
    # Requirement 17.6: Data age > 5 minutes
    if data_age_seconds is not None and data_age_seconds > 300:
        minutes = data_age_seconds // 60
        seconds = data_age_seconds % 60
        if minutes >= 60:
            hours = minutes // 60
            minutes = minutes % 60
            age_text = f"{hours}h {minutes}m"
        elif seconds > 0:
            age_text = f"{minutes}m {seconds}s"
        else:
            age_text = f"{minutes}m"
        warning_messages.append(f"Data is {age_text} old")
    
    # Combine messages
    if not warning_messages:
        warning_messages.append("Data may be outdated")
    
    main_message = " • ".join(warning_messages)
    
    # Format last update time
    update_text = ""
    if last_update:
        update_text = format_timestamp(last_update)
    
    # Build warning content
    warning_content = [
        # Warning icon and message
        html.Div(
            [
                html.Span(
                    "⚠️",
                    style={
                        "fontSize": "16px",
                        "marginRight": "10px",
                    }
                ),
                html.Span(
                    "Stale Data Warning",
                    style={
                        "fontWeight": "600",
                        "fontSize": "13px",
                        "color": COLORS["warning"],
                        "marginRight": "10px",
                    }
                ),
                html.Span(
                    main_message,
                    style={
                        "fontSize": "13px",
                        "color": COLORS["text_primary"],
                    }
                ),
            ],
            style={
                "display": "flex",
                "alignItems": "center",
                "flex": "1",
            }
        ),
        
        # Last update timestamp on the right
        html.Div(
            [
                html.Span(
                    "Last update: ",
                    style={
                        "fontSize": "11px",
                        "color": COLORS["text_muted"],
                    }
                ),
                html.Span(
                    update_text if update_text else "--",
                    style={
                        "fontSize": "11px",
                        "color": COLORS["text_secondary"],
                        "fontWeight": "500",
                    }
                ),
            ],
            style={"display": "flex", "alignItems": "center"}
        ) if update_text else None,
    ]
    
    # Warning container styling (orange/amber theme)
    container_style = {
        "backgroundColor": f"{COLORS['warning']}15",
        "border": f"1px solid {COLORS['warning']}",
        "borderRadius": "6px",
        "padding": "10px 15px",
        "marginBottom": "15px",
        "display": "flex",
        "justifyContent": "space-between",
        "alignItems": "center",
    }
    
    return html.Div(
        warning_content,
        id="staleness-warning-container",
        style=container_style,
    )


# =============================================================================
# Data Gap Warning Component
# FIX-032: Data Gap Detection & Auto-Bootstrap
# =============================================================================

def create_data_gap_warning(
    has_gap: bool,
    gap_type: Optional[str] = None,
    gap_message: Optional[str] = None,
    is_market_open: bool = True,
    on_bootstrap_click: bool = False,
) -> html.Div:
    """Create data gap warning banner component.
    
    FIX-032: Display warning when data gaps are detected during market hours.
    
    Args:
        has_gap: Whether a data gap is detected
        gap_type: Type of gap ('indicators', 'skew_pcr', 'candles')
        gap_message: Detailed message about the gap
        is_market_open: Whether market is currently open
        on_bootstrap_click: Whether bootstrap button was clicked (for loading state)
    
    Returns:
        Dash html.Div component for the data gap warning, or empty div if no gap
    """
    # Return empty div if no gap or market is closed
    if not has_gap or not is_market_open:
        return html.Div(id="data-gap-warning-container", style={"display": "none"})
    
    # Determine warning message
    if gap_message:
        main_message = gap_message
    elif gap_type:
        type_labels = {
            "indicators": "Indicator data",
            "skew_pcr": "Skew/PCR data",
            "candles": "Candle data",
        }
        main_message = f"{type_labels.get(gap_type, 'Data')} is missing or stale"
    else:
        main_message = "Data gap detected during market hours"
    
    # Build warning content
    warning_content = [
        # Warning icon and message
        html.Div(
            [
                html.Span(
                    "🔄",
                    style={
                        "fontSize": "16px",
                        "marginRight": "10px",
                    }
                ),
                html.Span(
                    "Data Gap Detected",
                    style={
                        "fontWeight": "600",
                        "fontSize": "13px",
                        "color": COLORS["negative"],
                        "marginRight": "10px",
                    }
                ),
                html.Span(
                    main_message,
                    style={
                        "fontSize": "13px",
                        "color": COLORS["text_primary"],
                    }
                ),
            ],
            style={
                "display": "flex",
                "alignItems": "center",
                "flex": "1",
            }
        ),
        
        # Auto-bootstrap button
        html.Button(
            "Refreshing..." if on_bootstrap_click else "Refresh Data",
            id="data-gap-bootstrap-btn",
            disabled=on_bootstrap_click,
            style={
                "backgroundColor": COLORS["accent"],
                "color": COLORS["text_light"],
                "border": "none",
                "borderRadius": "4px",
                "padding": "6px 12px",
                "cursor": "pointer" if not on_bootstrap_click else "not-allowed",
                "fontSize": "12px",
                "fontWeight": "500",
                "opacity": "0.7" if on_bootstrap_click else "1",
            }
        ),
    ]
    
    # Warning container styling (red/error theme)
    container_style = {
        "backgroundColor": f"{COLORS['negative']}15",
        "border": f"1px solid {COLORS['negative']}",
        "borderRadius": "6px",
        "padding": "10px 15px",
        "marginBottom": "15px",
        "display": "flex",
        "justifyContent": "space-between",
        "alignItems": "center",
    }
    
    return html.Div(
        warning_content,
        id="data-gap-warning-container",
        style=container_style,
    )


def create_staleness_indicator(
    is_stale: bool,
    data_age_seconds: Optional[int] = None,
) -> html.Div:
    """Create a compact staleness indicator for inline display.
    
    Requirements:
        5.7: Display cache_stale warning
        17.6: Display staleness warning if data is >5 minutes old
    
    Args:
        is_stale: Whether data is stale
        data_age_seconds: Age of data in seconds
    
    Returns:
        Dash html.Div component for the staleness indicator
    """
    if not is_stale:
        # Fresh data indicator
        return html.Div(
            [
                html.Span(
                    "●",
                    style={
                        "color": COLORS["positive"],
                        "marginRight": "4px",
                        "fontSize": "8px",
                    }
                ),
                html.Span(
                    "Live",
                    style={
                        "fontSize": "10px",
                        "color": COLORS["positive"],
                    }
                ),
            ],
            style={"display": "flex", "alignItems": "center"}
        )
    
    # Stale data indicator
    age_text = ""
    if data_age_seconds is not None:
        minutes = data_age_seconds // 60
        if minutes >= 60:
            hours = minutes // 60
            age_text = f" ({hours}h+ old)"
        elif minutes > 0:
            age_text = f" ({minutes}m old)"
    
    return html.Div(
        [
            html.Span(
                "●",
                style={
                    "color": COLORS["warning"],
                    "marginRight": "4px",
                    "fontSize": "8px",
                }
            ),
            html.Span(
                f"Stale{age_text}",
                style={
                    "fontSize": "10px",
                    "color": COLORS["warning"],
                }
            ),
        ],
        style={"display": "flex", "alignItems": "center"}
    )


def create_connection_status_panel(
    connection_status: ConnectionStatus,
) -> html.Div:
    """Create connection status panel showing WS and SSE status.
    
    Requirement 17.5: Display connection status indicators for WebSocket and SSE.
    
    Args:
        connection_status: ConnectionStatus object with current status
    
    Returns:
        Dash html.Div component with connection status indicators
    """
    return html.Div(
        [
            html.Div(
                "Connection Status",
                style={
                    "fontSize": "11px",
                    "color": COLORS["text_secondary"],
                    "textTransform": "uppercase",
                    "letterSpacing": "0.5px",
                    "marginBottom": "10px",
                }
            ),
            create_connection_status_indicator(
                "WebSocket",
                connection_status.ws_connected,
                connection_status.last_ws_update,
            ),
            create_connection_status_indicator(
                "SSE",
                connection_status.sse_connected,
                connection_status.last_sse_update,
            ),
        ],
        id="connection-status-panel",
        style={
            "padding": "12px",
            "backgroundColor": "rgba(255,255,255,0.05)",
            "borderRadius": "6px",
            "marginTop": "15px",
        }
    )


# =============================================================================
# Main Layout Assembly
# =============================================================================

def create_header(
    current_symbol: str = "nifty",
    current_mode: str = "current",
) -> html.Div:
    """Create the main header component.
    
    Args:
        current_symbol: Currently selected symbol
        current_mode: Currently selected mode
    
    Returns:
        Dash html.Div component for the header
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
                ],
                style={"display": "flex", "alignItems": "center"}
            ),
            
            # Mode tabs
            create_mode_tabs_header(current_mode),
            
            # Account button
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
        style=create_header_style(),
    )


def create_sidebar(
    state: StateManager,
    current_mode: str = "current",
) -> html.Div:
    """Create the sidebar component.
    
    Args:
        state: StateManager with current data
        current_mode: Currently selected mode
    
    Returns:
        Dash html.Div component for the sidebar
    """
    connection_status = state.get_connection_status()
    
    return html.Div(
        [
            # Navigation links
            html.Div(
                [
                    html.A(
                        "📊 Main",
                        href="/",
                        style={
                            "display": "block",
                            "padding": "10px 12px",
                            "color": COLORS["text_light"],
                            "textDecoration": "none",
                            "borderRadius": "4px",
                            "marginBottom": "5px",
                            "backgroundColor": "rgba(255,255,255,0.1)",
                        }
                    ),
                    html.A(
                        "📈 Advanced",
                        href="/advanced",
                        style={
                            "display": "block",
                            "padding": "10px 12px",
                            "color": COLORS["text_light"],
                            "textDecoration": "none",
                            "borderRadius": "4px",
                            "marginBottom": "5px",
                        }
                    ),
                    html.A(
                        "⚙️ Admin",
                        href="/admin",
                        style={
                            "display": "block",
                            "padding": "10px 12px",
                            "color": COLORS["text_light"],
                            "textDecoration": "none",
                            "borderRadius": "4px",
                            "marginBottom": "5px",
                        }
                    ),
                ],
                style={"marginBottom": "20px"}
            ),
            
            # Mode toggle
            create_mode_toggle(current_mode),
            
            # Connection status
            create_connection_status_panel(connection_status),
            
            # Market state
            html.Div(
                [
                    html.Div(
                        "Market Status",
                        style={
                            "fontSize": "11px",
                            "color": COLORS["text_secondary"],
                            "textTransform": "uppercase",
                            "letterSpacing": "0.5px",
                            "marginBottom": "8px",
                        }
                    ),
                    html.Div(
                        state.get_market_state(),
                        id="market-state-display",
                        style={
                            "fontSize": "14px",
                            "fontWeight": "600",
                            "color": COLORS["positive"] if state.get_market_state() == "OPEN" else COLORS["text_muted"],
                        }
                    ),
                ],
                style={
                    "padding": "12px",
                    "backgroundColor": "rgba(255,255,255,0.05)",
                    "borderRadius": "6px",
                    "marginTop": "15px",
                }
            ),
        ],
        style=create_sidebar_style(),
    )


def create_main_content_area() -> html.Div:
    """Create the main content area placeholder.
    
    This is where charts, indicators, and option chain will be displayed.
    
    Returns:
        Dash html.Div component for the main content area
    """
    return html.Div(
        [
            # Charts row
            html.Div(
                [
                    # Candlestick chart
                    html.Div(
                        [
                            html.Div("Trading View", style=create_card_header_style()),
                            dcc.Graph(
                                id="candlestick-chart",
                                config={"displayModeBar": False},
                                style={"height": "350px"},
                            ),
                        ],
                        style={**create_card_style(), "flex": "2"},
                    ),
                ],
                style={"display": "flex", "gap": "15px", "marginBottom": "15px"}
            ),
            
            # EMA chart
            html.Div(
                [
                    html.Div("Indicator Chart", style=create_card_header_style()),
                    dcc.Graph(
                        id="ema-chart",
                        config={"displayModeBar": False},
                        style={"height": "200px"},
                    ),
                ],
                style=create_card_style(),
            ),
            
            # Indicators and Option Chain row
            html.Div(
                [
                    # Indicators panel
                    html.Div(
                        id="indicators-panel-container",
                        style={"flex": "1"},
                    ),
                    
                    # Option chain
                    html.Div(
                        id="option-chain-container-wrapper",
                        style={"flex": "2"},
                    ),
                ],
                style={"display": "flex", "gap": "15px"}
            ),
        ],
        id="main-content-area",
        style={
            "marginLeft": "240px",  # Account for sidebar width
            "padding": "20px",
            "minHeight": "calc(100vh - 56px)",
        }
    )


def create_main_layout(
    state: StateManager,
    selected_symbol: str = "nifty",
    selected_mode: str = "current",
) -> html.Div:
    """Create the complete main dashboard layout.
    
    Requirements:
        2.1: Light mode design with dark teal header/sidebar
        2.2: Clean sans-serif font
        19.2: Main page displays symbol chart, EMA chart, indicators, option chain
    
    Args:
        state: StateManager with current data
        selected_symbol: Currently selected symbol
        selected_mode: Currently selected mode
    
    Returns:
        Dash html.Div component for the complete layout
    """
    return html.Div(
        [
            # Header
            create_header(selected_symbol, selected_mode),
            
            # Sidebar
            create_sidebar(state, selected_mode),
            
            # Main content
            create_main_content_area(),
            
            # Symbol selector bar at bottom
            html.Div(
                id="symbol-selector-container",
                style={
                    "position": "fixed",
                    "bottom": "0",
                    "left": "220px",
                    "right": "0",
                    "zIndex": "100",
                }
            ),
            
            # Interval components for polling
            dcc.Interval(
                id="fast-interval",
                interval=500,  # 500ms for LTP updates
                n_intervals=0,
            ),
            dcc.Interval(
                id="slow-interval",
                interval=5000,  # 5s for indicator updates
                n_intervals=0,
            ),
            dcc.Interval(
                id="health-interval",
                interval=30000,  # 30s for health checks
                n_intervals=0,
            ),
            
            # Store components for state
            dcc.Store(id="selected-symbol-store", data=selected_symbol),
            dcc.Store(id="selected-mode-store", data=selected_mode),
        ],
        style=create_professional_style(),
    )
