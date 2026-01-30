# FIX-029: Skew/PCR and EMA Chart Deduplication

**Date:** 2026-01-22  
**Status:** IMPLEMENTED  
**Priority:** Medium  
**Component:** Test Dashboard (local_iceberg_test_dashboard)

## Problem

The Skew/PCR and EMA charts in the test dashboard were displaying multiple lines instead of a single clean line. This was caused by:

1. **No timestamp deduplication**: Every call to `update_indicators()` appended a new entry to history, even if an entry for the same time period already existed
2. **Redundant "latest" entry**: After populating history from bootstrap series data, the code added one more entry with `datetime.now()` timestamp, creating a duplicate with a different timestamp
3. **No history clearing on re-bootstrap**: When bootstrap was called multiple times (reconnect, refresh), history accumulated without being cleared
4. **Unsorted history**: History entries weren't guaranteed to be in timestamp order

## Root Cause

In `state_manager.py`, the `update_indicators()` method blindly appended entries:
```python
self.skew_pcr_history[symbol][mode].append(
    (indicators.ts, indicators.skew, indicators.pcr)
)
```

In `app.py`, after the bootstrap loop, an extra entry was added:
```python
indicators = IndicatorData(
    skew=latest_skew,
    pcr=latest_pcr,
    ts=datetime.now(IST),  # Different timestamp than actual data!
)
state_manager.update_indicators(symbol, mode, indicators)
```

## Solution

### 1. Candle-Aligned Timestamps (state_manager.py)

Added `floor_to_5min_boundary()` function to align all indicator timestamps to 5-minute candle boundaries:
```python
def floor_to_5min_boundary(ts: datetime) -> datetime:
    """Floor a timestamp to the nearest 5-minute candle boundary."""
    total_minutes = ts.hour * 60 + ts.minute
    floored_minutes = (total_minutes // 5) * 5
    return ts.replace(
        hour=floored_minutes // 60,
        minute=floored_minutes % 60,
        second=0,
        microsecond=0
    )
```

### 2. Deduplication in update_indicators() (state_manager.py)

Modified `update_indicators()` to:
- Floor timestamps to 5-minute boundaries
- Check for existing entries at the same candle bucket
- Update existing entries instead of appending duplicates (last value wins)

### 3. Sorted History Retrieval (state_manager.py)

Modified `get_ema_history()` and `get_skew_pcr_history()` to return sorted copies:
```python
return sorted(self.skew_pcr_history[symbol][mode], key=lambda x: x[0])
```

### 4. Clear History Before Bootstrap (state_manager.py + app.py)

Added `clear_indicator_history()` method and call it at the start of bootstrap parsing:
```python
state_manager.clear_indicator_history()
```

### 5. Removed Redundant Latest Entry (app.py)

Removed the code that added an extra entry with `datetime.now()` after the bootstrap loop.

## Files Changed

| File | Change |
|------|--------|
| `local_iceberg_test_dashboard/src/state_manager.py` | Added `floor_to_5min_boundary()`, modified `update_indicators()` for deduplication, added `clear_indicator_history()`, sorted history in getters |
| `local_iceberg_test_dashboard/src/app.py` | Added `clear_indicator_history()` call before bootstrap, removed redundant latest entry code |
| `local_iceberg_test_dashboard/tests/test_state_manager.py` | Updated test to expect floored timestamps |

## Traceability

```
REQ: 8.1 (Display Skew with color coding)
REQ: 8.2 (Display PCR value)
REQ: 7.1 (Display EMA chart)
→ Code: local_iceberg_test_dashboard/src/state_manager.py
→ Code: local_iceberg_test_dashboard/src/app.py
→ Tests: local_iceberg_test_dashboard/tests/test_state_manager.py
→ Docs: local_iceberg_test_dashboard/fix_plan/2026-01-22/FIX_029_SKEW_EMA_CHART_DEDUPLICATION.md
```

## Validation

```bash
# Run state manager tests
cd local_iceberg_test_dashboard
python -m pytest tests/test_state_manager.py -v
# Expected: 57 passed
```

## Visual Result

Before: Multiple overlapping lines in Skew/PCR and EMA charts due to duplicate entries
After: Single clean line per indicator, aligned to 5-minute candle boundaries
