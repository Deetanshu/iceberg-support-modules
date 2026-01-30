"""
CLI for the Iceberg Data Remediation Tool.

Commands:
- validate: Dry-run validation against Breeze
- remediate: Fetch and upsert data from Breeze
- status: Show remediation progress
- reset: Reset progress tracking
"""
import asyncio
import json
from datetime import date, datetime
from typing import Optional

import structlog
import typer

from iceberg_remediation.config import get_settings
from iceberg_remediation.clients.breeze_client import BreezeClient
from iceberg_remediation.clients.postgres_client import PostgresClient
from iceberg_remediation.core.expiry_calculator import ExpiryCalculator
from iceberg_remediation.core.strike_resolver import StrikeResolver
from iceberg_remediation.core.holiday_checker import HolidayChecker
from iceberg_remediation.core.progress_store import ProgressStore
from iceberg_remediation.engine.validator import Validator
from iceberg_remediation.engine.remediator import Remediator

# Configure logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

app = typer.Typer(
    name="iceberg-remediation",
    help="Iceberg Data Remediation Tool - Fix historical option data using Breeze API"
)


def parse_date(date_str: str) -> date:
    """Parse date string in YYYY-MM-DD format."""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise typer.BadParameter(f"Invalid date format: {date_str}. Use YYYY-MM-DD")


async def create_clients():
    """Create and connect all clients."""
    settings = get_settings()
    
    breeze = BreezeClient(settings)
    postgres = PostgresClient(settings)
    progress = ProgressStore(settings.progress_db_path)
    
    await breeze.connect()
    await postgres.connect()
    await progress.initialize()
    
    return breeze, postgres, progress, settings


async def cleanup_clients(breeze, postgres, progress):
    """Close all client connections."""
    await breeze.close()
    await postgres.close()
    await progress.close()


@app.command()
def validate(
    symbol: str = typer.Option(..., "--symbol", "-s", help="Symbol to validate (nifty, banknifty, finnifty)"),
    from_date: str = typer.Option(..., "--from", "-f", help="Start date (YYYY-MM-DD)"),
    to_date: str = typer.Option(..., "--to", "-t", help="End date (YYYY-MM-DD)"),
    mode: str = typer.Option("current", "--mode", "-m", help="Mode: current or positional"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output file for results (JSON)"),
):
    """
    Validate data against Breeze (dry run).
    
    Compares existing database data with Breeze Historical API
    without making any changes.
    """
    from_dt = parse_date(from_date)
    to_dt = parse_date(to_date)
    
    if from_dt > to_dt:
        raise typer.BadParameter("from_date must be before to_date")
    
    if symbol.lower() not in ["nifty", "banknifty", "finnifty"]:
        raise typer.BadParameter(f"Unsupported symbol: {symbol}")
    
    if mode not in ["current", "positional"]:
        raise typer.BadParameter(f"Invalid mode: {mode}. Use 'current' or 'positional'")
    
    # FINNIFTY only has current mode
    if symbol.lower() == "finnifty" and mode == "positional":
        typer.echo("Warning: FINNIFTY only has current mode. Switching to current.")
        mode = "current"
    
    async def run():
        breeze, postgres, progress, settings = await create_clients()
        
        try:
            expiry_calc = ExpiryCalculator()
            strike_resolver = StrikeResolver(postgres, settings.default_strike_range)
            holiday_checker = HolidayChecker()
            
            # Load holidays
            async with postgres.pool.acquire() as conn:
                await holiday_checker.load_holidays(conn, from_dt.year)
                if from_dt.year != to_dt.year:
                    await holiday_checker.load_holidays(conn, to_dt.year)
            
            validator = Validator(
                breeze, postgres, expiry_calc, strike_resolver, holiday_checker
            )
            
            results = []
            current = from_dt
            while current <= to_dt:
                if holiday_checker.is_trading_day(current):
                    typer.echo(f"Validating {symbol} {current}...")
                    day_result = await validator.validate_day(symbol.lower(), current, mode)
                    results.append(day_result)
                    
                    # Print summary
                    if day_result.get("skipped"):
                        typer.echo(f"  Skipped: {day_result['skipped']}")
                    else:
                        typer.echo(f"  Valid: {day_result['valid_strikes']}, Invalid: {day_result['invalid_strikes']}")
                        typer.echo(f"  Missing: {day_result['missing_candles']}, Mismatched: {day_result['mismatched_candles']}")
                
                current = current.replace(day=current.day + 1) if current.day < 28 else \
                          date(current.year, current.month + 1, 1) if current.month < 12 else \
                          date(current.year + 1, 1, 1)
            
            # Save results
            if output:
                with open(output, 'w') as f:
                    json.dump(results, f, indent=2, default=str)
                typer.echo(f"\nResults saved to {output}")
            
            # Summary
            total_invalid = sum(r.get("invalid_strikes", 0) for r in results)
            total_missing = sum(r.get("missing_candles", 0) for r in results)
            typer.echo(f"\nTotal: {len(results)} days, {total_invalid} invalid strikes, {total_missing} missing candles")
            
        finally:
            await cleanup_clients(breeze, postgres, progress)
    
    asyncio.run(run())


@app.command()
def remediate(
    symbol: str = typer.Option(..., "--symbol", "-s", help="Symbol to remediate (nifty, banknifty, finnifty)"),
    from_date: str = typer.Option(..., "--from", "-f", help="Start date (YYYY-MM-DD)"),
    to_date: str = typer.Option(..., "--to", "-t", help="End date (YYYY-MM-DD)"),
    mode: str = typer.Option("current", "--mode", "-m", help="Mode: current or positional"),
    dry_run: bool = typer.Option(False, "--dry-run", "-d", help="Preview without writing to DB"),
    run_id: Optional[str] = typer.Option(None, "--run-id", "-r", help="Custom run ID for resumability"),
):
    """
    Remediate data from Breeze.
    
    Fetches historical option data from Breeze and upserts to PostgreSQL.
    Use --dry-run to preview changes without writing.
    """
    from_dt = parse_date(from_date)
    to_dt = parse_date(to_date)
    
    if from_dt > to_dt:
        raise typer.BadParameter("from_date must be before to_date")
    
    if symbol.lower() not in ["nifty", "banknifty", "finnifty"]:
        raise typer.BadParameter(f"Unsupported symbol: {symbol}")
    
    if mode not in ["current", "positional"]:
        raise typer.BadParameter(f"Invalid mode: {mode}. Use 'current' or 'positional'")
    
    # FINNIFTY only has current mode
    if symbol.lower() == "finnifty" and mode == "positional":
        typer.echo("Warning: FINNIFTY only has current mode. Switching to current.")
        mode = "current"
    
    async def run():
        breeze, postgres, progress, settings = await create_clients()
        
        try:
            expiry_calc = ExpiryCalculator()
            strike_resolver = StrikeResolver(postgres, settings.default_strike_range)
            holiday_checker = HolidayChecker()
            
            remediator = Remediator(
                breeze, postgres, expiry_calc, strike_resolver, holiday_checker, progress
            )
            
            typer.echo(f"Starting remediation for {symbol} from {from_dt} to {to_dt}")
            typer.echo(f"Mode: {mode}, Dry run: {dry_run}")
            
            summary = await remediator.remediate_range(
                symbol.lower(), from_dt, to_dt, mode, dry_run, run_id
            )
            
            # Print summary
            typer.echo("\n" + "=" * 50)
            typer.echo("REMEDIATION SUMMARY")
            typer.echo("=" * 50)
            typer.echo(f"Run ID: {summary.run_id}")
            typer.echo(f"Symbol: {summary.symbol}")
            typer.echo(f"Date Range: {summary.from_date} to {summary.to_date}")
            typer.echo(f"Total Trading Days: {summary.total_dates}")
            typer.echo(f"Completed: {summary.completed_dates}")
            typer.echo(f"Failed: {summary.failed_dates}")
            typer.echo(f"Candles Inserted: {summary.candles_inserted}")
            typer.echo(f"Candles Updated: {summary.candles_updated}")
            typer.echo(f"Duration: {summary.duration_seconds:.2f} seconds")
            
            if summary.errors:
                typer.echo(f"\nErrors ({len(summary.errors)}):")
                for err in summary.errors[:10]:
                    typer.echo(f"  - {err}")
                if len(summary.errors) > 10:
                    typer.echo(f"  ... and {len(summary.errors) - 10} more")
            
        finally:
            await cleanup_clients(breeze, postgres, progress)
    
    asyncio.run(run())


@app.command()
def status(
    run_id: Optional[str] = typer.Option(None, "--run-id", "-r", help="Specific run ID to check"),
):
    """
    Show remediation progress.
    
    Displays status of current or specified remediation run.
    """
    async def run():
        settings = get_settings()
        progress = ProgressStore(settings.progress_db_path)
        await progress.initialize()
        
        try:
            if run_id:
                summary = await progress.get_summary(run_id)
                typer.echo(f"\nRun: {run_id}")
                typer.echo(f"Status: {json.dumps(summary, indent=2)}")
                
                failed = await progress.get_failed_items(run_id)
                if failed:
                    typer.echo(f"\nFailed items ({len(failed)}):")
                    for item in failed[:10]:
                        typer.echo(f"  - {item['symbol']} {item['trade_date']}: {item['error_message']}")
            else:
                typer.echo("Use --run-id to check a specific run")
                typer.echo("Run IDs are shown when starting remediation")
                
        finally:
            await progress.close()
    
    asyncio.run(run())


@app.command()
def reset(
    run_id: str = typer.Option(..., "--run-id", "-r", help="Run ID to reset"),
    confirm: bool = typer.Option(False, "--confirm", "-y", help="Confirm reset"),
):
    """
    Reset progress for a run.
    
    Clears all progress tracking for the specified run ID,
    allowing it to be re-run from scratch.
    """
    if not confirm:
        typer.echo("This will delete all progress for the run.")
        typer.echo("Use --confirm to proceed.")
        raise typer.Exit(1)
    
    async def run():
        settings = get_settings()
        progress = ProgressStore(settings.progress_db_path)
        await progress.initialize()
        
        try:
            count = await progress.reset_run(run_id)
            typer.echo(f"Reset {count} progress entries for run: {run_id}")
        finally:
            await progress.close()
    
    asyncio.run(run())


@app.command()
def list_symbols():
    """
    List supported symbols.
    
    Shows all symbols that can be remediated using Breeze API.
    """
    typer.echo("\nSupported Symbols:")
    typer.echo("  nifty     - NIFTY 50 Index (current + positional)")
    typer.echo("  banknifty - Bank NIFTY Index (current + positional)")
    typer.echo("  finnifty  - NIFTY Financial Services (current only)")
    typer.echo("\nNote: SENSEX is not supported by Breeze API")


if __name__ == "__main__":
    app()
