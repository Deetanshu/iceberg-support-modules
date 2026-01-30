# FIX-035: ADR and RSI History Tracking

**Date:** 2026-01-22
**Status:** COMPLETE
**Scope:** local_iceberg_test_dashboard only

## Problem

The ADR line chart in the Advanced page was fetching data from the snapshot API endpoint, which doesn't return historical ADR data. The chart would only show a single point or no data.

The proper approach is:
1. Load initial ADR/RSI history from bootstrap's `technical_indicators` array
2. Accumulate new values from SSE `indicator_update` events throughout the session
3. Read from accumulated state for chart rendering

## Solution

### 1. StateManager Changes (`state_manager.py`)

Added new history tracking:
```python
# ADR history for charting: (timestamp, adr)
self.adr_history: Dict[str, List[Tuple[datetime, float]]] = {}

# RSI history for charting: (timestamp, rsi)
self.rsi_history: Dict[str, List[Tuple[datetime, float]]] = {}
```

Updated `update_indicators()` to accumulate ADR and RSI values (candle-aligned, deduplicated).

Added getter methods:
- `get_adr_history(symbol)` → List of (timestamp, adr) tuples
- `get_rsi_history(symbol)` → List of (timestamp, rsi) tuples

Updated `clear_indicator_history()` and `clear()` to include new arrays.

### 2. Bootstrap Parsing Changes (`app.py`)

Modified technical_indicators parsing to include ADR and RSI:
```python
adr_val = adr_arr[i] if i < len(adr_arr) else None
rsi_val = rsi_arr[i] if i < len(rsi_arr) else None

ema_indicators = IndicatorData(
    ema_5=ema_9_val,
    ema_21=ema_21_val,
    adr=adr_val,
    rsi=rsi_val,
    ts=ts_ist,
)
state_manager.update_indicators(symbol, "current", ema_indicators)
```

### 3. Advanced Page Changes (`advanced_page.py`)

Changed `fetch_adr_history()` to read from state manager instead of API:
```python
async def fetch_adr_history(symbol: str, state_manager: StateManager) -> List[Dict[str, Any]]:
    adr_history = state_manager.get_adr_history(symbol)
    return [{"timestamp": ts.isoformat(), "adr": adr} for ts, adr in adr_history]
```

Updated callback in `app.py` to pass `state_manager` instead of `api_client`.

## Data Flow

```
Bootstrap API → technical_indicators.adr[] → state_manager.adr_history
                                           ↓
SSE indicator_update → indicators.adr → state_manager.update_indicators()
                                           ↓
Advanced Page → state_manager.get_adr_history() → Line Chart
```

## Files Changed

| File | Changes |
|------|---------|
| `src/state_manager.py` | Added `adr_history`, `rsi_history` dicts; `get_adr_history()`, `get_rsi_history()` methods; updated `update_indicators()`, `clear_indicator_history()`, `clear()` |
| `src/advanced_page.py` | Changed `fetch_adr_history()` to use state_manager |
| `src/app.py` | Updated bootstrap parsing to include ADR/RSI; updated ADR refresh callback |

## Validation

- [ ] Dashboard starts without errors
- [ ] Bootstrap populates ADR/RSI history from `technical_indicators`
- [ ] SSE events accumulate new ADR/RSI values
- [ ] ADR line chart shows historical data throughout the day
- [ ] RSI history available for future charting use
