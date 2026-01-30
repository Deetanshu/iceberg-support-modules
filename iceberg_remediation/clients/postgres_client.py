"""
PostgreSQL client for reading and writing candle data.

Uses asyncpg with connection pooling for efficient database operations.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

import asyncpg
import structlog

from iceberg_remediation.config import Settings
from iceberg_remediation.models import IndexCandle, OptionCandle, StrikeRange

logger = structlog.get_logger(__name__)


class PostgresClient:
    """Async PostgreSQL client with connection pooling."""
    
    def __init__(self, settings: Settings):
        """
        Initialize PostgreSQL client.
        
        Args:
            settings: Application settings with database credentials
        """
        self.dsn = settings.postgres_dsn
        self._pool: Optional[asyncpg.Pool] = None
    
    async def connect(self) -> None:
        """Create connection pool."""
        self._pool = await asyncpg.create_pool(
            self.dsn,
            min_size=2,
            max_size=10,
            command_timeout=60
        )
        logger.info("postgres_client_connected")
    
    async def close(self) -> None:
        """Close connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("postgres_client_closed")
    
    @property
    def pool(self) -> asyncpg.Pool:
        """Get connection pool."""
        if not self._pool:
            raise RuntimeError("PostgresClient not connected")
        return self._pool
    
    # =========================================================================
    # Index Candle Operations
    # =========================================================================
    
    async def get_index_candles(
        self,
        symbol: str,
        trade_date: date
    ) -> List[IndexCandle]:
        """
        Get index candles for a trading day.
        
        Args:
            symbol: Index symbol
            trade_date: Trading date
            
        Returns:
            List of IndexCandle objects
        """
        query = """
            SELECT symbol, bucket_ts, open, high, low, close, volume, tick_count
            FROM processing.candles_5m
            WHERE symbol = $1 
              AND bucket_ts::date = $2
            ORDER BY bucket_ts
        """
        
        rows = await self.pool.fetch(query, symbol, trade_date)
        
        return [
            IndexCandle(
                symbol=row["symbol"],
                bucket_ts=row["bucket_ts"],
                trade_date=trade_date,
                open=Decimal(str(row["open"])),
                high=Decimal(str(row["high"])),
                low=Decimal(str(row["low"])),
                close=Decimal(str(row["close"])),
                volume=row["volume"],
                tick_count=row["tick_count"],
            )
            for row in rows
        ]
    
    async def upsert_index_candle(self, candle: IndexCandle) -> bool:
        """
        UPSERT an index candle.
        
        Args:
            candle: IndexCandle to upsert
            
        Returns:
            True if inserted/updated, False on error
        """
        query = """
            INSERT INTO processing.candles_5m 
                (symbol, bucket_ts, open, high, low, close, volume, tick_count)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (symbol, bucket_ts) 
            DO UPDATE SET
                open = EXCLUDED.open,
                high = EXCLUDED.high,
                low = EXCLUDED.low,
                close = EXCLUDED.close,
                volume = EXCLUDED.volume,
                tick_count = EXCLUDED.tick_count
        """
        
        try:
            await self.pool.execute(
                query,
                candle.symbol,
                candle.bucket_ts,
                float(candle.open),
                float(candle.high),
                float(candle.low),
                float(candle.close),
                candle.volume,
                candle.tick_count,
            )
            return True
        except Exception as e:
            logger.error("upsert_index_candle_failed", error=str(e), candle=candle.model_dump())
            return False

    # =========================================================================
    # Option Candle Operations
    # =========================================================================
    
    async def get_option_candles(
        self,
        symbol: str,
        expiry: date,
        strike: Decimal,
        option_type: str,
        trade_date: date
    ) -> List[OptionCandle]:
        """
        Get option candles for a trading day.
        
        Args:
            symbol: Index symbol
            expiry: Option expiry date
            strike: Strike price
            option_type: "CE" or "PE"
            trade_date: Trading date
            
        Returns:
            List of OptionCandle objects
        """
        query = """
            SELECT symbol, expiry, strike, option_type, bucket_ts,
                   open, high, low, close,
                   oi_open, oi_high, oi_low, oi_close,
                   vol_open, vol_high, vol_low, vol_close,
                   tick_count
            FROM processing.option_chain_candles_5m
            WHERE symbol = $1 
              AND expiry = $2
              AND strike = $3
              AND option_type = $4
              AND bucket_ts::date = $5
            ORDER BY bucket_ts
        """
        
        rows = await self.pool.fetch(
            query, symbol, expiry, float(strike), option_type, trade_date
        )
        
        return [
            OptionCandle(
                symbol=row["symbol"],
                expiry=row["expiry"],
                strike=Decimal(str(row["strike"])),
                option_type=row["option_type"],
                bucket_ts=row["bucket_ts"],
                trade_date=trade_date,
                open=Decimal(str(row["open"])),
                high=Decimal(str(row["high"])),
                low=Decimal(str(row["low"])),
                close=Decimal(str(row["close"])),
                oi_open=row["oi_open"],
                oi_high=row["oi_high"],
                oi_low=row["oi_low"],
                oi_close=row["oi_close"],
                vol_open=row["vol_open"],
                vol_high=row["vol_high"],
                vol_low=row["vol_low"],
                vol_close=row["vol_close"],
                tick_count=row["tick_count"],
            )
            for row in rows
        ]
    
    async def upsert_option_candle(self, candle: OptionCandle) -> bool:
        """
        UPSERT an option candle.
        
        Args:
            candle: OptionCandle to upsert
            
        Returns:
            True if inserted/updated, False on error
        """
        query = """
            INSERT INTO processing.option_chain_candles_5m 
                (symbol, expiry, strike, option_type, bucket_ts, trade_date,
                 open, high, low, close,
                 oi_open, oi_high, oi_low, oi_close,
                 vol_open, vol_high, vol_low, vol_close,
                 tick_count)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19)
            ON CONFLICT (symbol, expiry, strike, option_type, bucket_ts) 
            DO UPDATE SET
                open = EXCLUDED.open,
                high = EXCLUDED.high,
                low = EXCLUDED.low,
                close = EXCLUDED.close,
                oi_open = COALESCE(EXCLUDED.oi_open, processing.option_chain_candles_5m.oi_open),
                oi_high = COALESCE(EXCLUDED.oi_high, processing.option_chain_candles_5m.oi_high),
                oi_low = COALESCE(EXCLUDED.oi_low, processing.option_chain_candles_5m.oi_low),
                oi_close = COALESCE(EXCLUDED.oi_close, processing.option_chain_candles_5m.oi_close),
                vol_open = COALESCE(EXCLUDED.vol_open, processing.option_chain_candles_5m.vol_open),
                vol_high = COALESCE(EXCLUDED.vol_high, processing.option_chain_candles_5m.vol_high),
                vol_low = COALESCE(EXCLUDED.vol_low, processing.option_chain_candles_5m.vol_low),
                vol_close = COALESCE(EXCLUDED.vol_close, processing.option_chain_candles_5m.vol_close),
                tick_count = COALESCE(EXCLUDED.tick_count, processing.option_chain_candles_5m.tick_count)
        """
        
        try:
            await self.pool.execute(
                query,
                candle.symbol,
                candle.expiry,
                float(candle.strike),
                candle.option_type,
                candle.bucket_ts,
                candle.trade_date,
                float(candle.open),
                float(candle.high),
                float(candle.low),
                float(candle.close),
                candle.oi_open,
                candle.oi_high,
                candle.oi_low,
                candle.oi_close,
                candle.vol_open,
                candle.vol_high,
                candle.vol_low,
                candle.vol_close,
                candle.tick_count,
            )
            return True
        except Exception as e:
            logger.error("upsert_option_candle_failed", error=str(e), candle=candle.model_dump())
            return False

    # =========================================================================
    # Admin Strike Range Operations
    # =========================================================================
    
    async def get_admin_range(
        self,
        symbol: str,
        mode: str,
        target_date: date
    ) -> Optional[StrikeRange]:
        """
        Get historical admin strike range for a date.
        
        Args:
            symbol: Index symbol
            mode: "current" or "positional"
            target_date: Date to get range for
            
        Returns:
            StrikeRange if found, None otherwise
        """
        query = """
            SELECT symbol, mode, lower_strike, upper_strike, effective_from, effective_until
            FROM app.admin_key_ranges
            WHERE symbol = $1 
              AND mode = $2
              AND effective_from <= $3
              AND (effective_until IS NULL OR effective_until >= $3)
            ORDER BY effective_from DESC
            LIMIT 1
        """
        
        row = await self.pool.fetchrow(query, symbol, mode, target_date)
        
        if not row:
            return None
        
        return StrikeRange(
            symbol=row["symbol"],
            mode=row["mode"],
            lower_strike=Decimal(str(row["lower_strike"])),
            upper_strike=Decimal(str(row["upper_strike"])),
            source="admin",
            effective_from=row["effective_from"],
        )
    
    async def get_index_close(
        self,
        symbol: str,
        trade_date: date
    ) -> Optional[Decimal]:
        """
        Get index closing price for ATM calculation.
        
        Args:
            symbol: Index symbol
            trade_date: Trading date
            
        Returns:
            Closing price if found, None otherwise
        """
        query = """
            SELECT close
            FROM processing.candles_5m
            WHERE symbol = $1 
              AND bucket_ts::date = $2
            ORDER BY bucket_ts DESC
            LIMIT 1
        """
        
        row = await self.pool.fetchrow(query, symbol, trade_date)
        
        if not row:
            return None
        
        return Decimal(str(row["close"]))
    
    # =========================================================================
    # Holiday Operations
    # =========================================================================
    
    async def get_holidays(self, year: int) -> List[date]:
        """
        Get market holidays for a year.
        
        Args:
            year: Year to get holidays for
            
        Returns:
            List of holiday dates
        """
        query = """
            SELECT holiday_date
            FROM app.market_holidays
            WHERE EXTRACT(YEAR FROM holiday_date) = $1
            ORDER BY holiday_date
        """
        
        rows = await self.pool.fetch(query, year)
        return [row["holiday_date"] for row in rows]
    
    # =========================================================================
    # Validation Queries
    # =========================================================================
    
    async def count_option_candles(
        self,
        symbol: str,
        expiry: date,
        trade_date: date
    ) -> int:
        """
        Count option candles for a symbol/expiry/date.
        
        Args:
            symbol: Index symbol
            expiry: Option expiry date
            trade_date: Trading date
            
        Returns:
            Count of candles
        """
        query = """
            SELECT COUNT(*) as cnt
            FROM processing.option_chain_candles_5m
            WHERE symbol = $1 
              AND expiry = $2
              AND bucket_ts::date = $3
        """
        
        row = await self.pool.fetchrow(query, symbol, expiry, trade_date)
        return row["cnt"] if row else 0
    
    async def get_distinct_strikes(
        self,
        symbol: str,
        expiry: date,
        trade_date: date
    ) -> List[Decimal]:
        """
        Get distinct strikes for a symbol/expiry/date.
        
        Args:
            symbol: Index symbol
            expiry: Option expiry date
            trade_date: Trading date
            
        Returns:
            List of distinct strike prices
        """
        query = """
            SELECT DISTINCT strike
            FROM processing.option_chain_candles_5m
            WHERE symbol = $1 
              AND expiry = $2
              AND bucket_ts::date = $3
            ORDER BY strike
        """
        
        rows = await self.pool.fetch(query, symbol, expiry, trade_date)
        return [Decimal(str(row["strike"])) for row in rows]
    
    async def check_oi_data_exists(
        self,
        symbol: str,
        expiry: date,
        trade_date: date
    ) -> bool:
        """
        Check if OI data exists for a symbol/expiry/date.
        
        Args:
            symbol: Index symbol
            expiry: Option expiry date
            trade_date: Trading date
            
        Returns:
            True if OI data exists
        """
        query = """
            SELECT EXISTS(
                SELECT 1
                FROM processing.option_chain_candles_5m
                WHERE symbol = $1 
                  AND expiry = $2
                  AND bucket_ts::date = $3
                  AND oi_close IS NOT NULL
                  AND oi_close > 0
            ) as has_oi
        """
        
        row = await self.pool.fetchrow(query, symbol, expiry, trade_date)
        return row["has_oi"] if row else False
