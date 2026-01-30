"""
Data validator for comparing DB data with Breeze.

Performs dry-run validation without modifying the database.
"""
from datetime import date
from decimal import Decimal
from typing import List, Optional, Tuple

import structlog

from iceberg_remediation.clients.breeze_client import BreezeClient
from iceberg_remediation.clients.postgres_client import PostgresClient
from iceberg_remediation.core.expiry_calculator import ExpiryCalculator
from iceberg_remediation.core.strike_resolver import StrikeResolver
from iceberg_remediation.core.holiday_checker import HolidayChecker
from iceberg_remediation.models import (
    IndexCandle,
    OptionCandle,
    ValidationResult,
)

logger = structlog.get_logger(__name__)


class Validator:
    """Validates DB data against Breeze Historical API."""
    
    # Price difference threshold (1%)
    PRICE_THRESHOLD = 0.01
    
    def __init__(
        self,
        breeze: BreezeClient,
        postgres: PostgresClient,
        expiry_calc: ExpiryCalculator,
        strike_resolver: StrikeResolver,
        holiday_checker: HolidayChecker,
    ):
        """
        Initialize validator.
        
        Args:
            breeze: Breeze API client
            postgres: PostgreSQL client
            expiry_calc: Expiry calculator
            strike_resolver: Strike range resolver
            holiday_checker: Holiday checker
        """
        self.breeze = breeze
        self.postgres = postgres
        self.expiry_calc = expiry_calc
        self.strike_resolver = strike_resolver
        self.holiday_checker = holiday_checker
    
    def _candles_differ(
        self,
        db_candle: OptionCandle,
        breeze_candle: OptionCandle,
    ) -> Tuple[bool, dict]:
        """
        Compare two candles and return differences.
        
        Args:
            db_candle: Candle from database
            breeze_candle: Candle from Breeze
            
        Returns:
            Tuple of (differs, differences_dict)
        """
        differences = {}
        
        # Price comparison with threshold
        for field in ['open', 'high', 'low', 'close']:
            db_val = getattr(db_candle, field)
            breeze_val = getattr(breeze_candle, field)
            
            if db_val and breeze_val:
                diff = abs(float(db_val) - float(breeze_val)) / float(breeze_val)
                if diff > self.PRICE_THRESHOLD:
                    differences[field] = {
                        "db": float(db_val),
                        "breeze": float(breeze_val),
                        "diff_pct": round(diff * 100, 2)
                    }
        
        # OI comparison (exact match for close)
        if breeze_candle.oi_close is not None:
            if db_candle.oi_close != breeze_candle.oi_close:
                differences["oi_close"] = {
                    "db": db_candle.oi_close,
                    "breeze": breeze_candle.oi_close
                }
        
        return len(differences) > 0, differences

    async def validate_option_candles(
        self,
        symbol: str,
        expiry: date,
        strike: Decimal,
        option_type: str,
        trade_date: date,
    ) -> List[ValidationResult]:
        """
        Validate option candles for a specific strike.
        
        Args:
            symbol: Index symbol
            expiry: Option expiry date
            strike: Strike price
            option_type: "CE" or "PE"
            trade_date: Trading date
            
        Returns:
            List of ValidationResult objects
        """
        results = []
        
        # Fetch from both sources
        db_candles = await self.postgres.get_option_candles(
            symbol, expiry, strike, option_type, trade_date
        )
        breeze_candles = await self.breeze.get_option_candles(
            symbol, expiry, strike, option_type, trade_date
        )
        
        # Index by bucket_ts for comparison
        db_by_ts = {c.bucket_ts: c for c in db_candles}
        breeze_by_ts = {c.bucket_ts: c for c in breeze_candles}
        
        # Check all Breeze candles
        for ts, breeze_candle in breeze_by_ts.items():
            db_candle = db_by_ts.get(ts)
            
            if db_candle is None:
                # Missing in DB
                results.append(ValidationResult(
                    symbol=symbol,
                    bucket_ts=ts,
                    is_valid=False,
                    differences={"status": "missing_in_db"},
                    breeze_candle=breeze_candle.model_dump(),
                    db_candle=None,
                ))
            else:
                # Compare
                differs, diffs = self._candles_differ(db_candle, breeze_candle)
                results.append(ValidationResult(
                    symbol=symbol,
                    bucket_ts=ts,
                    is_valid=not differs,
                    differences=diffs,
                    breeze_candle=breeze_candle.model_dump() if differs else None,
                    db_candle=db_candle.model_dump() if differs else None,
                ))
        
        # Check for extra candles in DB (not in Breeze)
        for ts, db_candle in db_by_ts.items():
            if ts not in breeze_by_ts:
                results.append(ValidationResult(
                    symbol=symbol,
                    bucket_ts=ts,
                    is_valid=True,  # Extra data is OK
                    differences={"status": "extra_in_db"},
                    breeze_candle=None,
                    db_candle=db_candle.model_dump(),
                ))
        
        return results
    
    async def validate_day(
        self,
        symbol: str,
        trade_date: date,
        mode: str = "current",
    ) -> dict:
        """
        Validate all option data for a trading day.
        
        Args:
            symbol: Index symbol
            trade_date: Trading date
            mode: "current" or "positional"
            
        Returns:
            Validation summary dict
        """
        summary = {
            "symbol": symbol,
            "trade_date": str(trade_date),
            "mode": mode,
            "total_strikes": 0,
            "valid_strikes": 0,
            "invalid_strikes": 0,
            "missing_candles": 0,
            "mismatched_candles": 0,
            "issues": [],
        }
        
        # Check if trading day
        if not self.holiday_checker.is_trading_day(trade_date):
            summary["skipped"] = "not_trading_day"
            return summary
        
        # Get expiry for the date
        expiry = self.expiry_calc.get_expiry_for_date(symbol, trade_date, mode)
        if not expiry:
            summary["skipped"] = "no_expiry_found"
            return summary
        
        # Get strike range
        strike_range = await self.strike_resolver.get_strike_range(
            symbol, mode, trade_date
        )
        if not strike_range:
            summary["skipped"] = "no_strike_range"
            return summary
        
        # Generate strikes
        strikes = self.strike_resolver.generate_strikes(
            symbol, strike_range.lower_strike, strike_range.upper_strike
        )
        summary["total_strikes"] = len(strikes)
        
        # Validate each strike
        for strike in strikes:
            for option_type in ["CE", "PE"]:
                try:
                    results = await self.validate_option_candles(
                        symbol, expiry, strike, option_type, trade_date
                    )
                    
                    invalid = [r for r in results if not r.is_valid]
                    if invalid:
                        summary["invalid_strikes"] += 1
                        for r in invalid:
                            if r.differences.get("status") == "missing_in_db":
                                summary["missing_candles"] += 1
                            else:
                                summary["mismatched_candles"] += 1
                            summary["issues"].append({
                                "strike": float(strike),
                                "option_type": option_type,
                                "bucket_ts": str(r.bucket_ts),
                                "differences": r.differences,
                            })
                    else:
                        summary["valid_strikes"] += 1
                        
                except Exception as e:
                    logger.error(
                        "validation_error",
                        symbol=symbol,
                        strike=str(strike),
                        option_type=option_type,
                        error=str(e)
                    )
                    summary["issues"].append({
                        "strike": float(strike),
                        "option_type": option_type,
                        "error": str(e),
                    })
        
        return summary
