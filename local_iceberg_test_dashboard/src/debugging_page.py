# Iceberg Test Dashboard - Debugging Page
"""
Debugging page layout for the Iceberg Test Dashboard.

Provides:
- REST endpoint testing panel (moved from Advanced page)

Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6, 18.7
"""

import asyncio
import json
import time
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Tuple

from dash import html, dcc, callback, Input, Output, State, ctx
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
import pytz

from .layouts import COLORS, create_card_style, create_card_header_style
from .models import VALID_SYMBOLS
from .api_client import IcebergAPIClient, APIError, APIResponse
from .state_manager import StateManager

IST = pytz.timezone("Asia/Kolkata")


# =============================================================================
# REST Testing Panel - Endpoint Definitions
# Requirements 18.1, 18.2, 18.3, 18.4, 18.5
# =============================================================================

REST_ENDPOINTS = [
    {
        "id": "snapshot",
        "name": "Snapshot",
        "description": "Get current snapshot for symbol/mode",
        "method": "GET",
        "path": "/v1/dashboard/{symbol}/{mode}/snapshot",
        "params": [
            {"name": "symbol", "type": "select", "options": VALID_SYMBOLS, "required": True},
            {"name": "mode", "type": "select", "options": ["current", "positional"], "required": True},
        ],
    },
    {
        "id": "historical",
        "name": "Historical Snapshot",
        "description": "Get historical snapshot for a date",
        "method": "GET",
        "path": "/v1/dashboard/historical/snapshot",
        "params": [
            {"name": "date", "type": "date", "required": True},
            {"name": "symbols", "type": "text", "placeholder": "nifty,banknifty", "required": False},
        ],
    },
    {
        "id": "candles",
        "name": "Market Candles",
        "description": "Get candle data for symbol",
        "method": "GET",
        "path": "/v1/dashboard/market/candles",
        "params": [
            {"name": "symbol", "type": "select", "options": VALID_SYMBOLS, "required": True},
            {"name": "interval", "type": "select", "options": ["5m", "15m", "1h"], "required": False},
            {"name": "start", "type": "text", "placeholder": "2026-01-20T09:15:00", "required": False},
            {"name": "end", "type": "text", "placeholder": "2026-01-20T15:30:00", "required": False},
        ],
    },
    {
        "id": "spot",
        "name": "Market Spot",
        "description": "Get current spot prices",
        "method": "GET",
        "path": "/v1/dashboard/market/spot",
        "params": [
            {"name": "symbols", "type": "text", "placeholder": "nifty,banknifty", "required": False},
        ],
    },
    {
        "id": "adr_constituents",
        "name": "ADR Constituents",
        "description": "Get ADR constituent data for treemap",
        "method": "GET",
        "path": "/v1/dashboard/adr/constituents",
        "params": [
            {"name": "symbol", "type": "select", "options": VALID_SYMBOLS, "required": False},
        ],
    },
    {
        "id": "health",
        "name": "Health Check",
        "description": "Check API health status",
        "method": "GET",
        "path": "/health",
        "params": [],
    },
    {
        "id": "health_ready",
        "name": "Health Ready",
        "description": "Check API readiness",
        "method": "GET",
        "path": "/health/ready",
        "params": [],
    },
    {
        "id": "bootstrap",
        "name": "Bootstrap",
        "description": "Get bootstrap data for dashboard initialization",
        "method": "GET",
        "path": "/v1/dashboard/bootstrap",
        "params": [
            {"name": "symbols", "type": "text", "placeholder": "nifty,banknifty,sensex,finnifty", "required": False},
        ],
    },
]


def create_endpoint_param_input(param: Dict[str, Any], endpoint_id: str) -> html.Div:
    """Create input component for an endpoint parameter."""
    param_id = f"debug-param-{endpoint_id}-{param['name']}"
    label_text = param["name"].replace("_", " ").title()
    if param.get("required"):
        label_text += " *"
    
    label = html.Label(
        label_text,
        style={
            "fontSize": "11px",
            "color": COLORS["text_secondary"],
            "marginBottom": "3px",
            "display": "block",
        }
    )
    
    if param["type"] == "select":
        input_component = dcc.Dropdown(
            id=param_id,
            options=[{"label": o.upper() if isinstance(o, str) else o, "value": o} for o in param["options"]],
            value=param["options"][0] if param.get("required") else None,
            clearable=not param.get("required"),
            style={"fontSize": "12px"},
        )
    elif param["type"] == "date":
        input_component = dcc.DatePickerSingle(
            id=param_id,
            date=date.today().isoformat(),
            display_format="YYYY-MM-DD",
            style={"fontSize": "12px"},
        )
    else:  # text
        input_component = dcc.Input(
            id=param_id,
            type="text",
            placeholder=param.get("placeholder", ""),
            style={
                "width": "100%",
                "padding": "6px 10px",
                "fontSize": "12px",
                "border": f"1px solid {COLORS['content_bg']}",
                "borderRadius": "4px",
            }
        )
    
    return html.Div(
        [label, input_component],
        style={"marginBottom": "10px", "flex": "1", "minWidth": "150px"}
    )


def create_endpoint_card(endpoint: Dict[str, Any]) -> html.Div:
    """Create a card for a single REST endpoint."""
    method_color = COLORS["positive"] if endpoint["method"] == "GET" else COLORS["accent"]
    
    param_inputs = []
    for param in endpoint.get("params", []):
        param_inputs.append(create_endpoint_param_input(param, endpoint["id"]))
    
    return html.Div(
        [
            html.Div(
                [
                    html.Span(
                        endpoint["method"],
                        style={
                            "backgroundColor": method_color,
                            "color": COLORS["text_light"],
                            "padding": "2px 8px",
                            "borderRadius": "3px",
                            "fontSize": "10px",
                            "fontWeight": "bold",
                            "marginRight": "10px",
                        }
                    ),
                    html.Span(
                        endpoint["name"],
                        style={
                            "fontWeight": "600",
                            "fontSize": "13px",
                        }
                    ),
                ],
                style={"marginBottom": "5px"}
            ),
            html.Div(
                endpoint["path"],
                style={
                    "fontSize": "11px",
                    "color": COLORS["text_muted"],
                    "fontFamily": "monospace",
                    "marginBottom": "10px",
                }
            ),
            html.Div(
                endpoint["description"],
                style={
                    "fontSize": "12px",
                    "color": COLORS["text_secondary"],
                    "marginBottom": "10px",
                }
            ),
            html.Div(
                param_inputs,
                style={
                    "display": "flex",
                    "flexWrap": "wrap",
                    "gap": "10px",
                }
            ) if param_inputs else None,
            html.Button(
                "Execute",
                id={"type": "debug-execute-btn", "endpoint": endpoint["id"]},
                style={
                    "marginTop": "10px",
                    "padding": "6px 16px",
                    "fontSize": "12px",
                    "backgroundColor": COLORS["header_bg"],
                    "color": COLORS["text_light"],
                    "border": "none",
                    "borderRadius": "4px",
                    "cursor": "pointer",
                },
                n_clicks=0,
            ),
        ],
        id=f"debug-endpoint-card-{endpoint['id']}",
        style={
            "backgroundColor": COLORS["card_bg"],
            "padding": "15px",
            "borderRadius": "6px",
            "marginBottom": "10px",
            "border": f"1px solid {COLORS['content_bg']}",
        }
    )


def create_rest_testing_panel() -> html.Div:
    """Create REST endpoint testing panel."""
    return html.Div(
        [
            html.Div("REST API Testing", style=create_card_header_style()),
            
            html.Div(
                [
                    html.Label(
                        "Select Endpoint",
                        style={
                            "fontSize": "12px",
                            "color": COLORS["text_secondary"],
                            "marginBottom": "5px",
                            "display": "block",
                        }
                    ),
                    dcc.Dropdown(
                        id="debug-endpoint-selector",
                        options=[
                            {"label": f"{ep['method']} {ep['name']}", "value": ep["id"]}
                            for ep in REST_ENDPOINTS
                        ],
                        value="snapshot",
                        clearable=False,
                        style={"marginBottom": "15px"},
                    ),
                ],
            ),
            
            html.Div(
                id="debug-endpoint-form",
                children=[create_endpoint_card(REST_ENDPOINTS[0])],
            ),
            
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(
                                "Response",
                                style={"fontWeight": "600", "fontSize": "13px"}
                            ),
                            html.Span(
                                id="debug-response-time",
                                style={
                                    "marginLeft": "15px",
                                    "fontSize": "11px",
                                    "color": COLORS["text_muted"],
                                }
                            ),
                            html.Span(
                                id="debug-response-status",
                                style={
                                    "marginLeft": "10px",
                                    "fontSize": "11px",
                                    "padding": "2px 8px",
                                    "borderRadius": "3px",
                                }
                            ),
                        ],
                        style={"marginBottom": "10px"}
                    ),
                    dcc.Loading(
                        id="debug-response-loading",
                        type="circle",
                        children=[
                            html.Pre(
                                id="debug-response-json",
                                children="// Response will appear here",
                                style={
                                    "backgroundColor": "#1E1E1E",
                                    "color": "#D4D4D4",
                                    "padding": "15px",
                                    "borderRadius": "6px",
                                    "fontSize": "11px",
                                    "fontFamily": "monospace",
                                    "maxHeight": "500px",
                                    "overflow": "auto",
                                    "whiteSpace": "pre-wrap",
                                    "wordBreak": "break-word",
                                }
                            ),
                        ],
                    ),
                ],
                style={
                    "marginTop": "20px",
                    "padding": "15px",
                    "backgroundColor": COLORS["content_bg"],
                    "borderRadius": "6px",
                }
            ),
        ],
        id="debug-testing-panel",
        style=create_card_style(),
    )


def create_debugging_page_layout(state_manager: StateManager) -> html.Div:
    """Create the complete Debugging page layout."""
    return html.Div(
        [
            html.Div(
                [
                    html.H4(
                        "🔧 Debugging",
                        style={
                            "margin": "0",
                            "color": COLORS["text_primary"],
                        }
                    ),
                    html.Span(
                        "REST API Testing & Diagnostics",
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
            
            create_rest_testing_panel(),
            
            dcc.Store(id="debug-selected-endpoint-store", data="snapshot"),
        ],
        id="debugging-page-content",
        style={
            "padding": "20px",
            "paddingBottom": "100px",  # Space for fixed symbol selector at bottom
            "maxWidth": "1000px",
            "margin": "0 auto",
        }
    )


def get_endpoint_by_id(endpoint_id: str) -> Optional[Dict[str, Any]]:
    """Get endpoint definition by ID."""
    for ep in REST_ENDPOINTS:
        if ep["id"] == endpoint_id:
            return ep
    return None


async def execute_rest_endpoint(
    endpoint_id: str,
    params: Dict[str, Any],
    api_client: IcebergAPIClient,
) -> Tuple[Dict[str, Any], float, int]:
    """Execute a REST endpoint and return results."""
    start_time = time.time()
    
    try:
        if endpoint_id == "snapshot":
            result = await api_client.snapshot(
                symbol=params.get("symbol", "nifty"),
                mode=params.get("mode", "current"),
            )
        elif endpoint_id == "historical":
            result = await api_client.historical_snapshot(
                date=params.get("date", date.today().isoformat()),
                symbols=params.get("symbols", "").split(",") if params.get("symbols") else None,
            )
        elif endpoint_id == "candles":
            result = await api_client.market_candles(
                symbol=params.get("symbol", "nifty"),
                interval=params.get("interval", "5m"),
                start=params.get("start") or None,
                end=params.get("end") or None,
            )
        elif endpoint_id == "spot":
            symbols = params.get("symbols", "").split(",") if params.get("symbols") else None
            result = await api_client.market_spot(symbols=symbols)
        elif endpoint_id == "adr_constituents":
            result = await api_client.adr_constituents(
                symbol=params.get("symbol", "nifty"),
            )
        elif endpoint_id == "health":
            result = await api_client.health()
            result = APIResponse(ok=True, data=result)
        elif endpoint_id == "health_ready":
            result = await api_client.health_ready()
            result = APIResponse(ok=True, data=result)
        elif endpoint_id == "bootstrap":
            symbols = params.get("symbols", "").split(",") if params.get("symbols") else ["nifty", "banknifty", "sensex", "finnifty"]
            symbols = [s.strip() for s in symbols if s.strip()]
            result = await api_client.bootstrap(symbols=symbols)
        else:
            raise ValueError(f"Unknown endpoint: {endpoint_id}")
        
        elapsed_ms = (time.time() - start_time) * 1000
        
        response_data = {
            "ok": result.ok,
            "data": result.data,
            "error": result.error,
            "meta": result.meta,
        }
        
        return response_data, elapsed_ms, 200
        
    except APIError as e:
        elapsed_ms = (time.time() - start_time) * 1000
        return {
            "ok": False,
            "error": {
                "code": e.error_code,
                "message": e.message,
                "details": e.details,
            }
        }, elapsed_ms, e.status
        
    except Exception as e:
        elapsed_ms = (time.time() - start_time) * 1000
        return {
            "ok": False,
            "error": {
                "code": "CLIENT_ERROR",
                "message": str(e),
            }
        }, elapsed_ms, 0
