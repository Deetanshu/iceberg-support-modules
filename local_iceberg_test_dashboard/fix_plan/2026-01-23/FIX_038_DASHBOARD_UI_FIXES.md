# Test Dashboard Fixes - 2026-01-23

## Issues Identified & Fixed

### 1. Admin Users Endpoint - Pagination (FIX-035) ✅
**Status:** FIXED
**Changes Made:**
- `api_client.py`: Added `page` and `limit` params to `admin_get_users()`
- `admin_page.py`: Updated `get_users()` helper to return `(success, users, total, has_more, message)` tuple

### 2. RSI Not Being Plotted ✅
**Root Cause:** The RSI chart only showed a single point because `rsi_values` was created with only the current RSI value.
**Fix:** Changed `app.py` to use `state_manager.get_rsi_history(symbol)` which tracks RSI history over time.

### 3. Volume Not Being Plotted
**Status:** Already working - volume IS being plotted in `create_candlestick_chart()` as the second subplot.
**Note:** If volume appears empty, it's because candle data may not have volume values populated from bootstrap.

### 4. Symbol Changer Doesn't Work ✅
**Root Cause:** The symbol cards were missing `n_clicks=0` initialization, which is required for pattern-matching callbacks to work.
**Fix:** Added `n_clicks=0` to the symbol card Div in `layouts.py`.

### 5. Bottom Overlap with Symbol Changer ✅
**Root Cause:** Pages didn't have padding to account for the fixed symbol selector bar at the bottom.
**Fix:** Added `paddingBottom: 100px` to:
- `advanced_page.py`
- `admin_page.py`
- `debugging_page.py`
(Main page already had this padding)

### 6. Dropdown Text Color (White on White) ✅
**Root Cause:** Dash dropdowns use default styling which had white text on white background.
**Fix:** Created `assets/custom.css` with styles to fix dropdown text color to dark gray (#333333).

### 7. Treemap Sizing by LTP ✅
**Root Cause:** Treemap rectangles were sized by `abs(change_pct)` which made small movers nearly invisible.
**Fix:** Changed `create_adr_treemap()` in `charts.py` to use `ltp` field for sizing instead. Larger stocks now get bigger rectangles, making the treemap more representative of market weight.

## Files Modified

1. `local_iceberg_test_dashboard/src/api_client.py` - Added pagination params to admin_get_users()
2. `local_iceberg_test_dashboard/src/admin_page.py` - Updated get_users helper, added bottom padding
3. `local_iceberg_test_dashboard/src/app.py` - Fixed RSI history usage, fixed users unpacking
4. `local_iceberg_test_dashboard/src/layouts.py` - Added n_clicks=0 to symbol cards
5. `local_iceberg_test_dashboard/src/advanced_page.py` - Added bottom padding
6. `local_iceberg_test_dashboard/src/debugging_page.py` - Added bottom padding
7. `local_iceberg_test_dashboard/assets/custom.css` - NEW: Fixed dropdown text color
8. `local_iceberg_test_dashboard/src/charts.py` - Changed treemap sizing from change_pct to LTP

## Validation Steps

1. Run the dashboard: `cd local_iceberg_test_dashboard && python -m src.app`
2. Verify symbol changer works by clicking different symbols
3. Verify RSI subplot shows historical data (not just a single point)
4. Verify dropdown text is visible (dark text on white background)
5. Verify no overlap at the bottom of pages with the symbol selector
6. Test admin page user list loads correctly with pagination
