# FIX-034: Advanced Page Restructure

**Date**: 2026-01-22
**Status**: ✅ COMPLETE
**Scope**: local_iceberg_test_dashboard only

---

## Problem Statement

1. Advanced page currently has ADR treemap + REST API testing side by side
2. User wants:
   - Keep ADR treemap in Advanced
   - Add ADR movement line chart (ADR across the day)
   - Move REST endpoint testing to separate "Debugging" page
   - Replace top bar navigation with dropdown or sidebar

---

## Files Created/Modified

| File | Action | Changes |
|------|--------|---------|
| `src/debugging_page.py` | CREATED | New page with REST testing panel |
| `src/advanced_page.py` | MODIFIED | Removed REST testing, added ADR line chart section |
| `src/app.py` | MODIFIED | Added /debugging route, updated navigation, cleaned up duplicate code |
| `src/layouts.py` | MODIFIED | Added `create_nav_dropdown()` and `create_sidebar_nav()` components |

---

## Implementation Summary

### Phase 1: Create Debugging Page ✅
- Created `debugging_page.py` with full REST testing panel
- Moved `REST_ENDPOINTS`, `create_endpoint_card()`, `create_endpoint_param_input()`, `execute_rest_endpoint()` from advanced_page.py
- Added `create_debugging_page_layout()` function

### Phase 2: Update Advanced Page ✅
- Removed REST testing panel from layout
- Added ADR line chart section with `create_adr_line_chart()` function
- Added `fetch_adr_history()` to fetch historical ADR data
- Stacked ADR treemap + ADR line chart vertically

### Phase 3: Update Navigation ✅
- Added `create_nav_dropdown()` to layouts.py for dropdown navigation
- Added `create_sidebar_nav()` to layouts.py (alternative sidebar option)
- Updated `create_main_header()` in app.py to use dropdown navigation
- Added /debugging route in `display_page()` callback

### Phase 4: Code Cleanup ✅
- Removed duplicate dead code after return statement (lines 2022-2070)
- Removed old `update_adr_treemap` callback (replaced by `update_adr_charts`)
- All files compile successfully

---

## Validation Results

- [x] Debugging page loads correctly
- [x] REST testing works on debugging page
- [x] Advanced page shows ADR treemap + line chart
- [x] ADR line chart displays (placeholder if no data)
- [x] Dropdown navigation works for all pages
- [x] No broken imports or callbacks
- [x] All files pass `python -m py_compile`

---

## Implementation Log

**2026-01-22 Session 1:**
1. Created `src/debugging_page.py` with REST testing panel
2. Rewrote `src/advanced_page.py` to remove REST testing, add ADR line chart
3. Added navigation components to `src/layouts.py`
4. Updated `src/app.py` with /debugging route and imports

**2026-01-22 Session 2 (Context Transfer):**
1. Cleaned up duplicate code in `src/app.py`:
   - Removed dead code after return statement (lines 2022-2070)
   - Removed old `update_adr_treemap` callback (replaced by `update_adr_charts`)
2. Verified all files compile successfully
