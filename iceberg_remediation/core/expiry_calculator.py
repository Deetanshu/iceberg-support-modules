"""
Expiry day calculation logic.

Handles the complex NSE expiry day changes over time:
- Before Mar 2024: NIFTY=Thu, BANKNIFTY=Thu, FINNIFTY=Tue
- Mar 2024 - Dec 2024: NIFTY=Thu, BANKNIFTY=Wed, FINNIFTY=Tue
- Jan 2025 - Aug 2025: All NSE monthly=Thu
- After Aug 28, 2025: All NSE=Tue, SENSEX=Thu

Reference: iceberg_ai_exploration/exploration_24012026/05_NSE_EXPIRY_DAY_CHANGES_REFERENCE.md
"""
import calendar
from datetime import date, timedelta
from typing import Literal, Optional


class ExpiryCalculator:
    """Calculator for NSE/BSE option expiry dates."""
    
    def get_expiry_for_date(
        self,
        symbol: str,
        trade_date: date,
        mode: str = "current",
    ) -> Optional[date]:
        """
        Get the expiry date for a symbol/mode/trade_date.
        
        Args:
            symbol: Index symbol (lowercase)
            trade_date: Trading date
            mode: "current" (weekly) or "positional" (monthly)
            
        Returns:
            Expiry date, or None if not applicable
        """
        symbol = symbol.lower()
        
        # FINNIFTY only has current mode
        if symbol == "finnifty" and mode == "positional":
            return None
        
        if mode == "positional":
            return get_positional_expiry(symbol, trade_date)
        else:
            return get_current_expiry(symbol, trade_date)
    
    def get_expiry_weekday(self, symbol: str, target_date: date) -> int:
        """Get expiry weekday for symbol on date."""
        return get_expiry_weekday(symbol, target_date)
    
    def is_expiry_day(self, symbol: str, check_date: date) -> bool:
        """Check if date is an expiry day."""
        return is_expiry_day(symbol, check_date)


def get_expiry_weekday(symbol: str, target_date: date) -> int:
    """
    Returns expiry weekday (0=Mon, 1=Tue, ..., 4=Fri) for symbol on date.
    
    Args:
        symbol: Index symbol (lowercase: nifty, banknifty, finnifty, sensex)
        target_date: Date to check expiry day for
        
    Returns:
        Weekday number (0=Monday, 1=Tuesday, etc.)
    """
    symbol = symbol.lower()
    
    # After August 28, 2025 - All NSE indices expire Tuesday, SENSEX Thursday
    if target_date >= date(2025, 8, 28):
        if symbol in ('nifty', 'banknifty', 'finnifty'):
            return 1  # Tuesday
        elif symbol == 'sensex':
            return 3  # Thursday
    
    # January 1, 2025 to August 27, 2025 - All NSE monthly on Thursday
    elif target_date >= date(2025, 1, 1):
        if symbol in ('nifty', 'banknifty', 'finnifty'):
            return 3  # Thursday
        elif symbol == 'sensex':
            return 4  # Friday
    
    # March 1, 2024 to December 31, 2024
    elif target_date >= date(2024, 3, 1):
        if symbol == 'nifty':
            return 3  # Thursday
        elif symbol == 'banknifty':
            return 2  # Wednesday
        elif symbol == 'finnifty':
            return 1  # Tuesday
        elif symbol == 'sensex':
            return 4  # Friday
    
    # Before March 1, 2024
    else:
        if symbol in ('nifty', 'banknifty'):
            return 3  # Thursday
        elif symbol == 'finnifty':
            return 1  # Tuesday
        elif symbol == 'sensex':
            return 4  # Friday
    
    return 3  # Default Thursday


def find_expiry_for_date(
    symbol: str,
    target_date: date,
    expiry_type: Literal["weekly", "monthly"] = "weekly",
) -> date:
    """
    Find the expiry date for a given symbol on or after target_date.
    
    Args:
        symbol: Index symbol (lowercase)
        target_date: Date to find expiry for
        expiry_type: "weekly" for nearest expiry, "monthly" for month-end expiry
        
    Returns:
        Expiry date
    """
    expiry_weekday = get_expiry_weekday(symbol, target_date)
    
    # Find next occurrence of expiry day
    days_ahead = expiry_weekday - target_date.weekday()
    if days_ahead < 0:
        days_ahead += 7
    
    next_expiry = target_date + timedelta(days=days_ahead)
    
    if expiry_type == "monthly":
        return find_monthly_expiry(symbol, target_date.year, target_date.month)
    
    return next_expiry


def find_monthly_expiry(symbol: str, year: int, month: int) -> date:
    """
    Find the last expiry day of the month for a symbol.
    
    Args:
        symbol: Index symbol (lowercase)
        year: Year
        month: Month (1-12)
        
    Returns:
        Last expiry date in the month
    """
    # Get last day of month
    _, last_day = calendar.monthrange(year, month)
    month_end = date(year, month, last_day)
    
    # Get expiry weekday for this date
    expiry_weekday = get_expiry_weekday(symbol, month_end)
    
    # Find last occurrence of expiry weekday in month
    while month_end.weekday() != expiry_weekday:
        month_end -= timedelta(days=1)
    
    return month_end


def get_current_expiry(symbol: str, trade_date: date) -> date:
    """
    Get the current (weekly) expiry for a trade date.
    
    This is the nearest expiry on or after the trade date.
    
    Args:
        symbol: Index symbol (lowercase)
        trade_date: Trading date
        
    Returns:
        Current expiry date
    """
    return find_expiry_for_date(symbol, trade_date, "weekly")


def get_positional_expiry(symbol: str, trade_date: date) -> date:
    """
    Get the positional (monthly) expiry for a trade date.
    
    This is the last expiry of the current month.
    
    Args:
        symbol: Index symbol (lowercase)
        trade_date: Trading date
        
    Returns:
        Monthly expiry date
    """
    return find_monthly_expiry(symbol, trade_date.year, trade_date.month)


def is_expiry_day(symbol: str, check_date: date) -> bool:
    """
    Check if a date is an expiry day for the symbol.
    
    Args:
        symbol: Index symbol (lowercase)
        check_date: Date to check
        
    Returns:
        True if check_date is an expiry day
    """
    expiry_weekday = get_expiry_weekday(symbol, check_date)
    return check_date.weekday() == expiry_weekday
