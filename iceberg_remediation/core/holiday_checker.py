"""
Market holiday checker.

Queries app.market_holidays to skip non-trading days.
"""
from datetime import date
from typing import Optional, Set

import structlog

logger = structlog.get_logger(__name__)


class HolidayChecker:
    """Check if a date is a market holiday."""
    
    def __init__(self):
        """Initialize holiday checker."""
        self._holidays: Set[date] = set()
        self._loaded_years: Set[int] = set()
    
    async def load_holidays(self, conn, year: int) -> None:
        """
        Load holidays for a year from database.
        
        Args:
            conn: asyncpg connection
            year: Year to load holidays for
        """
        if year in self._loaded_years:
            return
        
        try:
            rows = await conn.fetch("""
                SELECT holiday_date
                FROM app.market_holidays
                WHERE EXTRACT(YEAR FROM holiday_date) = $1
            """, year)
            
            for row in rows:
                self._holidays.add(row['holiday_date'])
            
            self._loaded_years.add(year)
            logger.info("holidays_loaded", year=year, count=len(rows))
            
        except Exception as e:
            logger.warning("holidays_load_failed", year=year, error=str(e))
            # Continue without holidays - will process all weekdays
    
    def is_holiday(self, check_date: date) -> bool:
        """
        Check if a date is a market holiday.
        
        Args:
            check_date: Date to check
            
        Returns:
            True if the date is a holiday
        """
        return check_date in self._holidays
    
    def is_trading_day(self, check_date: date) -> bool:
        """
        Check if a date is a trading day (not weekend, not holiday).
        
        Args:
            check_date: Date to check
            
        Returns:
            True if the date is a trading day
        """
        # Weekend check
        if check_date.weekday() >= 5:
            return False
        
        # Holiday check
        if check_date in self._holidays:
            return False
        
        return True
    
    def get_trading_days(self, from_date: date, to_date: date) -> list[date]:
        """
        Get list of trading days in a date range.
        
        Args:
            from_date: Start date (inclusive)
            to_date: End date (inclusive)
            
        Returns:
            List of trading days
        """
        trading_days = []
        current = from_date
        
        while current <= to_date:
            if self.is_trading_day(current):
                trading_days.append(current)
            current = current.replace(day=current.day + 1) if current.day < 28 else \
                      date(current.year, current.month + 1, 1) if current.month < 12 else \
                      date(current.year + 1, 1, 1)
        
        # Simpler approach using timedelta
        from datetime import timedelta
        trading_days = []
        current = from_date
        while current <= to_date:
            if self.is_trading_day(current):
                trading_days.append(current)
            current += timedelta(days=1)
        
        return trading_days
