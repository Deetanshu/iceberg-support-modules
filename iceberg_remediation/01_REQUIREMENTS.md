# Data Remediation Service - Requirements Document

**Version:** 1.0  
**Date:** 2026-01-24  
**Status:** APPROVED FOR IMPLEMENTATION

---

## 1. Executive Summary

A local CLI tool for validating and correcting historical market data in the Iceberg production database. The service runs on the developer's machine (not cloud-deployed), connects directly to Cloud SQL PostgreSQL, and uses Breeze Historical API as the authoritative data source for remediation.

---

## 2. Functional Requirements

### 2.1 Core Operations

| ID | Requirement | Priority |
|----|-------------|----------|
| REM-001 | Validate existing data against Breeze Historical API | P0 |
| REM-002 | Delete flawed data with audit trail | P0 |
| REM-003 | Insert/update corrected data from Breeze | P0 |
| REM-004 | Recalculate derived indicators after candle remediation | P1 |
| REM-005 | Support dry-run mode for all operations | P0 |
| REM-006 | Resume from interruption (network outage, crash) | P0 |

### 2.2 Data Sources

| ID | Requirement | Priority |
|----|-------------|----------|
| REM-010 | Use Breeze Historical API for NIFTY, BANKNIFTY, FINNIFTY | P0 |
| REM-011 | Use Kite Historical API for SENSEX (Breeze doesn't support BSE) | P1 |
| REM-012 | Fetch index candles with OHLCV | P0 |
| REM-013 | Fetch option candles with OI (open_interest field) | P0 |

### 2.3 Strike Range Resolution

| ID | Requirement | Priority |
|----|-------------|----------|
| REM-020 | Query historical admin ranges from `app.admin_key_ranges` | P0 |
| REM-021 | Fallback to ±5 ATM strikes if no admin range exists | P0 |
| REM-022 | Support both `current` and `positional` modes | P0 |
| REM-023 | Calculate ATM from spot price with correct strike intervals | P0 |

### 2.4 Expiry Day Logic

| ID | Requirement | Priority |
|----|-------------|----------|
| REM-030 | Handle NSE expiry day changes (see timeline below) | P0 |
| REM-031 | Calculate correct expiry dates for historical lookups | P0 |
| REM-032 | Skip market holidays using `app.market_holidays` | P0 |

**Expiry Day Timeline:**
- Before Mar 2024: NIFTY=Thu, BANKNIFTY=Thu, FINNIFTY=Tue
- Mar 2024 - Dec 2024: NIFTY=Thu, BANKNIFTY=Wed, FINNIFTY=Tue
- Jan 2025 - Aug 2025: All NSE monthly=Thu
- After Aug 28, 2025: All NSE=Tue, SENSEX=Thu

### 2.5 Resumability

| ID | Requirement | Priority |
|----|-------------|----------|
| REM-040 | Store progress in local SQLite database | P0 |
| REM-041 | Track completed date/symbol/strike combinations | P0 |
| REM-042 | Resume from last successful checkpoint on restart | P0 |
| REM-043 | Support force-restart to ignore previous progress | P1 |

---

## 3. Non-Functional Requirements

### 3.1 Safety

| ID | Requirement | Priority |
|----|-------------|----------|
| REM-050 | All write operations must be transactional | P0 |
| REM-051 | Use UPSERT (INSERT ON CONFLICT UPDATE) instead of DELETE+INSERT | P0 |
| REM-052 | Log all operations to audit table | P0 |
| REM-053 | Support backup before destructive operations | P1 |

### 3.2 Rate Limiting

| ID | Requirement | Priority |
|----|-------------|----------|
| REM-060 | Respect Breeze API rate limits (250/min, 2500/day) | P0 |
| REM-061 | Configurable delay between API requests (default 0.3s) | P0 |
| REM-062 | Exponential backoff on rate limit errors | P0 |

### 3.3 Observability

| ID | Requirement | Priority |
|----|-------------|----------|
| REM-070 | Structured logging with progress indicators | P0 |
| REM-071 | Summary report at end of each run | P0 |
| REM-072 | Detailed error logging with context | P0 |

---

## 4. Target Tables

### 4.1 Read Tables

| Table | Purpose |
|-------|---------|
| `app.admin_key_ranges` | Historical strike ranges |
| `app.market_holidays` | Holiday calendar |
| `processing.candles_5m` | Index candles (for validation) |
| `processing.option_chain_candles_5m` | Option candles (for validation) |

### 4.2 Write Tables

| Table | Purpose |
|-------|---------|
| `processing.candles_5m` | Index candle corrections |
| `processing.option_chain_candles_5m` | Option candle corrections |
| `processing.{symbol}_indicators_5m` | Recalculated indicators |

### 4.3 Local Tables (SQLite)

| Table | Purpose |
|-------|---------|
| `remediation_progress` | Track completed work |
| `remediation_audit` | Local audit log |
| `remediation_errors` | Failed operations for retry |

---

## 5. Data Shapes

### 5.1 Index Candle (processing.candles_5m)

```
symbol      TEXT NOT NULL
bucket_ts   TIMESTAMPTZ NOT NULL
trade_date  DATE NOT NULL
open        NUMERIC(10,2) NOT NULL
high        NUMERIC(10,2) NOT NULL
low         NUMERIC(10,2) NOT NULL
close       NUMERIC(10,2) NOT NULL
volume      BIGINT
tick_count  INTEGER
```

**Primary Key:** `(symbol, bucket_ts)`

### 5.2 Option Candle (processing.option_chain_candles_5m)

```
symbol      TEXT NOT NULL
expiry      DATE NOT NULL
strike      NUMERIC NOT NULL
option_type TEXT NOT NULL ('CE' or 'PE')
bucket_ts   TIMESTAMPTZ NOT NULL
trade_date  DATE NOT NULL
open        NUMERIC(10,2) NOT NULL
high        NUMERIC(10,2) NOT NULL
low         NUMERIC(10,2) NOT NULL
close       NUMERIC(10,2) NOT NULL
oi_open     BIGINT
oi_high     BIGINT
oi_low      BIGINT
oi_close    BIGINT
vol_open    BIGINT
vol_high    BIGINT
vol_low     BIGINT
vol_close   BIGINT
tick_count  INTEGER
```

**Primary Key:** `(symbol, expiry, strike, option_type, bucket_ts)`

### 5.3 Admin Key Range (app.admin_key_ranges)

```
symbol          TEXT NOT NULL
mode            TEXT ('current' or 'positional')
lower_strike    NUMERIC(10,2) NOT NULL
upper_strike    NUMERIC(10,2) NOT NULL
effective_from  DATE
effective_until DATE
is_active       BOOLEAN
```

---

## 6. Supported Symbols

| Symbol | Breeze Stock Code | Exchange | Strike Interval |
|--------|-------------------|----------|-----------------|
| nifty | NIFTY | NFO | 50 |
| banknifty | CNXBAN | NFO | 100 |
| finnifty | NIFFIN | NFO | 50 |
| sensex | N/A (use Kite) | BSE | 100 |

---

## 7. CLI Interface

```bash
# Validate data (dry run)
python -m iceberg_remediation validate \
  --symbol nifty \
  --from-date 2026-01-15 \
  --to-date 2026-01-20

# Delete flawed data
python -m iceberg_remediation delete \
  --symbol nifty \
  --from-date 2026-01-10 \
  --to-date 2026-01-15 \
  --reason "incorrect_oi_values"

# Remediate (fetch + upsert)
python -m iceberg_remediation remediate \
  --symbol nifty \
  --from-date 2026-01-15 \
  --to-date 2026-01-20 \
  --dry-run

# Recalculate indicators
python -m iceberg_remediation recalculate \
  --symbol nifty \
  --from-date 2026-01-15 \
  --to-date 2026-01-20

# Full pipeline
python -m iceberg_remediation full \
  --symbol nifty \
  --from-date 2026-01-10 \
  --to-date 2026-01-20 \
  --delete-flawed \
  --dry-run

# Show progress
python -m iceberg_remediation status

# Reset progress (force restart)
python -m iceberg_remediation reset --confirm
```

---

## 8. Out of Scope

| Item | Reason |
|------|--------|
| Backtesting data collection | Future scope (separate schema) |
| Real-time data correction | Production Data Handler handles this |
| Database schema modifications | Read-only access rule |
| Cloud deployment | Local tool only |
| ADR constituent data | Not available in Breeze Historical |

---

## 9. Acceptance Criteria

1. **AC-001:** Tool can validate 1 day of NIFTY data in < 5 minutes
2. **AC-002:** Tool resumes correctly after simulated network interruption
3. **AC-003:** All write operations use UPSERT (no data loss on retry)
4. **AC-004:** Dry-run mode produces identical logs without DB writes
5. **AC-005:** Audit log captures all operations with timestamps
6. **AC-006:** Rate limiting prevents Breeze API quota exhaustion

---

## 10. Dependencies

| Dependency | Version | Purpose |
|------------|---------|---------|
| Python | 3.11+ | Runtime |
| asyncpg | 0.29+ | PostgreSQL async client |
| aiosqlite | 0.19+ | SQLite async client |
| httpx | 0.25+ | HTTP client for Breeze |
| typer | 0.9+ | CLI framework |
| pydantic | 2.0+ | Configuration and validation |
| structlog | 23.0+ | Structured logging |
| tenacity | 8.0+ | Retry logic |

---

## Appendix A: Known Data Issues

| Issue | Date Range | Affected Tables | Action |
|-------|------------|-----------------|--------|
| Incorrect OI values | Before 2026-01-15 | option_chain_candles_5m | DELETE + re-fetch |
| Missing prev_close_oi | Various | option_oi_prev_close_snapshot | Re-bootstrap |
| Wrong expiry data | Various | option_chain_candles_5m | DELETE invalid rows |

---

*Document created: 2026-01-24*
