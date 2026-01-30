# Iceberg Test Dashboard - REST API Client
"""
Async HTTP client for the Iceberg Trading Platform API.

Implements all REST endpoints with retry logic and exponential backoff.
Requirements: 3.4, 3.6, 3.9, 3.10, 4.1, 4.2, 4.3, 5.1, 14.2, 15.3, 15.4, 15.6, 17.2, 17.7
"""

import asyncio
import functools
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, TypeVar
from urllib.parse import urlencode

import httpx
import structlog

from .config import get_settings

# Requirement 17.7: Log all errors to console for debugging
logger = structlog.get_logger(__name__)

T = TypeVar("T")


# Auth error codes that should trigger session clear
AUTH_ERROR_CODES = {"UNAUTHORIZED", "SESSION_REVOKED", "TOKEN_EXPIRED", "INVALID_TOKEN"}


@dataclass
class APIError(Exception):
    """API error with status code and error details.
    
    Requirement 3.10: Handle auth errors (401, SESSION_REVOKED).
    """

    status: int
    error_code: str
    message: str
    details: Optional[Dict[str, Any]] = None

    def __str__(self) -> str:
        return f"APIError({self.status}): {self.error_code} - {self.message}"

    def is_auth_error(self) -> bool:
        """Check if this is an authentication error requiring session clear.
        
        Requirement 3.10: Handle auth errors (401, SESSION_REVOKED).
        
        Returns:
            True if this is an auth error, False otherwise
        """
        if self.status == 401:
            return True
        if self.error_code in AUTH_ERROR_CODES:
            return True
        return False


@dataclass
class APIResponse:
    """Wrapper for API response data."""

    ok: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None
    meta: Optional[Dict[str, Any]] = None


def calculate_backoff_delay(attempt: int) -> float:
    """
    Calculate backoff delay for retry attempt.

    Property 13: API Retry Logic
    Delays: immediate (0), 1s, 2s for attempts 1, 2, 3
    Requirement 17.2

    Args:
        attempt: Current attempt number (1-indexed)

    Returns:
        Delay in seconds before next retry
    """
    if attempt <= 1:
        return 0.0  # Immediate retry for first attempt
    elif attempt == 2:
        return 1.0
    else:
        return 2.0


def with_retry(
    max_attempts: int = 3,
    retryable_statuses: tuple = (500, 502, 503, 504),
) -> Callable:
    """
    Decorator for retry logic with exponential backoff.

    Requirement 17.2: Retry logic for failed API calls (3 attempts with backoff)
    Delays: immediate, 1s, 2s

    Args:
        max_attempts: Maximum number of retry attempts (default 3)
        retryable_statuses: HTTP status codes that trigger retry

    Returns:
        Decorated function with retry logic
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            last_exception: Optional[Exception] = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except httpx.HTTPStatusError as e:
                    if e.response.status_code not in retryable_statuses:
                        raise
                    last_exception = e
                    if attempt < max_attempts:
                        delay = calculate_backoff_delay(attempt)
                        logger.warning(
                            "api_retry",
                            attempt=attempt,
                            max_attempts=max_attempts,
                            delay=delay,
                            status=e.response.status_code,
                        )
                        await asyncio.sleep(delay)
                except (httpx.ConnectError, httpx.TimeoutException) as e:
                    last_exception = e
                    if attempt < max_attempts:
                        delay = calculate_backoff_delay(attempt)
                        logger.warning(
                            "api_retry_connection",
                            attempt=attempt,
                            max_attempts=max_attempts,
                            delay=delay,
                            error=str(e),
                        )
                        await asyncio.sleep(delay)

            # All retries exhausted
            if last_exception:
                raise last_exception
            raise RuntimeError("Retry logic failed unexpectedly")

        return wrapper

    return decorator


class IcebergAPIClient:
    """
    Async REST client for Iceberg Trading Platform API.

    Provides methods for:
    - Health checks (Requirement 4.1, 4.2, 4.3)
    - Bootstrap data (Requirement 5.1)
    - Snapshots and market data
    - ADR constituents (Requirement 14.2)
    - Authentication (Requirement 3.4, 3.6)
    - Admin operations (Requirement 15.3, 15.4, 15.6)
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
    ):
        """
        Initialize the API client.

        Args:
            base_url: API base URL (defaults to settings)
            timeout: Request timeout in seconds
        """
        settings = get_settings()
        self.base_url = base_url or settings.iceberg_api_url
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._jwt_token: Optional[str] = None

    @property
    def jwt_token(self) -> Optional[str]:
        """Get current JWT token."""
        return self._jwt_token

    @jwt_token.setter
    def jwt_token(self, value: Optional[str]) -> None:
        """Set JWT token for authenticated requests."""
        self._jwt_token = value

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client.
        
        Note: Always creates a fresh client to avoid event loop binding issues.
        httpx.AsyncClient is bound to the event loop it was created in, and
        Dash callbacks create new event loops via asyncio.new_event_loop().
        Reusing a client from a different event loop causes requests to fail silently.
        """
        # Always close existing client and create fresh one
        # This is necessary because Dash callbacks run in different event loops
        if self._client and not self._client.is_closed:
            try:
                await self._client.aclose()
            except Exception:
                pass
        
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
        )
        logger.debug("http_client_created", base_url=self.base_url)
        
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _get_auth_headers(self) -> Dict[str, str]:
        """Get authorization headers if JWT token is set."""
        if self._jwt_token:
            return {"Authorization": f"Bearer {self._jwt_token}"}
        return {}

    async def _handle_response(self, response: httpx.Response) -> APIResponse:
        """
        Parse API response and handle errors.

        Args:
            response: HTTP response object

        Returns:
            Parsed APIResponse

        Raises:
            APIError: If response indicates an error
        """
        try:
            data = response.json()
        except Exception as e:
            # Requirement 17.7: Log all errors to console for debugging
            logger.error(
                "api_json_parse_error",
                error=str(e),
                status_code=response.status_code,
                response_preview=response.text[:200] if response.text else None,
            )
            data = {"raw": response.text}

        if response.status_code >= 400:
            error_data = data.get("error", {}) if isinstance(data, dict) else {}
            error = APIError(
                status=response.status_code,
                error_code=error_data.get("code", "UNKNOWN"),
                message=error_data.get("message", response.text),
                details=error_data.get("details"),
            )
            # Requirement 17.7: Log all errors to console for debugging
            logger.error(
                "api_error_response",
                status=error.status,
                error_code=error.error_code,
                message=error.message,
                is_auth_error=error.is_auth_error(),
            )
            raise error

        if isinstance(data, dict):
            return APIResponse(
                ok=data.get("ok", True),
                data=data.get("data"),
                error=data.get("error"),
                meta=data.get("meta"),
            )
        return APIResponse(ok=True, data=data)

    # -------------------------------------------------------------------------
    # Health Endpoints (Requirements 4.1, 4.2, 4.3)
    # -------------------------------------------------------------------------

    @with_retry(max_attempts=3)
    async def health(self) -> Dict[str, Any]:
        """
        Check API health status.

        Requirement 4.1: Display health status from GET /health

        Returns:
            Health status response
        """
        client = await self._get_client()
        response = await client.get("/health")
        response.raise_for_status()
        return response.json()

    @with_retry(max_attempts=3)
    async def health_ready(self) -> Dict[str, Any]:
        """
        Check API readiness status.

        Requirement 4.2: Display readiness status from GET /health/ready

        Returns:
            Readiness status response
        """
        client = await self._get_client()
        response = await client.get("/health/ready")
        response.raise_for_status()
        return response.json()

    @with_retry(max_attempts=3)
    async def health_live(self) -> Dict[str, Any]:
        """
        Check API liveness status.

        Requirement 4.3: Display liveness status from GET /health/live

        Returns:
            Liveness status response
        """
        client = await self._get_client()
        response = await client.get("/health/live")
        response.raise_for_status()
        return response.json()

    # -------------------------------------------------------------------------
    # Dashboard Endpoints (Requirements 5.1, 14.2)
    # -------------------------------------------------------------------------

    @with_retry(max_attempts=3)
    async def bootstrap(
        self,
        symbols: Optional[List[str]] = None,
        include_candles: bool = True,
        include_option_chain: bool = True,
        include_indicators: bool = True,
    ) -> APIResponse:
        """
        Fetch bootstrap data for dashboard initialization.

        Requirement 5.1: Fetch bootstrap data from GET /v1/dashboard/bootstrap

        Args:
            symbols: List of symbols to fetch (default: all)
            include_candles: Include candle data
            include_option_chain: Include option chain data
            include_indicators: Include EMA, RSI, BB, VWAP indicators in series

        Returns:
            Bootstrap response with candles, indicators, option chain
        """
        client = await self._get_client()
        params = {
            "include_candles": str(include_candles).lower(),
            "include_option_chain": str(include_option_chain).lower(),
            "include_indicators": str(include_indicators).lower(),
        }
        if symbols:
            params["symbols"] = ",".join(symbols)

        response = await client.get(
            "/v1/dashboard/bootstrap",
            params=params,
            headers=self._get_auth_headers(),
        )
        response.raise_for_status()
        return await self._handle_response(response)

    @with_retry(max_attempts=3)
    async def snapshot(self, symbol: str, mode: str) -> APIResponse:
        """
        Fetch snapshot data for a symbol/mode combination.

        Args:
            symbol: Trading symbol (nifty, banknifty, sensex, finnifty)
            mode: Expiry mode (current, positional)

        Returns:
            Snapshot response with current data
        """
        client = await self._get_client()
        response = await client.get(
            f"/v1/dashboard/{symbol}/{mode}/snapshot",
            headers=self._get_auth_headers(),
        )
        response.raise_for_status()
        return await self._handle_response(response)

    @with_retry(max_attempts=3)
    async def historical_snapshot(
        self,
        date: str,
        symbols: Optional[List[str]] = None,
    ) -> APIResponse:
        """
        Fetch historical snapshot data.

        Args:
            date: Date string (YYYY-MM-DD)
            symbols: List of symbols to fetch

        Returns:
            Historical snapshot response
        """
        client = await self._get_client()
        params = {"date": date}
        if symbols:
            params["symbols"] = ",".join(symbols)

        response = await client.get(
            "/v1/dashboard/historical/snapshot",
            params=params,
            headers=self._get_auth_headers(),
        )
        response.raise_for_status()
        return await self._handle_response(response)

    @with_retry(max_attempts=3)
    async def market_candles(
        self,
        symbol: str,
        interval: str = "5m",
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> APIResponse:
        """
        Fetch market candle data.

        Args:
            symbol: Trading symbol
            interval: Candle interval (5m, 15m, 1h, etc.)
            start: Start datetime (ISO format)
            end: End datetime (ISO format)

        Returns:
            Candle data response
        """
        client = await self._get_client()
        params = {"symbol": symbol, "interval": interval}
        if start:
            params["start"] = start
        if end:
            params["end"] = end

        response = await client.get(
            "/v1/dashboard/market/candles",
            params=params,
            headers=self._get_auth_headers(),
        )
        response.raise_for_status()
        return await self._handle_response(response)

    @with_retry(max_attempts=3)
    async def market_spot(self, symbols: Optional[List[str]] = None) -> APIResponse:
        """
        Fetch current spot prices.

        Args:
            symbols: List of symbols to fetch

        Returns:
            Spot price response
        """
        client = await self._get_client()
        params = {}
        if symbols:
            params["symbols"] = ",".join(symbols)

        response = await client.get(
            "/v1/dashboard/market/spot",
            params=params,
            headers=self._get_auth_headers(),
        )
        response.raise_for_status()
        return await self._handle_response(response)

    @with_retry(max_attempts=3)
    async def adr_constituents(self, symbol: str = "nifty") -> APIResponse:
        """
        Fetch ADR constituent data for treemap visualization.

        Requirement 14.2: Fetch constituent data from GET /v1/dashboard/adr/constituents

        Args:
            symbol: Index symbol (default: nifty)

        Returns:
            ADR constituents response with change percentages
        """
        try:
            client = await self._get_client()
            
            # Log request details
            logger.info(
                "adr_constituents_request",
                symbol=symbol,
                url=f"{self.base_url}/v1/dashboard/adr/constituents",
                has_jwt=bool(self.jwt_token),
            )
            
            response = await client.get(
                "/v1/dashboard/adr/constituents",
                params={"symbol": symbol},
                headers=self._get_auth_headers(),
            )
            
            # Log raw HTTP response
            logger.info(
                "adr_constituents_http_response",
                symbol=symbol,
                status_code=response.status_code,
                response_text=response.text[:500] if response.text else None,
            )
            
            response.raise_for_status()
            return await self._handle_response(response)
        except Exception as e:
            logger.error(
                "adr_constituents_exception",
                symbol=symbol,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise

    # -------------------------------------------------------------------------
    # Authentication Endpoints (Requirements 3.4, 3.6)
    # -------------------------------------------------------------------------

    @with_retry(max_attempts=3)
    async def exchange_google_code(self, authorization_code: str) -> APIResponse:
        """
        Exchange Google OAuth authorization code for JWT token.

        Requirement 3.4: Exchange code via POST /v1/auth/google/exchange

        Args:
            authorization_code: Google OAuth authorization code

        Returns:
            Response with JWT token
        """
        client = await self._get_client()
        response = await client.post(
            "/v1/auth/google/exchange",
            json={"authorization_code": authorization_code},
        )
        response.raise_for_status()
        result = await self._handle_response(response)

        # Store JWT token if present
        if result.data and "token" in result.data:
            self._jwt_token = result.data["token"]

        return result

    @with_retry(max_attempts=3)
    async def get_me(self) -> APIResponse:
        """
        Get current user information.

        Requirement 3.6: Display current user info from GET /v1/auth/me

        Returns:
            User information response
        """
        client = await self._get_client()
        response = await client.get(
            "/v1/auth/me",
            headers=self._get_auth_headers(),
        )
        response.raise_for_status()
        return await self._handle_response(response)

    @with_retry(max_attempts=3)
    async def refresh_token(self) -> APIResponse:
        """
        Refresh JWT token.

        Requirement 3.6: Refresh via POST /v1/auth/refresh

        Returns:
            Response with new JWT token
        """
        client = await self._get_client()
        response = await client.post(
            "/v1/auth/refresh",
            headers=self._get_auth_headers(),
        )
        response.raise_for_status()
        result = await self._handle_response(response)

        # Update stored JWT token if present
        if result.data and "token" in result.data:
            self._jwt_token = result.data["token"]

        return result

    # -------------------------------------------------------------------------
    # Admin Endpoints (Requirements 15.3, 15.4, 15.6)
    # -------------------------------------------------------------------------

    @with_retry(max_attempts=3)
    async def admin_request_otp(self) -> APIResponse:
        """
        Request OTP for admin operations.

        Requirement 15.3: OTP request via POST /v1/admin/otp/request

        Returns:
            OTP request response
        """
        client = await self._get_client()
        response = await client.post(
            "/v1/admin/otp/request",
            headers=self._get_auth_headers(),
        )
        response.raise_for_status()
        return await self._handle_response(response)

    @with_retry(max_attempts=3)
    async def admin_verify_otp(self, otp: str) -> APIResponse:
        """
        Verify OTP for admin operations.

        Requirement 15.4: OTP verification via POST /v1/admin/otp/verify

        Args:
            otp: One-time password to verify

        Returns:
            OTP verification response
        """
        client = await self._get_client()
        response = await client.post(
            "/v1/admin/otp/verify",
            json={"otp": otp},
            headers=self._get_auth_headers(),
        )
        response.raise_for_status()
        return await self._handle_response(response)

    @with_retry(max_attempts=3)
    async def admin_session_status(self) -> APIResponse:
        """
        Get admin session status.

        Returns:
            Session status response
        """
        client = await self._get_client()
        response = await client.get(
            "/v1/admin/session/status",
            headers=self._get_auth_headers(),
        )
        response.raise_for_status()
        return await self._handle_response(response)

    @with_retry(max_attempts=3)
    async def admin_get_users(
        self,
        page: int = 1,
        limit: int = 100,
    ) -> APIResponse:
        """
        Get list of users with pagination (requires OTP verification).

        Requirement 15.6: User list from GET /v1/admin/users
        FIX-035: Added pagination support

        Args:
            page: Page number (1-indexed)
            limit: Users per page (max 100)

        Returns:
            Paginated user list response with users, total, page, limit, has_more
        """
        client = await self._get_client()
        response = await client.get(
            "/v1/admin/users",
            params={"page": page, "limit": limit},
            headers=self._get_auth_headers(),
        )
        response.raise_for_status()
        return await self._handle_response(response)

    @with_retry(max_attempts=3)
    async def admin_set_strike_ranges(
        self,
        symbol: str,
        mode: str,
        lower_strike: float,
        upper_strike: float,
    ) -> APIResponse:
        """
        Configure strike ranges for a symbol/mode.

        Args:
            symbol: Trading symbol
            mode: Expiry mode
            lower_strike: Lower strike price
            upper_strike: Upper strike price

        Returns:
            Configuration response
        """
        client = await self._get_client()
        response = await client.post(
            "/v1/admin/strike-ranges",
            json={
                "symbol": symbol,
                "mode": mode,
                "lower_strike": lower_strike,
                "upper_strike": upper_strike,
            },
            headers=self._get_auth_headers(),
        )
        response.raise_for_status()
        return await self._handle_response(response)

    # -------------------------------------------------------------------------
    # Context Manager Support
    # -------------------------------------------------------------------------

    async def __aenter__(self) -> "IcebergAPIClient":
        """Enter async context."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context and close client."""
        await self.close()
