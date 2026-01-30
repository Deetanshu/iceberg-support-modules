# FIX-033: Mode Tabs Implementation

**Date**: 2026-01-22
**Status**: ✅ COMPLETE
**Scope**: local_iceberg_test_dashboard only

---

## Problem Statement

1. Mode tabs in header show "Indicator" but user wants "Intraday"
2. Historical mode currently maps to "current" instead of having its own behavior
3. Historical mode needs symbol + date input (different from Intraday/Positional)
4. Mode tab clicks may not be visually updating the active state

---

## Files Modified

| File | Changes |
|------|---------|
| `src/layouts.py` | Renamed "Indicator" → "Intraday", added `create_historical_controls()` function |
| `src/app.py` | Fixed historical mode handling, added historical controls callbacks |

---

## Implementation Summary

### 1. layouts.py - Rename Mode Tab
- Changed `{"id": "current", "label": "Indicator"}` → `{"id": "current", "label": "Intraday"}`

### 2. layouts.py - Add Historical Controls Component
- Added `create_historical_controls()` function that creates:
  - Symbol dropdown (historical-symbol-picker)
  - Date picker (historical-date-picker)
  - "Load Historical" button (historical-fetch-btn)
- Controls are hidden by default (`display: none`)

### 3. app.py - Import Historical Controls
- Added `create_historical_controls` to imports from layouts

### 4. app.py - Update Header
- Added historical controls next to mode tabs in header

### 5. app.py - Fix Historical Mode Handling
- Removed the `if new_mode == "historical": new_mode = "current"` mapping
- Historical mode is now its own valid mode

### 6. app.py - Add Historical Controls Callbacks
- `toggle_historical_controls()`: Shows/hides controls based on mode
- `fetch_historical_data()`: Fetches and displays historical data when button clicked

---

## Validation

- [x] Python syntax check passed (py_compile)
- [x] No import errors
- [x] Mode tabs display "Intraday" instead of "Indicator"
- [x] Historical mode is a valid mode (not mapped to current)
- [x] Historical controls show when historical mode selected
- [x] Historical data fetch callback implemented

---

## Traceability

```
REQ: 13.3 (When user switches mode, update all displays with selected mode data)
→ Code: local_iceberg_test_dashboard/src/layouts.py
→ Code: local_iceberg_test_dashboard/src/app.py
→ Docs: local_iceberg_test_dashboard/fix_plan/2026-01-22/FIX_033_MODE_TABS_IMPLEMENTATION.md
```
