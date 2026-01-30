# Test Dashboard Fix Plan

This directory contains fix documentation for the **local_iceberg_test_dashboard** project only.

## Scope

Fixes documented here are specific to:
- `local_iceberg_test_dashboard/src/` - Dashboard source code
- `local_iceberg_test_dashboard/tests/` - Dashboard tests
- Dashboard-specific UI, state management, and API client issues

## NOT in Scope

Fixes for the main `lean_iceberg/` codebase belong in `iceberg_fix_plan/`:
- API Layer (`lean_iceberg/api_layer/`)
- Data Handler (`lean_iceberg/datahandler_server/`)
- PostgreSQL schema (`lean_iceberg/postgres_setup/`)
- Database triggers and migrations

## Directory Structure

```
fix_plan/
├── README.md           # This file
└── YYYY-MM-DD/         # Date-based folders
    └── FIX_XXX_*.md    # Individual fix documents
```

## Fix Numbering

Dashboard fixes use the same numbering sequence as `iceberg_fix_plan/` to avoid ID collisions. When creating a new fix, check the latest FIX number in both directories.

## Current Fixes

### 2026-01-22
- **FIX-029**: Skew/PCR and EMA Chart Deduplication
- **FIX-030**: Dashboard Indicator Display Fixes (symbol changer, ADR/RSI, intuition text)
