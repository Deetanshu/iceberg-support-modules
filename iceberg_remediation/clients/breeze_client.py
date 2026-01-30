"""
Breeze Historical API client with rate limiting.

Fetches historical index and option candles with OI data.
Uses the official Breeze API v1 historicalcharts endpoint.
"""
import asyncio
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
from typing import List, Optional
from zoneinfo import ZoneInfo

import httpx
import structlog
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from iceberg_remediation.config import Settings
from iceberg_remediation.models import BreezeCandle, IndexCandle, OptionCandle

logger = structlog.get_logger(__name__)

# Timezone constants
IST = ZoneInfo("Asia/Kolkata")
UTC = ZoneInfo("UTC")

# Breeze stock code mapping
BREEZE_SYMBOLS = {
    "nifty": {"stock_code": "NIFTY", "exchange": "NFO", "index_exchange": "NSE"},
    "banknifty": {"stock_code": "CNXBAN", "exchange": "NFO", "index_exchange": "NSE"},
    "finnifty": {"stock_code": "NIFFIN", "exchange": "NFO", "index_exchange": "NSE"},
}


class BreezeAPIError(Exception):
    """Breeze API error."""
    pass


class BreezeRateLimitError(BreezeAPIError):
    """Rate limit exceeded."""
    pass


class BreezeClient:
    """Async client for Breeze Historical API."""
    
    BASE_URL = "https://api.icicidirect.com/breezeapi/api/v1"
    
    def __init__(self, settings: Settings):
        """
        Initialize Breeze client.
        
        Args:
            settings: Application settings with Breeze credentials
        """
        self.api_key = settings.breeze_api_key
        self.api_secret = settings.breeze_api_secret
        self.session_token = settings.breeze_session_token
        self.rate_limit_delay = settings.rate_limit_delay
        self._base64_session: Optional[str] = None
        self._client: Optional[httpx.AsyncClient] = None
        self._last_request_time: float = 0
    
    async def connect(self) -> None:
        """Initialize connection and validate session."""
        self._client = httpx.AsyncClient(timeout=30.0)
        
        # Get base64 session token from customer details
        body = {"SessionToken": self.session_token, "AppKey": self.api_key}
        body_str = json.dumps(body, separators=(',', ':'))
        
        response = await self._client.request(
            "GET",
            f"{self.BASE_URL}/customerdetails",
            content=body_str,
            headers={"Content-Type": "application/json"}
        )
        
        data = response.json()
        if data.get("Status") != 200 or not data.get("Success"):
            raise BreezeAPIError(f"Session validation failed: {data}")
        
        self._base64_session = data["Success"]["session_token"]
        logger.info("breeze_client_connected")
    
    async def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
            logger.info("breeze_client_closed")

    async def _rate_limit(self) -> None:
        """Enforce rate limiting between requests."""
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_request_time
        if elapsed < self.rate_limit_delay:
            await asyncio.sleep(self.rate_limit_delay - elapsed)
        self._last_request_time = asyncio.get_event_loop().time()
    
    def _make_headers(self, body: str) -> dict:
        """Create authenticated headers for Breeze API."""
        current_date = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')
        checksum = sha256(
            (current_date + body + self.api_secret).encode("utf-8")
        ).hexdigest()
        
        return {
            "Content-Type": "application/json",
            "X-Checksum": f"token {checksum}",
            "X-Timestamp": current_date,
            "X-AppKey": self.api_key,
            "X-SessionToken": self._base64_session,
        }
    
    def _parse_breeze_timestamp(self, dt_str: str) -> datetime:
        """
        Parse Breeze timestamp to UTC datetime.
        
        Breeze returns timestamps in IST without timezone info (e.g., "2026-01-21 09:15:00").
        We need to interpret as IST and convert to UTC to match DB storage format.
        
        Args:
            dt_str: Datetime string from Breeze API
            
        Returns:
            UTC-aware datetime
        """
        # Remove any trailing Z or timezone info (Breeze is inconsistent)
        clean_str = dt_str.replace("Z", "").replace("+00:00", "").strip()
        
        # Parse as naive datetime
        try:
            naive_dt = datetime.fromisoformat(clean_str)
        except ValueError:
            # Try alternative format
            naive_dt = datetime.strptime(clean_str, "%Y-%m-%d %H:%M:%S")
        
        # Breeze returns IST timestamps - localize to IST then convert to UTC
        ist_dt = naive_dt.replace(tzinfo=IST)
        utc_dt = ist_dt.astimezone(UTC)
        
        return utc_dt
    
    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        retry=retry_if_exception_type((httpx.TimeoutException, BreezeRateLimitError)),
    )
    async def _request(self, endpoint: str, body_dict: dict) -> dict:
        """
        Make authenticated request to Breeze API.
        
        Args:
            endpoint: API endpoint (e.g., "historicalcharts")
            body_dict: Request body as dictionary
            
        Returns:
            API response data
            
        Raises:
            BreezeAPIError: On API errors
            BreezeRateLimitError: On rate limit (will retry)
        """
        await self._rate_limit()
        
        body = json.dumps(body_dict, separators=(',', ':'))
        headers = self._make_headers(body)
        
        response = await self._client.request(
            "GET",
            f"{self.BASE_URL}/{endpoint}",
            content=body,
            headers=headers
        )
        
        if not response.text:
            raise BreezeAPIError("Empty response from Breeze API")
        
        try:
            data = response.json()
        except json.JSONDecodeError:
            raise BreezeAPIError(f"Invalid JSON: {response.text[:200]}")
        
        # Check for rate limiting
        if data.get("Status") == 429:
            raise BreezeRateLimitError("Rate limit exceeded")
        
        # Check for errors
        if data.get("Status") != 200:
            error_msg = data.get("Error", data.get("Message", "Unknown error"))
            raise BreezeAPIError(f"API error: {error_msg}")
        
        return data
    
    async def get_index_candles(
        self,
        symbol: str,
        trade_date: date,
        interval: str = "5minute"
    ) -> List[IndexCandle]:
        """
        Fetch index candles for a trading day.
        
        Args:
            symbol: Index symbol (nifty, banknifty, finnifty)
            trade_date: Trading date
            interval: Candle interval (default: 5minute)
            
        Returns:
            List of IndexCandle objects
        """
        if symbol not in BREEZE_SYMBOLS:
            raise ValueError(f"Unsupported symbol: {symbol}")
        
        config = BREEZE_SYMBOLS[symbol]
        
        from_dt = trade_date.strftime('%Y-%m-%dT09:15:00.000Z')
        to_dt = trade_date.strftime('%Y-%m-%dT15:30:00.000Z')
        
        body = {
            "interval": interval,
            "from_date": from_dt,
            "to_date": to_dt,
            "stock_code": config["stock_code"],
            "exchange_code": config["index_exchange"],
            "product_type": "cash"
        }
        
        logger.debug("fetching_index_candles", symbol=symbol, date=str(trade_date))
        
        data = await self._request("historicalcharts", body)
        candles = data.get("Success", [])
        
        result = []
        for c in candles:
            try:
                # Parse datetime from Breeze format (IST -> UTC)
                dt_str = c.get("datetime", "")
                bucket_ts = self._parse_breeze_timestamp(dt_str)
                
                result.append(IndexCandle(
                    symbol=symbol,
                    bucket_ts=bucket_ts,
                    trade_date=trade_date,
                    open=Decimal(str(c.get("open", 0))),
                    high=Decimal(str(c.get("high", 0))),
                    low=Decimal(str(c.get("low", 0))),
                    close=Decimal(str(c.get("close", 0))),
                    volume=int(c.get("volume", 0)) if c.get("volume") else None,
                    tick_count=int(c.get("count", 0)) if c.get("count") else None,
                ))
            except Exception as e:
                logger.warning("candle_parse_error", error=str(e), candle=c)
        
        logger.info("index_candles_fetched", symbol=symbol, date=str(trade_date), count=len(result))
        return result

    async def get_option_candles(
        self,
        symbol: str,
        expiry: date,
        strike: Decimal,
        option_type: str,
        trade_date: date,
        interval: str = "5minute"
    ) -> List[OptionCandle]:
        """
        Fetch option candles with OI for a trading day.
        
        Args:
            symbol: Index symbol (nifty, banknifty, finnifty)
            expiry: Option expiry date
            strike: Strike price
            option_type: "CE" or "PE"
            trade_date: Trading date
            interval: Candle interval (default: 5minute)
            
        Returns:
            List of OptionCandle objects
        """
        if symbol not in BREEZE_SYMBOLS:
            raise ValueError(f"Unsupported symbol: {symbol}")
        
        config = BREEZE_SYMBOLS[symbol]
        
        # Convert option_type to Breeze format
        right = "call" if option_type == "CE" else "put"
        
        # Format expiry as DD-Mon-YYYY (e.g., "28-Jan-2026")
        expiry_str = expiry.strftime('%d-%b-%Y')
        
        from_dt = trade_date.strftime('%Y-%m-%dT09:15:00.000Z')
        to_dt = trade_date.strftime('%Y-%m-%dT15:30:00.000Z')
        
        body = {
            "interval": interval,
            "from_date": from_dt,
            "to_date": to_dt,
            "stock_code": config["stock_code"],
            "exchange_code": config["exchange"],
            "product_type": "options",
            "expiry_date": expiry_str,
            "strike_price": str(int(strike)),
            "right": right
        }
        
        logger.debug(
            "fetching_option_candles",
            symbol=symbol,
            expiry=expiry_str,
            strike=str(strike),
            option_type=option_type,
            date=str(trade_date)
        )
        
        data = await self._request("historicalcharts", body)
        candles = data.get("Success", [])
        
        result = []
        for c in candles:
            try:
                # Parse datetime from Breeze format (IST -> UTC)
                dt_str = c.get("datetime", "")
                bucket_ts = self._parse_breeze_timestamp(dt_str)
                
                # Parse OI - Breeze returns open_interest field
                oi_value = None
                if c.get("open_interest"):
                    try:
                        oi_value = int(float(c["open_interest"]))
                    except (ValueError, TypeError):
                        pass
                
                result.append(OptionCandle(
                    symbol=symbol,
                    expiry=expiry,
                    strike=strike,
                    option_type=option_type,
                    bucket_ts=bucket_ts,
                    trade_date=trade_date,
                    open=Decimal(str(c.get("open", 0))),
                    high=Decimal(str(c.get("high", 0))),
                    low=Decimal(str(c.get("low", 0))),
                    close=Decimal(str(c.get("close", 0))),
                    # Breeze only provides close OI, not OHLC for OI
                    oi_close=oi_value,
                    vol_close=int(c.get("volume", 0)) if c.get("volume") else None,
                    tick_count=int(c.get("count", 0)) if c.get("count") else None,
                ))
            except Exception as e:
                logger.warning("option_candle_parse_error", error=str(e), candle=c)
        
        logger.info(
            "option_candles_fetched",
            symbol=symbol,
            expiry=expiry_str,
            strike=str(strike),
            option_type=option_type,
            date=str(trade_date),
            count=len(result)
        )
        return result
    
    def get_supported_symbols(self) -> List[str]:
        """Get list of supported symbols."""
        return list(BREEZE_SYMBOLS.keys())
    
    def is_symbol_supported(self, symbol: str) -> bool:
        """Check if symbol is supported by Breeze."""
        return symbol.lower() in BREEZE_SYMBOLS
