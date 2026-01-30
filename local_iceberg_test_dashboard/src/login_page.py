# Iceberg Test Dashboard - Login Page
"""
Login page layout and authentication flow components.

Implements Google OAuth authentication flow:
1. Generate OAuth URL with client_id and redirect URI
2. User clicks button to open Google OAuth in new tab
3. User pastes callback URL containing authorization code
4. Dashboard extracts 'code' parameter and exchanges for JWT

Requirements: 3.1, 3.2, 3.4, 3.5
"""

from typing import Optional
from urllib.parse import urlencode, urlparse, parse_qs

from dash import html, dcc
import dash_bootstrap_components as dbc

from .config import get_settings
from .layouts import COLORS, create_card_style


# =============================================================================
# OAuth URL Generation
# Requirement 3.2: Redirect to Google OAuth with configured client_id
# =============================================================================

def generate_google_oauth_url() -> str:
    """Generate Google OAuth authorization URL.
    
    Requirement 3.2: WHEN a user initiates login, THE Dashboard SHALL redirect
    to Google OAuth with the configured client_id.
    
    Requirement 3.3: THE Dashboard SHALL use callback URI
    https://botbro.ronykax.xyz/api/auth/callback/google
    
    Returns:
        Complete Google OAuth authorization URL
    """
    settings = get_settings()
    
    base_url = "https://accounts.google.com/o/oauth2/v2/auth"
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_callback_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "consent",
    }
    
    return f"{base_url}?{urlencode(params)}"


# =============================================================================
# Authorization Code Parsing
# Requirement 3.5: Parse authorization code from pasted URL
# =============================================================================

def parse_authorization_code(callback_url: str) -> Optional[str]:
    """Parse authorization code from callback URL.
    
    Requirement 3.5: THE Dashboard SHALL parse the authorization code from
    the pasted URL (extracting the 'code' query parameter).
    
    Args:
        callback_url: Full callback URL containing the authorization code
        
    Returns:
        Authorization code if found, None otherwise
    """
    if not callback_url:
        return None
    
    try:
        # Parse the URL
        parsed = urlparse(callback_url)
        
        # Extract query parameters
        query_params = parse_qs(parsed.query)
        
        # Get the 'code' parameter
        code_list = query_params.get("code", [])
        
        if code_list:
            return code_list[0]
        
        return None
    except Exception:
        return None


# =============================================================================
# Login Page Layout
# Requirement 3.1: Provide login interface for Google OAuth authentication
# =============================================================================

def create_login_page_layout() -> html.Div:
    """Create the login page layout.
    
    Requirement 3.1: THE Dashboard SHALL provide a login interface for
    Google OAuth authentication.
    
    Requirement 3.4: THE Dashboard SHALL provide an input field where users
    can paste the full callback URL containing the authorization code.
    
    Returns:
        Dash html.Div component for the login page
    """
    oauth_url = generate_google_oauth_url()
    
    return html.Div(
        [
            # Header
            html.Div(
                [
                    html.Span(
                        "❄",
                        style={
                            "fontSize": "32px",
                            "marginRight": "12px",
                        }
                    ),
                    html.Span(
                        "Iceberg",
                        style={
                            "fontSize": "28px",
                            "fontWeight": "bold",
                        }
                    ),
                ],
                style={
                    "display": "flex",
                    "alignItems": "center",
                    "justifyContent": "center",
                    "marginBottom": "30px",
                    "color": COLORS["text_light"],
                }
            ),
            
            # Login card
            html.Div(
                [
                    html.H3(
                        "Sign In",
                        style={
                            "textAlign": "center",
                            "marginBottom": "25px",
                            "color": COLORS["text_primary"],
                            "fontWeight": "600",
                        }
                    ),
                    
                    # Step 1: Google OAuth button
                    html.Div(
                        [
                            html.Div(
                                "Step 1: Sign in with Google",
                                style={
                                    "fontSize": "14px",
                                    "fontWeight": "500",
                                    "marginBottom": "10px",
                                    "color": COLORS["text_secondary"],
                                }
                            ),
                            html.A(
                                html.Button(
                                    [
                                        html.Img(
                                            src="https://www.gstatic.com/firebasejs/ui/2.0.0/images/auth/google.svg",
                                            style={
                                                "width": "20px",
                                                "height": "20px",
                                                "marginRight": "10px",
                                            }
                                        ),
                                        "Sign in with Google",
                                    ],
                                    id="google-oauth-btn",
                                    style={
                                        "display": "flex",
                                        "alignItems": "center",
                                        "justifyContent": "center",
                                        "width": "100%",
                                        "padding": "12px 20px",
                                        "backgroundColor": COLORS["card_bg"],
                                        "color": COLORS["text_primary"],
                                        "border": f"1px solid {COLORS['content_bg']}",
                                        "borderRadius": "6px",
                                        "cursor": "pointer",
                                        "fontSize": "14px",
                                        "fontWeight": "500",
                                        "transition": "all 0.2s ease",
                                    }
                                ),
                                href=oauth_url,
                                target="_blank",
                                style={"textDecoration": "none"},
                            ),
                            html.Div(
                                "Opens Google sign-in in a new tab",
                                style={
                                    "fontSize": "11px",
                                    "color": COLORS["text_muted"],
                                    "marginTop": "6px",
                                    "textAlign": "center",
                                }
                            ),
                        ],
                        style={"marginBottom": "25px"}
                    ),
                    
                    # Divider
                    html.Hr(
                        style={
                            "border": "none",
                            "borderTop": f"1px solid {COLORS['content_bg']}",
                            "margin": "20px 0",
                        }
                    ),
                    
                    # Step 2: Paste callback URL
                    html.Div(
                        [
                            html.Div(
                                "Step 2: Paste the callback URL",
                                style={
                                    "fontSize": "14px",
                                    "fontWeight": "500",
                                    "marginBottom": "10px",
                                    "color": COLORS["text_secondary"],
                                }
                            ),
                            html.Div(
                                "After signing in, copy the full URL from your browser and paste it below:",
                                style={
                                    "fontSize": "12px",
                                    "color": COLORS["text_muted"],
                                    "marginBottom": "10px",
                                }
                            ),
                            # Callback URL input (Requirement 3.4)
                            dcc.Input(
                                id="callback-url-input",
                                type="text",
                                placeholder="https://botbro.ronykax.xyz/api/auth/callback/google?code=...",
                                style={
                                    "width": "100%",
                                    "padding": "12px",
                                    "borderRadius": "6px",
                                    "border": f"1px solid {COLORS['content_bg']}",
                                    "fontSize": "13px",
                                    "marginBottom": "12px",
                                    "boxSizing": "border-box",
                                }
                            ),
                            # Submit button
                            html.Button(
                                "Complete Sign In",
                                id="submit-callback-btn",
                                style={
                                    "width": "100%",
                                    "padding": "12px 20px",
                                    "backgroundColor": COLORS["header_bg"],
                                    "color": COLORS["text_light"],
                                    "border": "none",
                                    "borderRadius": "6px",
                                    "cursor": "pointer",
                                    "fontSize": "14px",
                                    "fontWeight": "500",
                                    "transition": "all 0.2s ease",
                                }
                            ),
                        ],
                        style={"marginBottom": "15px"}
                    ),
                    
                    # Status display
                    html.Div(
                        id="login-status",
                        style={
                            "marginTop": "15px",
                            "padding": "10px",
                            "borderRadius": "6px",
                            "textAlign": "center",
                            "fontSize": "13px",
                            "display": "none",  # Hidden by default
                        }
                    ),
                    
                    # Alternative: Direct JWT input for testing
                    html.Details(
                        [
                            html.Summary(
                                "Advanced: Use existing JWT token",
                                style={
                                    "cursor": "pointer",
                                    "fontSize": "12px",
                                    "color": COLORS["text_muted"],
                                    "marginBottom": "10px",
                                }
                            ),
                            html.Div(
                                [
                                    dcc.Input(
                                        id="jwt-token-input",
                                        type="password",
                                        placeholder="Paste JWT token here...",
                                        style={
                                            "width": "100%",
                                            "padding": "10px",
                                            "borderRadius": "6px",
                                            "border": f"1px solid {COLORS['content_bg']}",
                                            "fontSize": "12px",
                                            "marginBottom": "10px",
                                            "boxSizing": "border-box",
                                        }
                                    ),
                                    html.Button(
                                        "Use Token",
                                        id="use-jwt-btn",
                                        style={
                                            "width": "100%",
                                            "padding": "10px",
                                            "backgroundColor": COLORS["accent"],
                                            "color": COLORS["text_light"],
                                            "border": "none",
                                            "borderRadius": "6px",
                                            "cursor": "pointer",
                                            "fontSize": "12px",
                                        }
                                    ),
                                ],
                                style={"marginTop": "10px"}
                            ),
                        ],
                        style={"marginTop": "20px"}
                    ),
                ],
                style={
                    **create_card_style(),
                    "maxWidth": "400px",
                    "margin": "0 auto",
                    "padding": "30px",
                }
            ),
            
            # Footer info
            html.Div(
                [
                    html.Div(
                        "Iceberg Test Dashboard",
                        style={
                            "fontSize": "12px",
                            "color": COLORS["text_muted"],
                        }
                    ),
                    html.Div(
                        "For testing Iceberg Trading Platform API",
                        style={
                            "fontSize": "11px",
                            "color": COLORS["text_muted"],
                            "marginTop": "4px",
                        }
                    ),
                ],
                style={
                    "textAlign": "center",
                    "marginTop": "30px",
                }
            ),
        ],
        style={
            "minHeight": "100vh",
            "display": "flex",
            "flexDirection": "column",
            "justifyContent": "center",
            "padding": "40px 20px",
            "backgroundColor": COLORS["header_bg"],
        }
    )


def create_login_status_display(
    success: bool,
    message: str,
) -> html.Div:
    """Create login status display component.
    
    Requirement 3.10: IF authentication fails, THEN THE Dashboard SHALL
    display the error message and allow retry.
    
    Args:
        success: Whether the operation was successful
        message: Status message to display
        
    Returns:
        Dash html.Div component for status display
    """
    bg_color = COLORS["positive"] if success else COLORS["negative"]
    
    return html.Div(
        message,
        style={
            "marginTop": "15px",
            "padding": "12px",
            "borderRadius": "6px",
            "textAlign": "center",
            "fontSize": "13px",
            "backgroundColor": f"{bg_color}20",  # 20% opacity
            "color": bg_color,
            "border": f"1px solid {bg_color}",
            "display": "block",
        }
    )


def create_user_info_display(
    email: str,
    name: Optional[str] = None,
    role: Optional[str] = None,
) -> html.Div:
    """Create user info display component for header.
    
    Requirement 3.8: THE Dashboard SHALL display current user info from GET /v1/auth/me.
    
    Args:
        email: User email address
        name: User display name (optional)
        role: User role (optional)
        
    Returns:
        Dash html.Div component for user info display
    """
    display_name = name or email.split("@")[0]
    role_badge = ""
    if role:
        role_badge = f" ({role})"
    
    return html.Div(
        [
            html.Span(
                f"{display_name}{role_badge}",
                style={
                    "fontSize": "13px",
                    "marginRight": "10px",
                }
            ),
            html.Button(
                "Logout",
                id="logout-btn",
                style={
                    "backgroundColor": "transparent",
                    "color": COLORS["text_light"],
                    "border": f"1px solid {COLORS['text_light']}",
                    "borderRadius": "4px",
                    "padding": "4px 12px",
                    "cursor": "pointer",
                    "fontSize": "12px",
                }
            ),
        ],
        style={
            "display": "flex",
            "alignItems": "center",
        }
    )
