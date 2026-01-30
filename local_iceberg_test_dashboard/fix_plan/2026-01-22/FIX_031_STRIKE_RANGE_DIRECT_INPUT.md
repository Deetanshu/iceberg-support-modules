# FIX-031: Strike Range Direct Input

**Date**: 2026-01-22
**Status**: ✅ COMPLETE
**Scope**: local_iceberg_test_dashboard only

---

## Problem Statement

The dashboard UI for strike range configuration uses "Strikes Above ATM" and "Strikes Below ATM" (count-based inputs), but the API expects `lower_strike` and `upper_strike` (actual strike prices).

### Current Behavior
- Dashboard sends: `{"range_above": 10, "range_below": 10}`
- API expects: `{"lower_strike": 24900.0, "upper_strike": 25700.0}`

### Expected Behavior
- User enters actual strike prices (e.g., 24900 to 25700 for NIFTY)
- Dashboard sends correct field names to API

---

## Files Modified

| File | Changes |
|------|---------|
| `src/admin_page.py` | Updated UI inputs and `set_strike_ranges()` function |
| `src/api_client.py` | Fixed `admin_set_strike_ranges()` parameters |
| `src/app.py` | Updated callback State IDs |

---

## Implementation Summary

### 1. admin_page.py - UI Changes
- Changed "Strikes Above ATM" → "Lower Strike" (id: `strike-range-lower`)
- Changed "Strikes Below ATM" → "Upper Strike" (id: `strike-range-upper`)
- Added placeholder text with examples (e.g., "24900", "25700")
- Updated description text to explain direct strike price input

### 2. admin_page.py - Function Changes
- Updated `set_strike_ranges()` signature: `range_above`/`range_below` → `lower_strike`/`upper_strike`
- Added validation: lower_strike < upper_strike
- Updated success message to show actual strike range

### 3. api_client.py - Method Changes
- Updated `admin_set_strike_ranges()` parameters
- Changed JSON payload to use `lower_strike`/`upper_strike`

### 4. app.py - Callback Changes
- Updated State IDs from `strike-range-above`/`strike-range-below` to `strike-range-lower`/`strike-range-upper`
- Updated validation logic for strike prices
- Updated function call parameters

---

## Validation

- [x] Python syntax check passed (py_compile)
- [x] No import errors
- [x] API contract matches `lean_iceberg/api_layer/src/api_layer/routes/admin.py`

---

## Traceability

```
REQ: 15.7 (Strike range configuration via POST /v1/admin/strike-ranges)
→ Code: local_iceberg_test_dashboard/src/admin_page.py
→ Code: local_iceberg_test_dashboard/src/api_client.py
→ Code: local_iceberg_test_dashboard/src/app.py
→ Docs: local_iceberg_test_dashboard/fix_plan/2026-01-22/FIX_031_STRIKE_RANGE_DIRECT_INPUT.md
```
