# FIX-030: Dashboard Indicator Display Fixes

**Date:** 2026-01-22  
**Status:** IMPLEMENTED  
**Priority:** Medium  
**Component:** Test Dashboard (local_iceberg_test_dashboard)

## Overview

This fix addresses three related issues in the test dashboard:
1. Symbol changer reverting immediately after selection
2. ADR and RSI values not displaying in the indicators panel
3. Intuition text (AI insight) not showing

## Issue 1: Symbol Changer Reverting

### Problem
When clicking a symbol card to change the selected symbol, it would change for a millisecond and then revert back to the previous symbol.

### Root Cause
In `layouts.py`, the `create_symbol_card()` function set `n_clicks=0` every time symbol cards were recreated. Since the `update_ltp_display` callback runs every 500ms and recreates all symbol cards, this reset the click state, causing the symbol selection callback to not detect the click properly.

### Solution
Removed `n_clicks=0` from `create_symbol_card()` in `layouts.py`. Dash components maintain their own click state, so explicitly setting it to 0 on recreation was interfering with the callback detection.

### Files Changed
| File | Change |
|------|--------|
| `local_iceberg_test_dashboard/src/layouts.py` | Removed `n_clicks=0` from `create_symbol_card()` |

---

## Issue 2: ADR and RSI Not Displaying

### Problem
The ADR (Advance/Decline Ratio) and RSI (Relative Strength Index) values were not showing in the indicators panel, even though the data was present in the bootstrap response.

### Root Cause
In `app.py`, the `_populate_state_from_bootstrap()` function extracted `rsi_arr` and `adr_arr` from `technical_indicators` but never used them to populate the current indicator values. The code only populated EMA history, not the latest RSI/ADR values.

### Solution
Added comprehensive indicator parsing in `_populate_state_from_bootstrap()` to:
1. Extract latest RSI and ADR values from `technical_indicators` arrays
2. Create a `current_indicators` IndicatorData object with all latest values
3. Call `state_manager.update_indicators()` to populate the state

### Files Changed
| File | Change |
|------|--------|
| `local_iceberg_test_dashboard/src/app.py` | Added extraction of latest RSI, ADR, EMA values from `technical_indicators` and creation of comprehensive `current_indicators` object |

---

## Issue 3: Intuition Text Not Showing

### Problem
The AI-generated market insight text (intuition) was not displaying in the dashboard, even though it was present in the bootstrap response.

### Root Cause
Three issues:
1. The `IndicatorData` model didn't have an `intuition_text` field
2. Bootstrap parsing didn't extract `intuition_engine.text` from the response
3. The UI layout didn't have a section to display the intuition text

### API Spec Reference
Per `iceberg_ai_context/40_DEV_API_SPEC.md`:
- Bootstrap: `intuition_engine.text` at mode level (e.g., `data.nifty.current.intuition_engine.text`)
- SSE `indicator_update`: `intuition_text` field at event level

### Solution
1. Added `intuition_text: Optional[str] = None` field to `IndicatorData` model
2. Added parsing of `intuition_engine.text` from bootstrap in `_populate_state_from_bootstrap()`
3. Added parsing of `intuition_text` from SSE `indicator_update` events in `parsers.py`
4. Added "AI Insight" display section to `create_indicators_panel()` in `layouts.py`

### Files Changed
| File | Change |
|------|--------|
| `local_iceberg_test_dashboard/src/models.py` | Added `intuition_text: Optional[str] = None` field to `IndicatorData` |
| `local_iceberg_test_dashboard/src/app.py` | Added extraction of `intuition_engine.text` from bootstrap |
| `local_iceberg_test_dashboard/src/parsers.py` | Added `intuition_text=event.get("intuition_text")` to `parse_indicator_update()` |
| `local_iceberg_test_dashboard/src/layouts.py` | Added "AI Insight" section to `create_indicators_panel()` |

---

## Traceability

```
REQ: 10.5 (Symbol selection updates all displays)
REQ: 8.5 (Display ADR value)
REQ: 8.6 (Display RSI value with overbought/oversold highlighting)
REQ: 8.7 (Display AI-generated intuition text)
→ Code: local_iceberg_test_dashboard/src/layouts.py
→ Code: local_iceberg_test_dashboard/src/app.py
→ Code: local_iceberg_test_dashboard/src/models.py
→ Code: local_iceberg_test_dashboard/src/parsers.py
→ Docs: local_iceberg_test_dashboard/fix_plan/2026-01-22/FIX_030_DASHBOARD_INDICATOR_FIXES.md
```

## Validation

```bash
# Run all dashboard tests
cd local_iceberg_test_dashboard
python -m pytest tests/ -v
# Expected: 201 passed
```

## Visual Results

### Symbol Changer
- Before: Symbol changes for a millisecond then reverts
- After: Symbol selection persists and updates all displays

### ADR/RSI Display
- Before: ADR and RSI show "--" even with data present
- After: ADR and RSI values display correctly with proper formatting

### Intuition Text
- Before: No AI insight section visible
- After: "AI Insight" section displays below indicators with styled text box

## Related Fixes

- FIX-029: Skew/PCR and EMA Chart Deduplication (same session)
