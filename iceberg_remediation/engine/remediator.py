"""
Data remediator for fetching and upserting data from Breeze.

Handles the main remediation workflow with progress tracking.
"""
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import List, Optional

import structlog

from iceberg_remediation.clients.breeze_client import BreezeClient
from iceberg_remediation.clients.postgres_client import PostgresClient
from iceberg_remediation.core.expiry_calculator import ExpiryCalculator
from iceberg_remediation.core.strike_resolver import StrikeResolver
from iceberg_remediation.core.holiday_checker import HolidayChecker
from iceberg_remediation.core.progress_store import ProgressStore
from iceberg_remediation.models import RemediationSummary

logger = structlog.get_logger(__name__)


class Remediator:
    """Fetches data from Breeze and upserts to PostgreSQL."""
    
    def __init__(
        self,
        breeze: BreezeClient,
        postgres: PostgresClient,
        expiry_calc: ExpiryCalculator,
        strike_resolver: StrikeResolver,
        holiday_checker: HolidayChecker,
        progress_store: ProgressStore,
    ):
        """
        Initialize remediator.
        
        Args:
            breeze: Breeze API client
            postgres: PostgreSQL client
            expiry_calc: Expiry calculator
            strike_resolver: Strike range resolver
            holiday_checker: Holiday checker
            progress_store: Progress tracking store
        """
        self.breeze = breeze
        self.postgres = postgres
        self.expiry_calc = expiry_calc
        self.strike_resolver = strike_resolver
        self.holiday_checker = holiday_checker
        self.progress = progress_store
    
    async def remediate_strike(
        self,
        run_id: str,
        symbol: str,
        expiry: date,
        strike: Decimal,
        option_type: str,
        trade_date: date,
        dry_run: bool = False,
    ) -> dict:
        """
        Remediate a single strike for a trading day.
        
        Args:
            run_id: Unique run identifier
            symbol: Index symbol
            expiry: Option expiry date
            strike: Strike price
            option_type: "CE" or "PE"
            trade_date: Trading date
            dry_run: If True, don't write to DB
            
        Returns:
            Result dict with counts
        """
        result = {
            "strike": float(strike),
            "option_type": option_type,
            "fetched": 0,
            "inserted": 0,
            "updated": 0,
            "unchanged": 0,
            "errors": [],
        }
        
        try:
            # Fetch from Breeze
            breeze_candles = await self.breeze.get_option_candles(
                symbol, expiry, strike, option_type, trade_date
            )
            result["fetched"] = len(breeze_candles)
            
            if not breeze_candles:
                logger.debug(
                    "no_breeze_data",
                    symbol=symbol,
                    strike=str(strike),
                    option_type=option_type,
                    date=str(trade_date)
                )
                return result
            
            # Get existing DB candles
            db_candles = await self.postgres.get_option_candles(
                symbol, expiry, strike, option_type, trade_date
            )
            db_by_ts = {c.bucket_ts: c for c in db_candles}
            
            # Process each Breeze candle
            for candle in breeze_candles:
                existing = db_by_ts.get(candle.bucket_ts)
                
                if existing is None:
                    # New candle - insert
                    if not dry_run:
                        success = await self.postgres.upsert_option_candle(candle)
                        if success:
                            result["inserted"] += 1
                        else:
                            result["errors"].append(f"Insert failed: {candle.bucket_ts}")
                    else:
                        result["inserted"] += 1
                else:
                    # Existing candle - check if update needed
                    needs_update = self._needs_update(existing, candle)
                    if needs_update:
                        if not dry_run:
                            success = await self.postgres.upsert_option_candle(candle)
                            if success:
                                result["updated"] += 1
                            else:
                                result["errors"].append(f"Update failed: {candle.bucket_ts}")
                        else:
                            result["updated"] += 1
                    else:
                        result["unchanged"] += 1
            
            # Log audit
            if not dry_run and (result["inserted"] > 0 or result["updated"] > 0):
                await self.progress.log_audit(
                    run_id=run_id,
                    operation="upsert",
                    table_name="processing.option_chain_candles_5m",
                    symbol=symbol,
                    trade_date=trade_date,
                    row_count=result["inserted"] + result["updated"],
                    details=f"strike={strike}, type={option_type}, exp={expiry}"
                )
                
        except Exception as e:
            logger.error(
                "remediate_strike_error",
                symbol=symbol,
                strike=str(strike),
                option_type=option_type,
                error=str(e)
            )
            result["errors"].append(str(e))
        
        return result

    def _needs_update(self, db_candle, breeze_candle) -> bool:
        """Check if DB candle needs update from Breeze data."""
        # Update if OI is missing in DB but available in Breeze
        if breeze_candle.oi_close is not None and db_candle.oi_close is None:
            return True
        
        # Update if OI differs
        if breeze_candle.oi_close is not None and db_candle.oi_close != breeze_candle.oi_close:
            return True
        
        # Price comparison with 1% threshold
        for field in ['open', 'high', 'low', 'close']:
            db_val = getattr(db_candle, field)
            breeze_val = getattr(breeze_candle, field)
            if db_val and breeze_val:
                diff = abs(float(db_val) - float(breeze_val)) / float(breeze_val)
                if diff > 0.01:
                    return True
        
        return False
    
    async def remediate_day(
        self,
        run_id: str,
        symbol: str,
        trade_date: date,
        mode: str = "current",
        dry_run: bool = False,
    ) -> dict:
        """
        Remediate all option data for a trading day.
        
        Args:
            run_id: Unique run identifier
            symbol: Index symbol
            trade_date: Trading date
            mode: "current" or "positional"
            dry_run: If True, don't write to DB
            
        Returns:
            Day summary dict
        """
        summary = {
            "symbol": symbol,
            "trade_date": str(trade_date),
            "mode": mode,
            "dry_run": dry_run,
            "total_strikes": 0,
            "processed_strikes": 0,
            "candles_fetched": 0,
            "candles_inserted": 0,
            "candles_updated": 0,
            "candles_unchanged": 0,
            "errors": [],
        }
        
        # Check if trading day
        if not self.holiday_checker.is_trading_day(trade_date):
            summary["skipped"] = "not_trading_day"
            logger.info("skipping_non_trading_day", date=str(trade_date))
            return summary
        
        # Check if already completed
        if await self.progress.is_completed(run_id, symbol, trade_date):
            summary["skipped"] = "already_completed"
            logger.info("skipping_completed", date=str(trade_date))
            return summary
        
        # Mark as started
        await self.progress.mark_started(run_id, symbol, trade_date)
        
        try:
            # Get expiry for the date
            expiry = self.expiry_calc.get_expiry_for_date(symbol, trade_date, mode)
            if not expiry:
                summary["skipped"] = "no_expiry_found"
                await self.progress.mark_failed(run_id, symbol, trade_date, "no_expiry_found")
                return summary
            
            summary["expiry"] = str(expiry)
            
            # Get strike range
            strike_range = await self.strike_resolver.get_strike_range(
                symbol, mode, trade_date
            )
            if not strike_range:
                summary["skipped"] = "no_strike_range"
                await self.progress.mark_failed(run_id, symbol, trade_date, "no_strike_range")
                return summary
            
            summary["strike_range"] = {
                "lower": float(strike_range.lower_strike),
                "upper": float(strike_range.upper_strike),
                "source": strike_range.source,
            }
            
            # Generate strikes
            strikes = self.strike_resolver.generate_strikes(
                symbol, strike_range.lower_strike, strike_range.upper_strike
            )
            summary["total_strikes"] = len(strikes)
            
            logger.info(
                "remediating_day",
                symbol=symbol,
                date=str(trade_date),
                expiry=str(expiry),
                strikes=len(strikes),
                mode=mode,
                dry_run=dry_run
            )
            
            # Process each strike
            for strike in strikes:
                for option_type in ["CE", "PE"]:
                    result = await self.remediate_strike(
                        run_id, symbol, expiry, strike, option_type, trade_date, dry_run
                    )
                    
                    summary["candles_fetched"] += result["fetched"]
                    summary["candles_inserted"] += result["inserted"]
                    summary["candles_updated"] += result["updated"]
                    summary["candles_unchanged"] += result["unchanged"]
                    summary["errors"].extend(result["errors"])
                
                summary["processed_strikes"] += 1
            
            # Mark as completed
            await self.progress.mark_completed(run_id, symbol, trade_date)
            
            logger.info(
                "day_remediation_complete",
                symbol=symbol,
                date=str(trade_date),
                inserted=summary["candles_inserted"],
                updated=summary["candles_updated"],
                unchanged=summary["candles_unchanged"]
            )
            
        except Exception as e:
            logger.error("day_remediation_error", symbol=symbol, date=str(trade_date), error=str(e))
            summary["errors"].append(str(e))
            await self.progress.mark_failed(run_id, symbol, trade_date, str(e))
        
        return summary

    async def remediate_range(
        self,
        symbol: str,
        from_date: date,
        to_date: date,
        mode: str = "current",
        dry_run: bool = False,
        run_id: Optional[str] = None,
    ) -> RemediationSummary:
        """
        Remediate option data for a date range.
        
        Args:
            symbol: Index symbol
            from_date: Start date (inclusive)
            to_date: End date (inclusive)
            mode: "current" or "positional"
            dry_run: If True, don't write to DB
            run_id: Optional run ID (generated if not provided)
            
        Returns:
            RemediationSummary with results
        """
        if run_id is None:
            run_id = f"{symbol}_{mode}_{from_date}_{uuid.uuid4().hex[:8]}"
        
        start_time = datetime.now()
        
        # Load holidays for the date range
        years = set()
        current = from_date
        while current <= to_date:
            years.add(current.year)
            current += timedelta(days=365)
        years.add(to_date.year)
        
        async with self.postgres.pool.acquire() as conn:
            for year in years:
                await self.holiday_checker.load_holidays(conn, year)
        
        # Get trading days
        trading_days = self.holiday_checker.get_trading_days(from_date, to_date)
        
        logger.info(
            "starting_remediation",
            run_id=run_id,
            symbol=symbol,
            from_date=str(from_date),
            to_date=str(to_date),
            mode=mode,
            trading_days=len(trading_days),
            dry_run=dry_run
        )
        
        total_inserted = 0
        total_updated = 0
        completed_dates = 0
        failed_dates = 0
        all_errors = []
        
        for trade_date in trading_days:
            day_summary = await self.remediate_day(
                run_id, symbol, trade_date, mode, dry_run
            )
            
            if day_summary.get("skipped"):
                if day_summary["skipped"] not in ["not_trading_day", "already_completed"]:
                    failed_dates += 1
                    all_errors.append(f"{trade_date}: {day_summary['skipped']}")
            else:
                completed_dates += 1
                total_inserted += day_summary.get("candles_inserted", 0)
                total_updated += day_summary.get("candles_updated", 0)
                all_errors.extend(day_summary.get("errors", []))
        
        duration = (datetime.now() - start_time).total_seconds()
        
        summary = RemediationSummary(
            run_id=run_id,
            symbol=symbol,
            from_date=from_date,
            to_date=to_date,
            total_dates=len(trading_days),
            completed_dates=completed_dates,
            failed_dates=failed_dates,
            candles_validated=0,  # Not tracked in remediation mode
            candles_updated=total_updated,
            candles_inserted=total_inserted,
            errors=all_errors[:100],  # Limit errors
            duration_seconds=duration,
        )
        
        logger.info(
            "remediation_complete",
            run_id=run_id,
            symbol=symbol,
            completed=completed_dates,
            failed=failed_dates,
            inserted=total_inserted,
            updated=total_updated,
            duration_seconds=round(duration, 2)
        )
        
        return summary
