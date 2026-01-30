# Data Remediation Service - Design Document

**Version:** 1.0  
**Date:** 2026-01-24  
**Status:** APPROVED FOR IMPLEMENTATION

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          LOCAL MACHINE                                   │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │                    iceberg_remediation/                             │ │
│  │                                                                     │ │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌───────────┐ │ │
│  │  │   CLI       │  │   Config    │  │   Models    │  │  Logging  │ │ │
│  │  │  (typer)    │  │  (pydantic) │  │  (pydantic) │  │ (structlog)│ │ │
│  │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └─────┬─────┘ │ │
│  │         │                │                │                │       │ │
│  │         ▼                ▼                ▼                ▼       │ │
│  │  ┌─────────────────────────────────────────────────────────────┐  │ │
│  │  │                  Remediation Engine                          │  │ │
│  │  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │  │ │
│  │  │  │  Validator  │  │  Remediator │  │ Indicator Calculator │  │  │ │
│  │  │  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘  │  │ │
│  │  └─────────┼────────────────┼────────────────────┼─────────────┘  │ │
│  │            │                │                    │                 │ │
│  │  ┌─────────▼────────────────▼────────────────────▼─────────────┐  │ │
│  │  │                    Data Access Layer                         │  │ │
│  │  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │  │ │
│  │  │  │   Breeze    │  │  PostgreSQL │  │   SQLite (Local)    │  │  │ │
│  │  │  │   Client    │  │   Client    │  │   Progress Store    │  │  │ │
│  │  │  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘  │  │ │
│  │  └─────────┼────────────────┼────────────────────┼─────────────┘  │ │
│  └────────────┼────────────────┼────────────────────┼─────────────────┘ │
│               │                │                    │                   │
└───────────────┼────────────────┼────────────────────┼───────────────────┘
                │                │                    │
                ▼                ▼                    ▼
        ┌───────────────┐ ┌───────────────┐  ┌───────────────┐
        │ Breeze API    │ │ Cloud SQL     │  │ Local SQLite  │
        │ (Historical)  │ │ PostgreSQL    │  │ (progress.db) │
        └───────────────┘ └───────────────┘  └───────────────┘
```

---

## 2. Module Structure

```
iceberg_remediation/
├── __init__.py
├── __main__.py                 # Entry point: python -m iceberg_remediation
├── cli.py                      # Typer CLI commands
├── config.py                   # Pydantic settings
├── models.py                   # Data models
│
├── clients/
│   ├── __init__.py
│   ├── breeze_client.py        # Breeze Historical API
│   ├── kite_client.py          # Kite Historical API (SENSEX only)
│   └── postgres_client.py      # Cloud SQL PostgreSQL
│
├── core/
│   ├── __init__.py
│   ├── expiry_calculator.py    # Expiry day logic
│   ├── strike_resolver.py      # Admin range + ATM fallback
│   ├── holiday_checker.py      # Market holiday lookup
│   └── progress_store.py       # SQLite progress tracking
│
├── engine/
│   ├── __init__.py
│   ├── validator.py            # Data validation
│   ├── remediator.py           # Fetch + upsert logic
│   ├── deleter.py              # Safe deletion with audit
│   └── indicator_calculator.py # Indicator recalculation
│
├── .env.example
├── requirements.txt
└── README.md
```

---

## 3. Component Design

### 3.1 Configuration (config.py)

```python
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="REMEDIATION_")
    
    # PostgreSQL (Cloud SQL)
    db_host: str = "34.180.57.7"
    db_port: int = 5432
    db_user: str = "iceberg"
    db_password: str
    db_name: str = "iceberg"
    
    # Breeze API
    breeze_api_key: str
    breeze_api_secret: str
    breeze_session_token: str  # From results/breeze_session.json
    
    # Kite API (for SENSEX)
    kite_api_key: Optional[str] = None
    kite_access_token: Optional[str] = None
    
    # Remediation settings
    default_strike_range: int = 5  # ±5 ATM if no admin range
    batch_size: int = 100
    rate_limit_delay: float = 0.3  # Seconds between requests
    
    # Local SQLite
    progress_db_path: str = "progress.db"
    
    @property
    def postgres_dsn(self) -> str:
        return f"postgresql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"
```

### 3.2 Data Models (models.py)

```python
from pydantic import BaseModel
from datetime import date, datetime
from typing import Optional, Literal
from decimal import Decimal

class IndexCandle(BaseModel):
    """Index candle data from Breeze or DB."""
    symbol: str
    bucket_ts: datetime
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Optional[int] = None

class OptionCandle(BaseModel):
    """Option candle data with OI."""
    symbol: str
    expiry: date
    strike: Decimal
    option_type: Literal["CE", "PE"]
    bucket_ts: datetime
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    oi_open: Optional[int] = None
    oi_high: Optional[int] = None
    oi_low: Optional[int] = None
    oi_close: Optional[int] = None
    vol_open: Optional[int] = None
    vol_high: Optional[int] = None
    vol_low: Optional[int] = None
    vol_close: Optional[int] = None

class StrikeRange(BaseModel):
    """Strike range from admin config or ATM calculation."""
    symbol: str
    mode: Literal["current", "positional"]
    lower_strike: Decimal
    upper_strike: Decimal
    source: Literal["admin", "atm_fallback"]

class RemediationProgress(BaseModel):
    """Progress tracking for resumability."""
    symbol: str
    trade_date: date
    mode: str
    strike: Optional[Decimal] = None
    option_type: Optional[str] = None
    status: Literal["pending", "in_progress", "completed", "failed"]
    last_bucket_ts: Optional[datetime] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
```

### 3.3 Expiry Calculator (core/expiry_calculator.py)

```python
from datetime import date, timedelta
from typing import Literal

def get_expiry_weekday(symbol: str, target_date: date) -> int:
    """
    Returns expiry weekday (0=Mon, 1=Tue, ..., 4=Fri) for symbol on date.
    
    NSE Expiry Day Timeline:
    - Before Mar 2024: NIFTY=Thu, BANKNIFTY=Thu, FINNIFTY=Tue
    - Mar 2024 - Dec 2024: NIFTY=Thu, BANKNIFTY=Wed, FINNIFTY=Tue
    - Jan 2025 - Aug 2025: All NSE monthly=Thu
    - After Aug 28, 2025: All NSE=Tue, SENSEX=Thu
    """
    # After August 28, 2025 - All NSE indices expire Tuesday
    if target_date >= date(2025, 8, 28):
        if symbol in ('nifty', 'banknifty', 'finnifty'):
            return 1  # Tuesday
        elif symbol == 'sensex':
            return 3  # Thursday
    
    # January 1, 2025 to August 27, 2025
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
    expiry_type: Literal["weekly", "monthly"] = "weekly"
) -> date:
    """Find the expiry date for a given symbol on or after target_date."""
    expiry_weekday = get_expiry_weekday(symbol, target_date)
    
    # Find next occurrence of expiry day
    days_ahead = expiry_weekday - target_date.weekday()
    if days_ahead < 0:
        days_ahead += 7
    
    next_expiry = target_date + timedelta(days=days_ahead)
    
    if expiry_type == "monthly":
        # Find last occurrence of expiry day in the month
        # Move to next month if we're past the last expiry
        month_end = date(next_expiry.year, next_expiry.month + 1, 1) - timedelta(days=1)
        if next_expiry.month == 12:
            month_end = date(next_expiry.year, 12, 31)
        
        # Find last expiry weekday in month
        last_expiry = month_end
        while last_expiry.weekday() != expiry_weekday:
            last_expiry -= timedelta(days=1)
        
        return last_expiry
    
    return next_expiry
```

### 3.4 Strike Resolver (core/strike_resolver.py)

```python
from decimal import Decimal
from datetime import date
from typing import Optional, Tuple
import asyncpg

STRIKE_INTERVALS = {
    'nifty': 50,
    'banknifty': 100,
    'finnifty': 50,
    'sensex': 100,
}

async def get_admin_range(
    conn: asyncpg.Connection,
    symbol: str,
    mode: str,
    target_date: date
) -> Optional[Tuple[Decimal, Decimal]]:
    """Query historical admin range for the given date."""
    row = await conn.fetchrow("""
        SELECT lower_strike, upper_strike
        FROM app.admin_key_ranges
        WHERE symbol = $1
          AND mode = $2
          AND is_active = true
          AND effective_from <= $3
          AND (effective_until IS NULL OR effective_until > $3)
        ORDER BY effective_from DESC
        LIMIT 1
    """, symbol, mode, target_date)
    
    if row:
        return (row['lower_strike'], row['upper_strike'])
    return None


def calculate_atm_strike(symbol: str, spot_price: float) -> int:
    """Calculate ATM strike from spot price."""
    interval = STRIKE_INTERVALS.get(symbol, 50)
    return round(spot_price / interval) * interval


def get_strike_range_fallback(
    symbol: str, 
    spot_price: float, 
    num_strikes: int = 5
) -> Tuple[int, int]:
    """Calculate ±N ATM strikes as fallback."""
    atm = calculate_atm_strike(symbol, spot_price)
    interval = STRIKE_INTERVALS.get(symbol, 50)
    lower = atm - (num_strikes * interval)
    upper = atm + (num_strikes * interval)
    return (lower, upper)


def generate_strikes(
    symbol: str, 
    lower: int, 
    upper: int
) -> list[int]:
    """Generate list of strikes within range."""
    interval = STRIKE_INTERVALS.get(symbol, 50)
    strikes = []
    current = lower
    while current <= upper:
        strikes.append(current)
        current += interval
    return strikes
```

### 3.5 Progress Store (core/progress_store.py)

```python
import aiosqlite
from datetime import date, datetime
from typing import Optional, List
from decimal import Decimal

class ProgressStore:
    """SQLite-based progress tracking for resumability."""
    
    def __init__(self, db_path: str = "progress.db"):
        self.db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None
    
    async def initialize(self):
        """Create tables if not exist."""
        self._conn = await aiosqlite.connect(self.db_path)
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS remediation_progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                trade_date DATE NOT NULL,
                mode TEXT NOT NULL,
                strike REAL,
                option_type TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                last_bucket_ts TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(run_id, symbol, trade_date, mode, strike, option_type)
            )
        """)
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS remediation_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                table_name TEXT NOT NULL,
                symbol TEXT NOT NULL,
                trade_date DATE NOT NULL,
                row_count INTEGER,
                details TEXT,
                created_at TEXT NOT NULL
            )
        """)
        await self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_progress_run 
            ON remediation_progress(run_id, status)
        """)
        await self._conn.commit()
    
    async def mark_started(
        self, 
        run_id: str, 
        symbol: str, 
        trade_date: date, 
        mode: str,
        strike: Optional[Decimal] = None,
        option_type: Optional[str] = None
    ):
        """Mark a work item as started."""
        now = datetime.now().isoformat()
        await self._conn.execute("""
            INSERT INTO remediation_progress 
            (run_id, symbol, trade_date, mode, strike, option_type, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'in_progress', ?, ?)
            ON CONFLICT(run_id, symbol, trade_date, mode, strike, option_type) 
            DO UPDATE SET status = 'in_progress', updated_at = ?
        """, (run_id, symbol, str(trade_date), mode, 
              float(strike) if strike else None, option_type, now, now, now))
        await self._conn.commit()
    
    async def mark_completed(
        self, 
        run_id: str, 
        symbol: str, 
        trade_date: date, 
        mode: str,
        strike: Optional[Decimal] = None,
        option_type: Optional[str] = None
    ):
        """Mark a work item as completed."""
        now = datetime.now().isoformat()
        await self._conn.execute("""
            UPDATE remediation_progress 
            SET status = 'completed', updated_at = ?
            WHERE run_id = ? AND symbol = ? AND trade_date = ? AND mode = ?
              AND (strike IS ? OR strike = ?)
              AND (option_type IS ? OR option_type = ?)
        """, (now, run_id, symbol, str(trade_date), mode,
              None if strike is None else float(strike),
              float(strike) if strike else None,
              None if option_type is None else option_type,
              option_type))
        await self._conn.commit()
    
    async def mark_failed(
        self, 
        run_id: str, 
        symbol: str, 
        trade_date: date, 
        mode: str,
        error: str,
        strike: Optional[Decimal] = None,
        option_type: Optional[str] = None
    ):
        """Mark a work item as failed."""
        now = datetime.now().isoformat()
        await self._conn.execute("""
            UPDATE remediation_progress 
            SET status = 'failed', error_message = ?, updated_at = ?
            WHERE run_id = ? AND symbol = ? AND trade_date = ? AND mode = ?
              AND (strike IS ? OR strike = ?)
              AND (option_type IS ? OR option_type = ?)
        """, (error, now, run_id, symbol, str(trade_date), mode,
              None if strike is None else float(strike),
              float(strike) if strike else None,
              None if option_type is None else option_type,
              option_type))
        await self._conn.commit()
    
    async def is_completed(
        self, 
        run_id: str, 
        symbol: str, 
        trade_date: date, 
        mode: str,
        strike: Optional[Decimal] = None,
        option_type: Optional[str] = None
    ) -> bool:
        """Check if work item is already completed."""
        cursor = await self._conn.execute("""
            SELECT 1 FROM remediation_progress 
            WHERE run_id = ? AND symbol = ? AND trade_date = ? AND mode = ?
              AND (strike IS ? OR strike = ?)
              AND (option_type IS ? OR option_type = ?)
              AND status = 'completed'
        """, (run_id, symbol, str(trade_date), mode,
              None if strike is None else float(strike),
              float(strike) if strike else None,
              None if option_type is None else option_type,
              option_type))
        row = await cursor.fetchone()
        return row is not None
    
    async def log_audit(
        self,
        run_id: str,
        operation: str,
        table_name: str,
        symbol: str,
        trade_date: date,
        row_count: int,
        details: Optional[str] = None
    ):
        """Log an audit entry."""
        now = datetime.now().isoformat()
        await self._conn.execute("""
            INSERT INTO remediation_audit 
            (run_id, operation, table_name, symbol, trade_date, row_count, details, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (run_id, operation, table_name, symbol, str(trade_date), row_count, details, now))
        await self._conn.commit()
    
    async def get_summary(self, run_id: str) -> dict:
        """Get summary of run progress."""
        cursor = await self._conn.execute("""
            SELECT status, COUNT(*) as count
            FROM remediation_progress
            WHERE run_id = ?
            GROUP BY status
        """, (run_id,))
        rows = await cursor.fetchall()
        return {row[0]: row[1] for row in rows}
    
    async def close(self):
        """Close database connection."""
        if self._conn:
            await self._conn.close()
```

---

## 4. Transactional Write Strategy

### 4.1 UPSERT Pattern (No DELETE)

All write operations use PostgreSQL's `INSERT ... ON CONFLICT ... DO UPDATE` to ensure:
- No data loss on retry
- Atomic updates
- Idempotent operations

```python
async def upsert_index_candle(conn: asyncpg.Connection, candle: IndexCandle):
    """Upsert index candle using ON CONFLICT."""
    await conn.execute("""
        INSERT INTO processing.candles_5m 
        (symbol, bucket_ts, trade_date, open, high, low, close, volume, tick_count, created_at, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 1, NOW(), NOW())
        ON CONFLICT (symbol, bucket_ts) DO UPDATE SET
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            volume = EXCLUDED.volume,
            updated_at = NOW()
    """, candle.symbol, candle.bucket_ts, candle.trade_date,
        candle.open, candle.high, candle.low, candle.close, candle.volume)


async def upsert_option_candle(conn: asyncpg.Connection, candle: OptionCandle):
    """Upsert option candle using ON CONFLICT."""
    await conn.execute("""
        INSERT INTO processing.option_chain_candles_5m 
        (symbol, expiry, strike, option_type, bucket_ts, trade_date,
         open, high, low, close, 
         oi_open, oi_high, oi_low, oi_close,
         vol_open, vol_high, vol_low, vol_close,
         tick_count, created_at, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 
                $11, $12, $13, $14, $15, $16, $17, $18, 1, NOW(), NOW())
        ON CONFLICT (symbol, expiry, strike, option_type, bucket_ts) DO UPDATE SET
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            oi_open = EXCLUDED.oi_open,
            oi_high = EXCLUDED.oi_high,
            oi_low = EXCLUDED.oi_low,
            oi_close = EXCLUDED.oi_close,
            vol_open = EXCLUDED.vol_open,
            vol_high = EXCLUDED.vol_high,
            vol_low = EXCLUDED.vol_low,
            vol_close = EXCLUDED.vol_close,
            updated_at = NOW()
    """, candle.symbol, candle.expiry, candle.strike, candle.option_type,
        candle.bucket_ts, candle.trade_date,
        candle.open, candle.high, candle.low, candle.close,
        candle.oi_open, candle.oi_high, candle.oi_low, candle.oi_close,
        candle.vol_open, candle.vol_high, candle.vol_low, candle.vol_close)
```

### 4.2 Batch Processing with Transactions

```python
async def remediate_batch(
    conn: asyncpg.Connection,
    candles: List[OptionCandle],
    progress_store: ProgressStore,
    run_id: str
):
    """Process a batch of candles in a single transaction."""
    async with conn.transaction():
        for candle in candles:
            await upsert_option_candle(conn, candle)
        
        # Log audit
        await progress_store.log_audit(
            run_id=run_id,
            operation="upsert",
            table_name="processing.option_chain_candles_5m",
            symbol=candles[0].symbol,
            trade_date=candles[0].trade_date,
            row_count=len(candles)
        )
```

---

## 5. Error Handling Strategy

### 5.1 Retry with Exponential Backoff

```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import httpx

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError))
)
async def fetch_with_retry(client: httpx.AsyncClient, url: str, **kwargs):
    """Fetch with automatic retry on network errors."""
    response = await client.get(url, **kwargs)
    response.raise_for_status()
    return response.json()
```

### 5.2 Rate Limit Handling

```python
class RateLimitError(Exception):
    """Raised when API rate limit is hit."""
    pass

async def handle_rate_limit(response: httpx.Response):
    """Check for rate limit and raise if hit."""
    if response.status_code == 429:
        retry_after = int(response.headers.get("Retry-After", 60))
        raise RateLimitError(f"Rate limited. Retry after {retry_after}s")
```

---

## 6. Logging Strategy

```python
import structlog

logger = structlog.get_logger()

# Configure structured logging
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
)

# Usage
logger.info("remediation_started", symbol="nifty", from_date="2026-01-15", to_date="2026-01-20")
logger.info("candle_upserted", symbol="nifty", bucket_ts="2026-01-15T09:15:00+05:30")
logger.error("api_error", symbol="nifty", error="Rate limited", retry_in=60)
```

---

## 7. Security Considerations

1. **Credentials:** Stored in `.env` file, never committed to git
2. **Database Access:** Uses parameterized queries (no SQL injection)
3. **API Keys:** Breeze session token refreshed daily
4. **Audit Trail:** All operations logged locally

---

## 8. Testing Strategy

1. **Unit Tests:** Test individual components (expiry calculator, strike resolver)
2. **Integration Tests:** Test against test database (not production)
3. **Dry-Run Validation:** Verify dry-run produces correct logs without writes
4. **Resumability Test:** Simulate interruption and verify resume

---

*Document created: 2026-01-24*
