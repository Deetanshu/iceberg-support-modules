# EXPLORATION-001: Dashboard Improvements Investigation

**Date**: 2026-01-22
**Status**: ✅ All Fixes Complete (4 of 4)
**Scope**: local_iceberg_test_dashboard only

---

## Overview

User requested investigation and fix planning for 4 dashboard issues:
1. Admin Strike Ranges - Direct Range Input → **✅ FIX-031 COMPLETE**
2. Missing Skew/PCR Data Detection & Auto-Bootstrap → **✅ FIX-032 COMPLETE**
3. Mode Tabs Not Working (Indicator/Positional/Historical) → **✅ FIX-033 COMPLETE**
4. Advanced Page Restructure (ADR + Debugging separation) → **✅ FIX-034 COMPLETE**

---

## Issue 1: Admin Strike Ranges - Direct Range Input

### Current State

**Dashboard UI** (`admin_page.py` lines 400-550):
- Uses "Strikes Above ATM" and "Strikes Below ATM" (number inputs)
- Input IDs: `strike-range-above`, `strike-range-below`
- Values are integers (1-50 range)

**Dashboard API Client** (`api_client.py` lines 687-720):
```python
async def admin_set_strike_ranges(
    self,
    symbol: str,
    mode: str,
    range_above: int,  # ← Currently sends count
    range_below: int,  # ← Currently sends count
) -> APIResponse:
    response = await client.post(
        "/v1/admin/strike-ranges",
        json={
            "symbol": symbol,
            "mode": mode,
            "range_above": range_above,  # ← WRONG FIELD NAME
            "range_below": range_below,  # ← WRONG FIELD NAME
        },
        ...
    )
```

**API Layer Contract** (`lean_iceberg/api_layer/src/api_layer/routes/admin.py` lines 253-260):
```python
class StrikeRangeCreateRequest(BaseModel):
    symbol: str
    mode: str = Field(..., pattern="^(current|positional)$")
    lower_strike: float  # ← Expects actual strike price
    upper_strike: float  # ← Expects actual strike price
    effective_from: Optional[date] = None
```

### Problem

**MISMATCH**: Dashboard sends `range_above`/`range_below` (counts), but API expects `lower_strike`/`upper_strike` (actual strike prices).

The API is designed for direct strike values (e.g., 24900 to 25700 for NIFTY), but the dashboard UI and client are sending strike counts relative to ATM.

### Required Changes

| File | Change |
|------|--------|
| `admin_page.py` | Replace "Strikes Above/Below ATM" inputs with "Lower Strike" and "Upper Strike" inputs |
| `admin_page.py` | Update `set_strike_ranges()` function signature |
| `api_client.py` | Fix `admin_set_strike_ranges()` to send `lower_strike`/`upper_strike` |
| `app.py` | Update callback to pass new field names |

### Fix Plan

**FIX-031: Strike Range Direct Input**
1. Modify `create_strike_range_section()` in `admin_page.py`:
   - Change "Strikes Above ATM" → "Lower Strike" (input id: `strike-range-lower`)
   - Change "Strikes Below ATM" → "Upper Strike" (input id: `strike-range-upper`)
   - Update placeholder text with examples (e.g., "24900" for NIFTY)
   - Add validation: lower < upper

2. Update `api_client.py`:
   ```python
   async def admin_set_strike_ranges(
       self,
       symbol: str,
       mode: str,
       lower_strike: float,  # Changed
       upper_strike: float,  # Changed
   ) -> APIResponse:
       response = await client.post(
           "/v1/admin/strike-ranges",
           json={
               "symbol": symbol,
               "mode": mode,
               "lower_strike": lower_strike,  # Fixed
               "upper_strike": upper_strike,  # Fixed
           },
           ...
       )
   ```

3. Update `admin_page.py` `set_strike_ranges()`:
   ```python
   async def set_strike_ranges(
       api_client: IcebergAPIClient,
       symbol: str,
       mode: str,
       lower_strike: float,  # Changed
       upper_strike: float,  # Changed
   ) -> Tuple[bool, str]:
   ```

4. Update callback in `app.py` (around line 2300):
   - Change State IDs from `strike-range-above`/`strike-range-below` to `strike-range-lower`/`strike-range-upper`

---

## Issue 2: Missing Skew/PCR Data Detection & Auto-Bootstrap

### Current State

**DB Query Results** (from investigation):
- Latest data timestamp: 09:55 UTC = 15:25 IST
- Market closes at 15:30 IST
- Current time during investigation: 16:33 IST (market closed)

**Finding**: Data gap is NOT a bug - it's expected behavior. Data stops ~5 minutes before market close (15:25 IST) because:
1. Market closes at 15:30 IST
2. Last candle aggregation happens at 15:25 IST
3. No new data after market close

### Problem

Dashboard doesn't have resilience to:
1. Detect when data is missing/stale during market hours
2. Auto-trigger bootstrap when gaps are detected
3. Distinguish between "market closed" vs "data missing during market hours"

### Required Changes

| File | Change |
|------|--------|
| `state_manager.py` | Add data gap detection logic |
| `app.py` | Add auto-bootstrap trigger on gap detection |
| `layouts.py` | Add visual indicator for data gaps |

### Fix Plan

**FIX-032: Data Gap Detection & Auto-Bootstrap**

1. Add to `state_manager.py`:
   ```python
   def detect_data_gaps(self, symbol: str, mode: str) -> Dict[str, Any]:
       """Detect gaps in skew/pcr/candle data.
       
       Returns:
           {
               "has_gap": bool,
               "gap_type": "skew" | "pcr" | "candles" | None,
               "last_data_time": datetime | None,
               "expected_data_time": datetime | None,
               "gap_minutes": int | None,
           }
       """
   
   def should_auto_bootstrap(self) -> bool:
       """Check if auto-bootstrap should be triggered.
       
       Conditions:
       1. Market is OPEN
       2. Data gap > 5 minutes detected
       3. Last bootstrap was > 2 minutes ago (prevent spam)
       """
   ```

2. Add to `app.py` slow-interval callback:
   ```python
   # Check for data gaps during market hours
   if state_manager.should_auto_bootstrap():
       # Trigger bootstrap with skew, pcr, candles
       await bootstrap_with_checks(["skew", "pcr", "candles"])
   ```

3. Add visual indicator in `layouts.py`:
   - Show warning banner when data gap detected during market hours
   - Different from staleness warning (which is for cache age)

---

## Issue 3: Mode Tabs Not Working

### Current State

**Mode Tabs** (`layouts.py` lines 760-810):
```python
def create_mode_tabs_header(current_mode: str = "current") -> html.Div:
    modes = [
        {"id": "current", "label": "Indicator"},      # ← User wants "Intraday"
        {"id": "positional", "label": "Positional"},
        {"id": "historical", "label": "Historical"},  # ← Different behavior needed
    ]
```

**Callback** (`app.py` lines 1631-1665):
```python
@app.callback(
    Output("selected-mode-store", "data"),
    [Input({"type": "header-mode-tab", "mode": ALL}, "n_clicks")],
    [State("selected-mode-store", "data")],
    prevent_initial_call=True,
)
def handle_mode_change(n_clicks_list, current_mode):
    # Maps "historical" to "current" - NOT CORRECT
    if new_mode == "historical":
        new_mode = "current"  # ← This is wrong
    return new_mode
```

### Problems

1. **Label**: "Indicator" should be "Intraday"
2. **Historical Mode**: Currently maps to "current" instead of having its own behavior
3. **Historical Needs**: Symbol + Date input (different from Intraday/Positional)
4. **Visual Feedback**: Tabs may not show active state correctly

### Required Changes

| File | Change |
|------|--------|
| `layouts.py` | Rename "Indicator" → "Intraday" |
| `layouts.py` | Add Historical mode date picker component |
| `app.py` | Implement Historical mode callback with date selection |
| `app.py` | Remove the `historical → current` mapping |

### Fix Plan

**FIX-033: Mode Tabs Implementation**

1. Update `layouts.py` `create_mode_tabs_header()`:
   ```python
   modes = [
       {"id": "current", "label": "Intraday"},      # Renamed
       {"id": "positional", "label": "Positional"},
       {"id": "historical", "label": "Historical"},
   ]
   ```

2. Add Historical mode date picker in `layouts.py`:
   ```python
   def create_historical_date_picker() -> html.Div:
       """Date picker shown only when Historical mode is active."""
       return html.Div(
           [
               dcc.DatePickerSingle(
                   id="historical-date-picker",
                   date=date.today().isoformat(),
                   display_format="YYYY-MM-DD",
               ),
               dcc.Dropdown(
                   id="historical-symbol-picker",
                   options=[...],
                   value="nifty",
               ),
           ],
           id="historical-controls",
           style={"display": "none"},  # Hidden by default
       )
   ```

3. Update `app.py` callback:
   ```python
   def handle_mode_change(n_clicks_list, current_mode):
       # Remove the historical → current mapping
       # Let historical be its own mode
       return new_mode
   ```

4. Add callback to show/hide historical controls:
   ```python
   @app.callback(
       Output("historical-controls", "style"),
       [Input("selected-mode-store", "data")],
   )
   def toggle_historical_controls(mode):
       if mode == "historical":
           return {"display": "flex", "gap": "10px"}
       return {"display": "none"}
   ```

5. Add callback to fetch historical data:
   ```python
   @app.callback(
       [...],  # Chart outputs
       [
           Input("historical-date-picker", "date"),
           Input("historical-symbol-picker", "value"),
       ],
       [State("selected-mode-store", "data")],
   )
   def fetch_historical_data(date, symbol, mode):
       if mode != "historical":
           raise PreventUpdate
       # Call GET /v1/dashboard/historical/snapshot
   ```

---

## Issue 4: Advanced Page Restructure

### Current State

**Advanced Page** (`advanced_page.py`):
- Two-column layout:
  - Left: ADR Treemap
  - Right: REST API Testing Panel
- Both in same page

**User Wants**:
1. Keep ADR Treemap in Advanced
2. Add ADR movement line chart (ADR across the day)
3. Move REST endpoint testing to separate "Debugging" page
4. Replace top bar navigation with dropdown or sidebar

### Required Changes

| File | Change |
|------|--------|
| `advanced_page.py` | Remove REST testing panel, add ADR line chart |
| New: `debugging_page.py` | Create new page with REST testing panel |
| `app.py` | Add routing for /debugging page |
| `layouts.py` | Replace header nav with sidebar/dropdown |

### Fix Plan

**FIX-034: Advanced Page Restructure**

1. Create `debugging_page.py`:
   - Move `create_rest_testing_panel()` from `advanced_page.py`
   - Move `REST_ENDPOINTS` list
   - Move `create_endpoint_card()`, `create_endpoint_param_input()`
   - Move `execute_rest_endpoint()` helper

2. Update `advanced_page.py`:
   - Remove REST testing panel
   - Add ADR line chart section:
     ```python
     def create_adr_line_chart_section(symbol: str = "nifty") -> html.Div:
         """ADR movement across the day as a line chart."""
         return html.Div([
             html.Div("ADR Movement", style=create_card_header_style()),
             dcc.Graph(
                 id="adr-line-chart",
                 figure=create_empty_chart("Loading ADR history..."),
                 style={"height": "300px"},
             ),
         ], style=create_card_style())
     ```
   - Update layout to stack ADR treemap + ADR line chart vertically

3. Update `app.py`:
   - Add import for `debugging_page`
   - Add route for `/debugging` in `display_page()` callback
   - Add callbacks for debugging page

4. Update navigation (`layouts.py` or `app.py`):
   
   **Option A: Sidebar Navigation**
   ```python
   def create_sidebar_nav(current_page: str) -> html.Div:
       pages = [
           {"id": "main", "label": "📊 Dashboard", "href": "/"},
           {"id": "advanced", "label": "📈 Advanced", "href": "/advanced"},
           {"id": "admin", "label": "⚙️ Admin", "href": "/admin"},
           {"id": "debugging", "label": "🔧 Debugging", "href": "/debugging"},
       ]
       # Vertical sidebar with icons
   ```
   
   **Option B: Dropdown Navigation**
   ```python
   def create_nav_dropdown(current_page: str) -> html.Div:
       return dcc.Dropdown(
           id="page-nav-dropdown",
           options=[
               {"label": "📊 Dashboard", "value": "/"},
               {"label": "📈 Advanced", "value": "/advanced"},
               {"label": "⚙️ Admin", "value": "/admin"},
               {"label": "🔧 Debugging", "value": "/debugging"},
           ],
           value=f"/{current_page}" if current_page != "main" else "/",
           clearable=False,
           style={"width": "200px"},
       )
   ```

**Recommendation**: Use sidebar navigation for better UX - it's always visible and doesn't require extra clicks.

---

## Summary of Fixes

| Fix ID | Title | Priority | Complexity | Status |
|--------|-------|----------|------------|--------|
| FIX-031 | Strike Range Direct Input | High | Low | ✅ COMPLETE |
| FIX-032 | Data Gap Detection & Auto-Bootstrap | Medium | Medium | ✅ COMPLETE |
| FIX-033 | Mode Tabs Implementation | High | Medium | ✅ COMPLETE |
| FIX-034 | Advanced Page Restructure | Medium | High | ✅ COMPLETE |

### Implementation Order (All Completed)

1. **FIX-031** (Strike Range) - ✅ Quick win, fixed broken functionality
2. **FIX-033** (Mode Tabs) - ✅ High visibility, improved UX
3. **FIX-034** (Page Restructure) - ✅ Larger change, completed with code cleanup
4. **FIX-032** (Data Gap Detection) - ✅ Auto-bootstrap with rate limiting

---

## Files to Modify

### Dashboard Files
- `local_iceberg_test_dashboard/src/admin_page.py`
- `local_iceberg_test_dashboard/src/api_client.py`
- `local_iceberg_test_dashboard/src/app.py`
- `local_iceberg_test_dashboard/src/layouts.py`
- `local_iceberg_test_dashboard/src/advanced_page.py`
- `local_iceberg_test_dashboard/src/state_manager.py`

### New Files
- `local_iceberg_test_dashboard/src/debugging_page.py`

### No Changes to lean_iceberg/
The API layer already supports direct strike values (`lower_strike`/`upper_strike`). The issue is entirely on the dashboard side.

---

## API Reference

### Strike Range API
```
POST /v1/admin/strike-ranges
Authorization: Bearer <jwt>

Request:
{
    "symbol": "nifty",
    "mode": "current",
    "lower_strike": 24900.0,
    "upper_strike": 25700.0,
    "effective_from": "2026-01-22"  // optional
}

Response:
{
    "id": "uuid",
    "symbol": "nifty",
    "mode": "current",
    "lower_strike": 24900.0,
    "upper_strike": 25700.0,
    "effective_from": "2026-01-22T00:00:00Z",
    "effective_until": null,
    "created_by": "user_id"
}
```

### Historical Snapshot API
```
GET /v1/dashboard/historical/snapshot?date=2026-01-20&symbols=nifty,banknifty
Authorization: Bearer <jwt>

Response:
{
    "ok": true,
    "data": {
        "nifty": { ... snapshot data ... },
        "banknifty": { ... snapshot data ... }
    },
    "meta": { "ts": "...", "cache_stale": false }
}
```
