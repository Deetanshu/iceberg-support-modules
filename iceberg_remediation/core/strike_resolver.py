"""
Strike range resolution logic.

Resolves strike ranges from:
1. Historical admin ranges (app.admin_key_ranges)
2. ATM fallback (±N strikes from spot price)
"""
from datetime import date
from decimal import Decimal
from typing import List, Optional, Tuple, TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from iceberg_remediation.clients.postgres_client import PostgresClient

from iceberg_remediation.models import StrikeRange

logger = structlog.get_logger(__name__)

# Strike intervals per symbol
STRIKE_INTERVALS = {
    'nifty': 50,
    'banknifty': 100,
    'finnifty': 50,
    'sensex': 100,
}


class StrikeResolver:
    """Resolves strike ranges from admin config or ATM fallback."""
    
    def __init__(self, postgres: "PostgresClient", default_num_strikes: int = 5):
        """
        Initialize strike resolver.
        
        Args:
            postgres: PostgreSQL client for admin range lookup
            default_num_strikes: Default ±N strikes for ATM fallback
        """
        self.postgres = postgres
        self.default_num_strikes = default_num_strikes
    
    async def get_strike_range(
        self,
        symbol: str,
        mode: str,
        target_date: date,
    ) -> Optional[StrikeRange]:
        """
        Get strike range for a symbol/mode/date.
        
        First tries admin range, then falls back to ATM calculation.
        
        Args:
            symbol: Index symbol (lowercase)
            mode: "current" or "positional"
            target_date: Date to get range for
            
        Returns:
            StrikeRange if found/calculated, None otherwise
        """
        # Try admin range first
        admin_range = await self.postgres.get_admin_range(symbol, mode, target_date)
        if admin_range:
            logger.debug(
                "using_admin_range",
                symbol=symbol,
                mode=mode,
                date=str(target_date),
                lower=float(admin_range.lower_strike),
                upper=float(admin_range.upper_strike)
            )
            return admin_range
        
        # Fallback to ATM calculation
        spot_price = await self.postgres.get_index_close(symbol, target_date)
        if spot_price is None:
            logger.warning(
                "no_spot_price_for_atm",
                symbol=symbol,
                date=str(target_date)
            )
            return None
        
        lower, upper = get_strike_range_fallback(
            symbol, float(spot_price), self.default_num_strikes
        )
        
        logger.debug(
            "using_atm_fallback",
            symbol=symbol,
            mode=mode,
            date=str(target_date),
            spot=float(spot_price),
            lower=lower,
            upper=upper
        )
        
        return StrikeRange(
            symbol=symbol,
            mode=mode,
            lower_strike=Decimal(lower),
            upper_strike=Decimal(upper),
            source="atm_fallback",
        )
    
    def generate_strikes(
        self,
        symbol: str,
        lower: Decimal,
        upper: Decimal,
    ) -> List[Decimal]:
        """
        Generate list of strikes within range.
        
        Args:
            symbol: Index symbol (lowercase)
            lower: Lower strike bound
            upper: Upper strike bound
            
        Returns:
            List of strike prices as Decimal
        """
        strikes = generate_strikes(symbol, int(lower), int(upper))
        return [Decimal(s) for s in strikes]


def calculate_atm_strike(symbol: str, spot_price: float) -> int:
    """
    Calculate ATM strike from spot price.
    
    Args:
        symbol: Index symbol (lowercase)
        spot_price: Current spot price
        
    Returns:
        ATM strike price (rounded to nearest interval)
    """
    interval = STRIKE_INTERVALS.get(symbol.lower(), 50)
    return round(spot_price / interval) * interval


def get_strike_range_fallback(
    symbol: str,
    spot_price: float,
    num_strikes: int = 5,
) -> Tuple[int, int]:
    """
    Calculate ±N ATM strikes as fallback when no admin range exists.
    
    Args:
        symbol: Index symbol (lowercase)
        spot_price: Current spot price
        num_strikes: Number of strikes on each side of ATM
        
    Returns:
        Tuple of (lower_strike, upper_strike)
    """
    atm = calculate_atm_strike(symbol, spot_price)
    interval = STRIKE_INTERVALS.get(symbol.lower(), 50)
    lower = atm - (num_strikes * interval)
    upper = atm + (num_strikes * interval)
    return (lower, upper)


def generate_strikes(
    symbol: str,
    lower: int,
    upper: int,
) -> List[int]:
    """
    Generate list of strikes within range.
    
    Args:
        symbol: Index symbol (lowercase)
        lower: Lower strike bound
        upper: Upper strike bound
        
    Returns:
        List of strike prices
    """
    interval = STRIKE_INTERVALS.get(symbol.lower(), 50)
    strikes = []
    current = lower
    while current <= upper:
        strikes.append(current)
        current += interval
    return strikes


def normalize_strike(symbol: str, strike: float) -> int:
    """
    Normalize a strike price to the nearest valid strike.
    
    Args:
        symbol: Index symbol (lowercase)
        strike: Strike price to normalize
        
    Returns:
        Normalized strike price
    """
    interval = STRIKE_INTERVALS.get(symbol.lower(), 50)
    return round(strike / interval) * interval
