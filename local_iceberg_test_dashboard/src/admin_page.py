# Iceberg Test Dashboard - Admin Page
"""
Admin page layout and callbacks for the Iceberg Test Dashboard.

Provides:
- User list table (Requirement 15.6)
- Strike range configuration (Requirement 15.7)

Requirements: 15.1, 15.6, 15.7, 19.4
"""

import asyncio
import json
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from dash import html, dcc, callback, Input, Output, State, ctx, dash_table
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
import pytz

from .layouts import COLORS, create_card_style, create_card_header_style, create_professional_style
from .models import VALID_SYMBOLS, VALID_MODES
from .api_client import IcebergAPIClient, APIError, APIResponse
from .state_manager import StateManager

IST = pytz.timezone("Asia/Kolkata")


# =============================================================================
# User List Table
# Requirement 15.6: Display user list from GET /v1/admin/users
# =============================================================================

def create_user_list_section() -> html.Div:
    """Create user list table section.
    
    Requirement 15.6: Display user list from GET /v1/admin/users
    
    Returns:
        Dash html.Div with user list table
    """
    return html.Div(
        [
            html.Div(
                [
                    html.Span("User Management", style={"fontWeight": "600"}),
                    html.Button(
                        "Load Users",
                        id="users-load-btn",
                        style={
                            "marginLeft": "15px",
                            "padding": "4px 12px",
                            "fontSize": "11px",
                            "backgroundColor": COLORS["accent"],
                            "color": COLORS["text_light"],
                            "border": "none",
                            "borderRadius": "4px",
                            "cursor": "pointer",
                        },
                        n_clicks=0,
                    ),
                ],
                style={
                    **create_card_header_style(),
                    "display": "flex",
                    "alignItems": "center",
                }
            ),
            
            # Info message
            html.Div(
                id="users-info-message",
                children="Click 'Load Users' to view the user list.",
                style={
                    "fontSize": "12px",
                    "color": COLORS["text_secondary"],
                    "marginBottom": "15px",
                    "fontStyle": "italic",
                }
            ),
            
            # User table
            dcc.Loading(
                id="users-loading",
                type="circle",
                children=[
                    dash_table.DataTable(
                        id="users-table",
                        columns=[
                            {"name": "Email", "id": "email"},
                            {"name": "Role", "id": "role"},
                            {"name": "Status", "id": "status"},
                            {"name": "Created", "id": "created_at"},
                            {"name": "Last Login", "id": "last_login"},
                        ],
                        data=[],
                        style_header={
                            "backgroundColor": COLORS["header_bg"],
                            "color": COLORS["text_light"],
                            "fontWeight": "bold",
                            "textAlign": "left",
                            "padding": "10px",
                            "fontSize": "12px",
                        },
                        style_cell={
                            "textAlign": "left",
                            "padding": "10px",
                            "fontSize": "12px",
                            "border": "none",
                            "borderBottom": f"1px solid {COLORS['content_bg']}",
                        },
                        style_data={
                            "backgroundColor": COLORS["card_bg"],
                            "color": COLORS["text_primary"],
                        },
                        style_data_conditional=[
                            # Highlight admin role
                            {
                                "if": {
                                    "filter_query": "{role} = 'admin'",
                                    "column_id": "role",
                                },
                                "color": COLORS["accent"],
                                "fontWeight": "600",
                            },
                            # Green for active status
                            {
                                "if": {
                                    "filter_query": "{status} = 'active'",
                                    "column_id": "status",
                                },
                                "color": COLORS["positive"],
                            },
                            # Red for inactive status
                            {
                                "if": {
                                    "filter_query": "{status} = 'inactive'",
                                    "column_id": "status",
                                },
                                "color": COLORS["negative"],
                            },
                        ],
                        style_table={
                            "overflowX": "auto",
                        },
                        page_size=10,
                        page_action="native",
                        sort_action="native",
                        filter_action="native",
                    ),
                ],
            ),
        ],
        id="user-list-section",
        style=create_card_style(),
    )


# =============================================================================
# Strike Range Configuration
# Requirement 15.7: Provide strike range configuration via POST /v1/admin/strike-ranges
# =============================================================================

def create_strike_range_section() -> html.Div:
    """Create strike range configuration section.
    
    Requirement 15.7: Provide strike range configuration via POST /v1/admin/strike-ranges
    
    Returns:
        Dash html.Div with strike range configuration form
    """
    return html.Div(
        [
            html.Div("Strike Range Configuration", style=create_card_header_style()),
            
            html.Div(
                "Configure the strike price range for each symbol/mode combination. Enter actual strike prices (e.g., 24900 to 25700 for NIFTY).",
                style={
                    "fontSize": "12px",
                    "color": COLORS["text_secondary"],
                    "marginBottom": "15px",
                }
            ),
            
            # Configuration form
            html.Div(
                [
                    # Symbol selector
                    html.Div(
                        [
                            html.Label(
                                "Symbol",
                                style={
                                    "fontSize": "12px",
                                    "color": COLORS["text_secondary"],
                                    "marginBottom": "5px",
                                    "display": "block",
                                }
                            ),
                            dcc.Dropdown(
                                id="strike-range-symbol",
                                options=[
                                    {"label": s.upper(), "value": s} for s in VALID_SYMBOLS
                                ],
                                value="nifty",
                                clearable=False,
                                style={"width": "150px"},
                            ),
                        ],
                        style={"flex": "1", "minWidth": "150px"}
                    ),
                    
                    # Mode selector
                    html.Div(
                        [
                            html.Label(
                                "Mode",
                                style={
                                    "fontSize": "12px",
                                    "color": COLORS["text_secondary"],
                                    "marginBottom": "5px",
                                    "display": "block",
                                }
                            ),
                            dcc.Dropdown(
                                id="strike-range-mode",
                                options=[
                                    {"label": m.title(), "value": m} for m in VALID_MODES
                                ],
                                value="current",
                                clearable=False,
                                style={"width": "150px"},
                            ),
                        ],
                        style={"flex": "1", "minWidth": "150px"}
                    ),
                    
                    # Lower Strike
                    html.Div(
                        [
                            html.Label(
                                "Lower Strike",
                                style={
                                    "fontSize": "12px",
                                    "color": COLORS["text_secondary"],
                                    "marginBottom": "5px",
                                    "display": "block",
                                }
                            ),
                            dcc.Input(
                                id="strike-range-lower",
                                type="number",
                                placeholder="e.g., 24900",
                                style={
                                    "width": "120px",
                                    "padding": "8px 12px",
                                    "fontSize": "13px",
                                    "border": f"1px solid {COLORS['content_bg']}",
                                    "borderRadius": "4px",
                                }
                            ),
                        ],
                        style={"flex": "1", "minWidth": "140px"}
                    ),
                    
                    # Upper Strike
                    html.Div(
                        [
                            html.Label(
                                "Upper Strike",
                                style={
                                    "fontSize": "12px",
                                    "color": COLORS["text_secondary"],
                                    "marginBottom": "5px",
                                    "display": "block",
                                }
                            ),
                            dcc.Input(
                                id="strike-range-upper",
                                type="number",
                                placeholder="e.g., 25700",
                                style={
                                    "width": "120px",
                                    "padding": "8px 12px",
                                    "fontSize": "13px",
                                    "border": f"1px solid {COLORS['content_bg']}",
                                    "borderRadius": "4px",
                                }
                            ),
                        ],
                        style={"flex": "1", "minWidth": "140px"}
                    ),
                ],
                style={
                    "display": "flex",
                    "flexWrap": "wrap",
                    "gap": "15px",
                    "marginBottom": "15px",
                }
            ),
            
            # Submit button
            html.Div(
                [
                    html.Button(
                        "Update Strike Ranges",
                        id="strike-range-submit-btn",
                        style={
                            "padding": "8px 20px",
                            "fontSize": "13px",
                            "backgroundColor": COLORS["header_bg"],
                            "color": COLORS["text_light"],
                            "border": "none",
                            "borderRadius": "4px",
                            "cursor": "pointer",
                        },
                        n_clicks=0,
                    ),
                    html.Div(
                        id="strike-range-status",
                        style={
                            "marginLeft": "15px",
                            "fontSize": "12px",
                            "display": "inline-block",
                        }
                    ),
                ],
                style={"display": "flex", "alignItems": "center"}
            ),
        ],
        id="strike-range-section",
        style=create_card_style(),
    )


# =============================================================================
# Access Denied Page
# Requirement 15.2: Redirect non-admin users
# =============================================================================

def create_access_denied_page() -> html.Div:
    """Create access denied page for non-admin users.
    
    Requirement 15.2: Admin page SHALL only be accessible to users with admin role.
    Non-admin users see this access denied message instead.
    
    Returns:
        Dash html.Div with access denied message
    """
    return html.Div(
        [
            # Access denied icon and message
            html.Div(
                [
                    html.Div(
                        "🚫",
                        style={
                            "fontSize": "64px",
                            "marginBottom": "20px",
                        }
                    ),
                    html.H3(
                        "Access Denied",
                        style={
                            "color": COLORS["text_primary"],
                            "marginBottom": "15px",
                        }
                    ),
                    html.P(
                        "You do not have permission to access the Admin page.",
                        style={
                            "color": COLORS["text_secondary"],
                            "fontSize": "14px",
                            "marginBottom": "10px",
                        }
                    ),
                    html.P(
                        "This page is only accessible to users with the admin role.",
                        style={
                            "color": COLORS["text_secondary"],
                            "fontSize": "13px",
                            "marginBottom": "25px",
                        }
                    ),
                    html.Div(
                        [
                            html.A(
                                "← Return to Main Dashboard",
                                href="/",
                                style={
                                    "color": COLORS["accent"],
                                    "textDecoration": "none",
                                    "fontSize": "14px",
                                    "fontWeight": "500",
                                }
                            ),
                        ],
                    ),
                ],
                style={
                    "textAlign": "center",
                    "padding": "60px 40px",
                    "backgroundColor": COLORS["card_bg"],
                    "borderRadius": "8px",
                    "boxShadow": "0 2px 4px rgba(0,0,0,0.1)",
                    "maxWidth": "500px",
                    "margin": "0 auto",
                }
            ),
        ],
        id="access-denied-page",
        style={
            "padding": "60px 20px",
            "maxWidth": "1400px",
            "margin": "0 auto",
        }
    )


# =============================================================================
# Admin Page Layout
# Requirements 15.1, 19.4: Admin page with admin endpoint testing interface
# =============================================================================

def create_admin_page_layout(
    state_manager: StateManager,
) -> html.Div:
    """Create the complete Admin page layout.
    
    Requirements:
        15.1: Provide separate Admin page accessible from navigation
        19.4: Admin page displays admin endpoint testing interface
    
    Args:
        state_manager: StateManager instance
    
    Returns:
        Dash html.Div with complete Admin page
    """
    return html.Div(
        [
            # Page header
            html.Div(
                [
                    html.H4(
                        "⚙️ Admin",
                        style={
                            "margin": "0",
                            "color": COLORS["text_primary"],
                        }
                    ),
                    html.Span(
                        "Admin Operations & User Management",
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
            
            # Two-column layout
            html.Div(
                [
                    # Left column - Users
                    html.Div(
                        [
                            create_user_list_section(),
                        ],
                        style={"flex": "1", "minWidth": "400px"},
                    ),
                    
                    # Right column - Strike Ranges
                    html.Div(
                        [
                            create_strike_range_section(),
                        ],
                        style={"flex": "1", "minWidth": "400px"},
                    ),
                ],
                style={
                    "display": "flex",
                    "gap": "20px",
                    "flexWrap": "wrap",
                }
            ),
        ],
        id="admin-page-content",
        style={
            "padding": "20px",
            "paddingBottom": "100px",  # Space for fixed symbol selector at bottom
            "maxWidth": "1400px",
            "margin": "0 auto",
        }
    )


# =============================================================================
# Helper Functions for API Calls
# =============================================================================

async def get_users(
    api_client: IcebergAPIClient,
    page: int = 1,
    limit: int = 100,
) -> Tuple[bool, List[Dict], int, bool, str]:
    """Get user list with pagination.
    
    Requirement 15.6: User list from GET /v1/admin/users
    FIX-035: Added pagination support
    
    Args:
        api_client: API client instance
        page: Page number (1-indexed)
        limit: Users per page (max 100)
    
    Returns:
        Tuple of (success, users_list, total, has_more, message)
    """
    try:
        result = await api_client.admin_get_users(page=page, limit=limit)
        if result.ok and result.data:
            users = result.data.get("users", [])
            total = result.data.get("total", len(users))
            has_more = result.data.get("has_more", False)
            return True, users, total, has_more, f"Loaded {len(users)} of {total} users (page {page})."
        return False, [], 0, False, result.error.get("message", "Failed to load users") if result.error else "Failed to load users"
    except APIError as e:
        return False, [], 0, False, f"Error: {e.message}"
    except Exception as e:
        return False, [], 0, False, f"Error: {str(e)}"


async def set_strike_ranges(
    api_client: IcebergAPIClient,
    symbol: str,
    mode: str,
    lower_strike: float,
    upper_strike: float,
) -> Tuple[bool, str]:
    """Set strike ranges for a symbol/mode.
    
    Requirement 15.7: Strike range configuration via POST /v1/admin/strike-ranges
    
    Args:
        api_client: API client instance
        symbol: Trading symbol
        mode: Expiry mode
        lower_strike: Lower strike price
        upper_strike: Upper strike price
    
    Returns:
        Tuple of (success, message)
    """
    # Validate that lower < upper
    if lower_strike >= upper_strike:
        return False, "Lower strike must be less than upper strike."
    
    try:
        result = await api_client.admin_set_strike_ranges(
            symbol=symbol,
            mode=mode,
            lower_strike=lower_strike,
            upper_strike=upper_strike,
        )
        if result.ok:
            return True, f"Strike range updated: {lower_strike:.0f} - {upper_strike:.0f} for {symbol.upper()} ({mode})."
        return False, result.error.get("message", "Failed to update strike ranges") if result.error else "Failed to update strike ranges"
    except APIError as e:
        return False, f"Error: {e.message}"
    except Exception as e:
        return False, f"Error: {str(e)}"
