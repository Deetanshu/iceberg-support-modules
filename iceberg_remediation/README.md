# Iceberg Data Remediation Service

Local CLI tool for validating and correcting historical option data (especially OI) in the Iceberg production database.

## Overview

This service:
- Runs locally on your machine (not cloud-deployed)
- Connects directly to Cloud SQL PostgreSQL
- Uses Breeze Historical API as authoritative data source for option OI
- Supports resumable operations via local SQLite tracking
- Prioritizes `current` mode (weekly expiry) over `positional` (monthly)

## Quick Start

```bash
# 1. Install dependencies
cd iceberg_remediation
pip install -r requirements.txt

# 2. Copy and configure environment
cp .env.example .env
# Edit .env with your credentials (see .env.example)

# 3. Update Breeze session token (required daily)
# Get token from local_test/results/breeze_session.json after running update_breeze_session.py

# 4. Validate data (dry run - no writes)
python -m iceberg_remediation validate --symbol nifty --from 2026-01-15 --to 2026-01-20 --mode current

# 5. Remediate data (with dry-run first)
python -m iceberg_remediation remediate --symbol nifty --from 2026-01-15 --to 2026-01-20 --mode current --dry-run

# 6. Remediate data (actual writes)
python -m iceberg_remediation remediate --symbol nifty --from 2026-01-15 --to 2026-01-20 --mode current
```

## Commands

| Command | Description |
|---------|-------------|
| `validate` | Compare DB data with Breeze (no writes) |
| `remediate` | Fetch from Breeze and UPSERT to DB |
| `status` | Show current progress for a run |
| `reset` | Clear progress tracking for a run |
| `list-symbols` | Show supported symbols |

## CLI Options

### validate / remediate
- `--symbol, -s` - Symbol to process (nifty, banknifty, finnifty)
- `--from, -f` - Start date (YYYY-MM-DD)
- `--to, -t` - End date (YYYY-MM-DD)
- `--mode, -m` - Mode: current (weekly) or positional (monthly)
- `--dry-run, -d` - Preview without writing (remediate only)
- `--output, -o` - Output file for results (validate only)
- `--run-id, -r` - Custom run ID for resumability

## Documentation

- [01_REQUIREMENTS.md](01_REQUIREMENTS.md) - Functional requirements
- [02_DESIGN.md](02_DESIGN.md) - Architecture and design
- [03_IMPLEMENTATION_PLAN.md](03_IMPLEMENTATION_PLAN.md) - Implementation details

## Supported Symbols

| Symbol | Breeze Code | Strike Interval | Modes |
|--------|-------------|-----------------|-------|
| nifty | NIFTY | 50 | current, positional |
| banknifty | CNXBAN | 100 | current, positional |
| finnifty | NIFFIN | 50 | current only |

**Note:** SENSEX is not supported by Breeze API (BSE exchange).

## Safety Features

- **UPSERT pattern**: No data loss on retry, preserves existing data
- **Progress tracking**: Resume after interruption using run_id
- **Dry-run mode**: Preview all changes without writes
- **Audit logging**: All operations logged to SQLite
- **Rate limiting**: 0.3s delay between API calls to avoid quota issues

## Prerequisites

- Python 3.11+
- Breeze API credentials (session token must be refreshed daily)
- PostgreSQL access to Cloud SQL (34.180.57.7)

## Important: Special Characters in API Keys

The Breeze API key contains special characters (`=`, `&`, `)`) that can cause issues:

```
ls02H2142bj4419=5515l15527)206&0
```

**When using in shell commands or URLs:**
- URL-encode the key, or
- Wrap in single quotes to prevent shell interpretation

**In `.env` files:**
- No quoting needed - Pydantic handles it correctly
- Do NOT add extra quotes around the value

**Example login URL (already encoded):**
```
https://api.icicidirect.com/apiuser/login?api_key=ls02H2142bj4419=5515l15527)206&0
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    CLI (cli.py)                             │
├─────────────────────────────────────────────────────────────┤
│  Engine Layer                                               │
│  ├── Validator (compare DB vs Breeze)                       │
│  └── Remediator (fetch + UPSERT)                           │
├─────────────────────────────────────────────────────────────┤
│  Core Layer                                                 │
│  ├── ExpiryCalculator (NSE expiry day logic)               │
│  ├── StrikeResolver (admin range + ATM fallback)           │
│  ├── HolidayChecker (skip non-trading days)                │
│  └── ProgressStore (SQLite resumability)                   │
├─────────────────────────────────────────────────────────────┤
│  Client Layer                                               │
│  ├── BreezeClient (Historical API with rate limiting)      │
│  └── PostgresClient (asyncpg connection pool)              │
└─────────────────────────────────────────────────────────────┘
```

## Expiry Day Logic

The service handles NSE expiry day changes automatically:

| Period | NIFTY | BANKNIFTY | FINNIFTY |
|--------|-------|-----------|----------|
| Before Mar 2024 | Thursday | Thursday | Tuesday |
| Mar 2024 - Dec 2024 | Thursday | Wednesday | Tuesday |
| Jan 2025 - Aug 27, 2025 | Thursday | Thursday | Thursday |
| After Aug 28, 2025 | Tuesday | Tuesday | Tuesday |
