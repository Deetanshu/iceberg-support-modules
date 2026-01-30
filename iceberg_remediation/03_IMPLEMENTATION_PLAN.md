# Data Remediation Service - Implementation Plan

**Version:** 1.0  
**Date:** 2026-01-24  
**Status:** READY FOR IMPLEMENTATION

---

## 1. Implementation Phases

### Phase 1: Foundation (Day 1)
- [x] Create folder structure
- [x] Set up configuration with Pydantic
- [x] Implement progress store (SQLite)
- [x] Implement logging setup

### Phase 2: Data Access Layer (Day 1-2)
- [x] Implement Breeze client with rate limiting
- [x] Implement PostgreSQL client with connection pooling
- [x] Implement holiday checker

### Phase 3: Core Logic (Day 2-3)
- [x] Implement expiry calculator
- [x] Implement strike resolver
- [x] Implement validator
- [x] Implement remediator with UPSERT

### Phase 4: CLI & Integration (Day 3-4)
- [x] Implement CLI commands
- [ ] Integration testing
- [x] Documentation

---

## 2. File Implementation Order


### 2.1 Phase 1 Files

| Order | File | Purpose | Dependencies |
|-------|------|---------|--------------|
| 1 | `__init__.py` | Package marker | None |
| 2 | `config.py` | Settings management | pydantic-settings |
| 3 | `models.py` | Data models | pydantic |
| 4 | `core/progress_store.py` | SQLite progress tracking | aiosqlite |
| 5 | `__main__.py` | Entry point | cli.py |

### 2.2 Phase 2 Files

| Order | File | Purpose | Dependencies |
|-------|------|---------|--------------|
| 6 | `clients/breeze_client.py` | Breeze Historical API | httpx, tenacity |
| 7 | `clients/postgres_client.py` | PostgreSQL operations | asyncpg |
| 8 | `core/holiday_checker.py` | Market holiday lookup | postgres_client |

### 2.3 Phase 3 Files

| Order | File | Purpose | Dependencies |
|-------|------|---------|--------------|
| 9 | `core/expiry_calculator.py` | Expiry day logic | None |
| 10 | `core/strike_resolver.py` | Strike range resolution | postgres_client |
| 11 | `engine/validator.py` | Data validation | breeze_client, postgres_client |
| 12 | `engine/remediator.py` | Fetch + upsert | All above |
| 13 | `engine/deleter.py` | Safe deletion | postgres_client, progress_store |

### 2.4 Phase 4 Files

| Order | File | Purpose | Dependencies |
|-------|------|---------|--------------|
| 14 | `engine/indicator_calculator.py` | Indicator recalc | postgres_client |
| 15 | `cli.py` | CLI commands | All above |
| 16 | `README.md` | Documentation | None |

---

## 3. Detailed Implementation

### 3.1 File: `__init__.py`

```python
"""Iceberg Data Remediation Service."""
__version__ = "1.0.0"
```

### 3.2 File: `__main__.py`

```python
"""Entry point for python -m iceberg_remediation."""
from iceberg_remediation.cli import app

if __name__ == "__main__":
    app()
```

### 3.3 File: `config.py`

```python
"""Configuration management using Pydantic settings."""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
from functools import lru_cache

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="REMEDIATION_",
        case_sensitive=False
    )
    
    # PostgreSQL (Cloud SQL)
    db_host: str = "34.180.57.7"
    db_port: int = 5432
    db_user: str = "iceberg"
    db_password: str
    db_name: str = "iceberg"
    
    # Breeze API
    breeze_api_key: str
    breeze_api_secret: str
    breeze_session_token: str
    
    # Kite API (for SENSEX)
    kite_api_key: Optional[str] = None
    kite_access_token: Optional[str] = None
    
    # Remediation settings
    default_strike_range: int = 5
    batch_size: int = 100
    rate_limit_delay: float = 0.3
    max_retries: int = 5
    
    # Local SQLite
    progress_db_path: str = "progress.db"
    
    # Logging
    log_level: str = "INFO"
    log_format: str = "json"
    
    @property
    def postgres_dsn(self) -> str:
        return f"postgresql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"

@lru_cache()
def get_settings() -> Settings:
    return Settings()
```

---

## 4. Breeze Client Implementation

### 4.1 File: `clients/breeze_client.py`

Key methods:
- `get_index_candles(symbol, date, interval)` - Fetch index OHLCV
- `get_option_candles(symbol, expiry, strike, right, date, interval)` - Fetch option OHLCV+OI
- `_make_request(endpoint, body)` - Low-level API call with rate limiting

### 4.2 Breeze API Mapping

| Symbol | Stock Code | Exchange | Product Type |
|--------|------------|----------|--------------|
| nifty | NIFTY | NSE (index), NFO (options) | cash / options |
| banknifty | CNXBAN | NSE (index), NFO (options) | cash / options |
| finnifty | NIFFIN | NSE (index), NFO (options) | cash / options |

### 4.3 Request Format

```python
# Index candles
body = {
    "interval": "5minute",
    "from_date": "2026-01-15T09:15:00.000Z",
    "to_date": "2026-01-15T15:30:00.000Z",
    "stock_code": "NIFTY",
    "exchange_code": "NSE",
    "product_type": "cash"
}

# Option candles
body = {
    "interval": "5minute",
    "from_date": "2026-01-15T09:15:00.000Z",
    "to_date": "2026-01-15T15:30:00.000Z",
    "stock_code": "NIFTY",
    "exchange_code": "NFO",
    "product_type": "options",
    "expiry_date": "28-Jan-2026",
    "strike_price": "25000",
    "right": "call"
}
```

---

## 5. PostgreSQL Client Implementation

### 5.1 File: `clients/postgres_client.py`

Key methods:
- `get_index_candles(symbol, date)` - Read existing candles
- `get_option_candles(symbol, expiry, strike, option_type, date)` - Read existing option candles
- `upsert_index_candle(candle)` - UPSERT index candle
- `upsert_option_candle(candle)` - UPSERT option candle
- `get_admin_range(symbol, mode, date)` - Get historical admin range
- `get_holidays(year)` - Get market holidays

### 5.2 Connection Pooling

```python
import asyncpg

class PostgresClient:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self._pool: Optional[asyncpg.Pool] = None
    
    async def connect(self):
        self._pool = await asyncpg.create_pool(
            self.dsn,
            min_size=2,
            max_size=10,
            command_timeout=60
        )
    
    async def close(self):
        if self._pool:
            await self._pool.close()
```

---

## 6. Remediator Implementation

### 6.1 File: `engine/remediator.py`

Main workflow:
1. Get date range to process
2. For each trading day:
   a. Skip if already completed (check progress store)
   b. Get strike range (admin or ATM fallback)
   c. Get expiry for the date
   d. For each strike in range:
      - Fetch from Breeze
      - Compare with DB
      - UPSERT if different
      - Mark progress
3. Generate summary report

### 6.2 Comparison Logic

```python
def candles_differ(db_candle: OptionCandle, breeze_candle: OptionCandle, threshold: float = 0.01) -> bool:
    """Check if candles differ beyond threshold."""
    # Price comparison (allow 1% tolerance)
    for field in ['open', 'high', 'low', 'close']:
        db_val = getattr(db_candle, field)
        breeze_val = getattr(breeze_candle, field)
        if db_val and breeze_val:
            diff = abs(float(db_val) - float(breeze_val)) / float(breeze_val)
            if diff > threshold:
                return True
    
    # OI comparison (exact match required)
    if db_candle.oi_close != breeze_candle.oi_close:
        return True
    
    return False
```

---

## 7. CLI Implementation

### 7.1 File: `cli.py`

```python
import typer
from datetime import date
from typing import Optional

app = typer.Typer(help="Iceberg Data Remediation Tool")

@app.command()
def validate(
    symbol: str = typer.Option(..., help="Symbol to validate"),
    from_date: str = typer.Option(..., help="Start date (YYYY-MM-DD)"),
    to_date: str = typer.Option(..., help="End date (YYYY-MM-DD)"),
    mode: str = typer.Option("current", help="Mode: current or positional")
):
    """Validate data against Breeze (dry run)."""
    ...

@app.command()
def remediate(
    symbol: str = typer.Option(..., help="Symbol to remediate"),
    from_date: str = typer.Option(..., help="Start date (YYYY-MM-DD)"),
    to_date: str = typer.Option(..., help="End date (YYYY-MM-DD)"),
    mode: str = typer.Option("current", help="Mode: current or positional"),
    dry_run: bool = typer.Option(False, help="Preview without writes")
):
    """Remediate data from Breeze."""
    ...

@app.command()
def status():
    """Show current remediation progress."""
    ...

@app.command()
def reset(
    confirm: bool = typer.Option(False, help="Confirm reset")
):
    """Reset progress tracking."""
    ...

if __name__ == "__main__":
    app()
```

---

## 8. Testing Plan

### 8.1 Unit Tests

| Test | File | Description |
|------|------|-------------|
| test_expiry_calculator | tests/test_expiry.py | Test all expiry day scenarios |
| test_strike_resolver | tests/test_strikes.py | Test ATM calculation |
| test_progress_store | tests/test_progress.py | Test SQLite operations |

### 8.2 Integration Tests

| Test | Description |
|------|-------------|
| test_breeze_connection | Verify Breeze API connectivity |
| test_postgres_connection | Verify PostgreSQL connectivity |
| test_dry_run | Verify dry-run produces no writes |
| test_resumability | Verify resume after interruption |

---

## 9. Validation Checklist

Before running on production data:

- [ ] Dry-run on 1 day of NIFTY data
- [ ] Verify UPSERT doesn't delete existing data
- [ ] Verify progress store tracks correctly
- [ ] Verify rate limiting works
- [ ] Verify expiry calculation for current date
- [ ] Verify strike range resolution

---

## 10. Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Data loss | UPSERT pattern, no DELETE operations |
| API quota exhaustion | Rate limiting, progress tracking |
| Network interruption | SQLite progress store, resume capability |
| Wrong expiry dates | Comprehensive expiry calculator with tests |
| Incorrect strike ranges | Admin range lookup with ATM fallback |

---

## 11. Rollback Plan

If remediation causes issues:
1. Stop the remediation tool
2. Identify affected date range from audit log
3. Use backup (if created) to restore
4. Or re-run with correct parameters

---

## 12. Success Criteria

1. Tool can process 1 week of NIFTY data without errors
2. All operations are logged to audit table
3. Resume works correctly after simulated interruption
4. Dry-run produces identical logs without DB writes
5. Rate limiting prevents API quota exhaustion

---

*Document created: 2026-01-24*
