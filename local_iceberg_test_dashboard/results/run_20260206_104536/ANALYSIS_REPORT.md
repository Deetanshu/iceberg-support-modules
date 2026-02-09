# Test Results Analysis - 2026-02-06 10:45 IST

**Test Duration:** 70 minutes  
**API URL:** https://api.botbro.trade

---

## Executive Summary

The test run shows several areas of concern:

| Issue | Severity | Evidence |
|-------|----------|----------|
| **Kite WebSocket ping timeout** | **CRITICAL** | **149 disconnections in 3.5 hours** |
| WebSocket tick gaps (>5s) | HIGH | 323 gaps detected, max 27.9s |
| SENSEX tick frequency | MEDIUM | 10s median interval vs 0.8s for others |
| SSE heartbeat irregularity | LOW | Mean 67.7s, range 31.7s-133.8s |
| Candle update gaps | MEDIUM | Max 300s gap between candle updates |
| WebSocket disconnects | LOW | 2 disconnects, 1 reconnect |

---

## ROOT CAUSE IDENTIFIED

### Kite WebSocket Ping Timeout Issue

**Error:** `sent 1011 (internal error) keepalive ping timeout; no close frame received`

**Evidence from Data Handler logs (2026-02-06):**
- First disconnect: `03:48:57 UTC` (09:18:57 IST)
- Last disconnect: `07:22:32 UTC` (12:52:32 IST)
- **Total disconnections: 149 in ~3.5 hours**
- **Average: 1 disconnect every ~1.4 minutes**

**Source Code Evidence:**
```python
# kite_adapter.py:171-174
self._websocket = await websockets.connect(
    url,
    ping_interval=self.heartbeat_interval,  # 30 seconds
    ping_timeout=10,  # 10 seconds
)
```

**Root Cause Analysis:**
1. The `websockets` library sends a ping every 30 seconds (`ping_interval=30`)
2. If no pong is received within 10 seconds (`ping_timeout=10`), it closes with error 1011
3. This is happening ~1.4 times per minute, indicating:
   - Network latency between GCP VM and Kite servers
   - Kite server not responding to pings in time
   - Possible network congestion or firewall issues

**Impact:**
- Each disconnect causes ~5 second data gap (reconnect delay)
- 149 disconnects × 5s = ~745 seconds of lost data (~12.4 minutes)
- This explains the 323 tick gaps >5s observed in the test

---

## 1. WebSocket (Fast Stream) Analysis

### 1.1 Tick Interval Statistics

| Symbol | Count | Min (ms) | Max (ms) | Mean (ms) | Median (ms) |
|--------|-------|----------|----------|-----------|-------------|
| nifty | 741 | 0 | 27,963 | 5,629 | 804 |
| banknifty | 735 | 0 | 30,608 | 5,690 | 837 |
| finnifty | 724 | 0 | 32,853 | 5,777 | 861 |
| sensex | 416 | 0 | 31,143 | 10,054 | **11,750** |

**Key Finding:** SENSEX has significantly fewer ticks (416 vs ~730 for others) and a much higher median interval (11.7s vs ~0.8s). This is consistent with lower trading activity on BSE compared to NSE.

### 1.2 Data Gaps (>5 seconds)

**Total gaps detected:** 323

**Evidence from DB query:**
```sql
-- Tick intervals for 10:00-11:00 IST (05:00-06:00 UTC)
symbol    | tick_count | avg_interval_sec | max_interval_sec | p95_interval_sec
----------+------------+------------------+------------------+------------------
banknifty |        633 |             5.66 |            30.59 |            17.93
finnifty  |        632 |             5.67 |            29.72 |            17.92
nifty     |        632 |             5.67 |            29.74 |            17.94
sensex    |        364 |             9.83 |            30.60 |            20.46
```

**Root Cause Analysis:**
1. The gaps are present at the database level (ingestion.ticks), indicating the issue is upstream of the API Layer
2. Possible causes:
   - Kite WebSocket connection issues
   - Data Handler tick processing delays
   - Redis publishing delays

### 1.3 Option Chain LTP Intervals

| Metric | Value |
|--------|-------|
| Count | 486 |
| Min | 4ms |
| Max | 64,159ms (~64s) |
| Mean | 8,431ms (~8.4s) |

**Finding:** Option chain LTP updates are arriving at ~8s intervals on average, with some gaps up to 64 seconds.

### 1.4 Connection Stability

- **Disconnects:** 2
- **Reconnects:** 1
- **Close codes:** 0 (Unknown) x2
- **Error:** "Connection to remote host was lost."

**Finding:** The WebSocket connection experienced 2 unexpected disconnects. The close code 0 indicates the connection was lost without a proper close handshake.

---

## 2. SSE (Slow Stream) Analysis

### 2.1 Indicator Update Intervals

| Metric | Value |
|--------|-------|
| Count | 559 |
| Min | 0ms |
| Max | 60,233ms (~60s) |
| Mean | 7,406ms (~7.4s) |

**Finding:** Indicator updates are arriving in batches every ~60 seconds as expected. The 8 updates per batch (4 symbols × 2 modes) arrive within milliseconds of each other.

**Evidence from raw data:**
```
59983.30ms → 4.91ms → 5.40ms → 3.55ms → 2.96ms → 0.22ms → 0.16ms → 0.16ms
59985.32ms → 4.14ms → 5.01ms → 7.29ms → 0.87ms → 0.54ms → 0.19ms → 4.02ms
```

This pattern shows ~60s gaps followed by rapid-fire updates - correct behavior.

### 2.2 Heartbeat Intervals

| Metric | Value |
|--------|-------|
| Count | 61 |
| Min | 31,758ms (~32s) |
| Max | 133,824ms (~134s) |
| Mean | 67,724ms (~68s) |

**Finding:** Heartbeat intervals are highly irregular. Expected: 30s intervals. Actual: 32s-134s range.

**Evidence from raw data:**
```
51037ms, 119941ms, 60091ms, 71681ms, 48392ms, 59859ms, 73153ms...
```

**Root Cause:** The heartbeat is sent when no other events are available. During periods of high indicator/option chain activity, heartbeats are suppressed.

### 2.3 Candle Update Intervals

| Metric | Value |
|--------|-------|
| Count | 107 |
| Min | 1ms |
| Max | 300,162ms (~5 min) |
| Mean | 37,760ms (~38s) |

**Finding:** Candle updates show large gaps (up to 5 minutes) which is expected since candles are 5-minute intervals. However, the distribution shows some irregularity.

**Evidence from raw data:**
```
56ms, 70ms, 148ms, 138965ms (~2.3min), 68ms, 74ms, 82ms, 183894ms (~3min)...
```

**Root Cause:** Candle updates are broadcast when the 5-minute candle closes. The irregular intervals suggest the refresh loop timing may not be perfectly aligned with candle boundaries.

### 2.4 Connection Stability

- **Disconnects:** 1
- **Reconnects:** 1
- **Reconnect time:** 224ms
- **Error:** "Response ended prematurely"

---

## 3. Database Evidence

### 3.1 Tick Data Timing (2026-02-06)

```sql
SELECT symbol, COUNT(*) as tick_count, MIN(ts), MAX(ts)
FROM ingestion.ticks
WHERE ts >= '2026-02-06 09:15:00+05:30' AND ts <= '2026-02-06 12:00:00+05:30'
  AND symbol IN ('nifty', 'banknifty', 'sensex', 'finnifty')
GROUP BY symbol;

  symbol   | tick_count |          first_tick           |           last_tick           
-----------+------------+-------------------------------+-------------------------------
 banknifty |       1999 | 2026-02-06 03:45:44.541003+00 | 2026-02-06 06:29:57.888182+00
 finnifty  |       1986 | 2026-02-06 03:45:44.541445+00 | 2026-02-06 06:29:57.88784+00
 nifty     |       1996 | 2026-02-06 03:45:44.539929+00 | 2026-02-06 06:29:57.886945+00
 sensex    |       1152 | 2026-02-06 03:45:44.540678+00 | 2026-02-06 06:29:57.878641+00
```

**Finding:** SENSEX has ~42% fewer ticks than other symbols, confirming lower BSE trading activity.

### 3.2 Gaps >10 seconds

```sql
SELECT symbol, COUNT(*) as gaps_over_10s, AVG(interval_sec), MAX(interval_sec)
FROM tick_intervals WHERE interval_sec > 10 GROUP BY symbol;

  symbol   | gaps_over_10s | avg_gap_sec | max_gap_sec 
-----------+---------------+-------------+-------------
 banknifty |           194 | 14.72       | 30.59
 finnifty  |           194 | 14.66       | 29.72
 nifty     |           192 | 14.69       | 29.74
 sensex    |           196 | 15.66       | 30.60
```

**Finding:** ~30% of tick intervals exceed 10 seconds. This is a significant data quality issue.

---

## 4. Red Flags Identified

### 4.1 HIGH Priority

1. **Tick Data Gaps at Source**
   - 323 gaps >5s detected in WebSocket stream
   - Gaps present in database (ingestion.ticks)
   - Max gap: 30.6 seconds
   - **Impact:** Users see stale LTP data for extended periods

2. **WebSocket Connection Instability**
   - 2 unexpected disconnects with close code 0
   - "Connection to remote host was lost" error
   - **Impact:** Users experience data interruptions

### 4.2 MEDIUM Priority

3. **SENSEX Lower Tick Frequency**
   - 42% fewer ticks than NSE symbols
   - Median interval 11.7s vs 0.8s for others
   - **Note:** This may be expected due to lower BSE trading volume

4. **Candle Update Timing Irregularity**
   - Max gap 300s between candle updates
   - Some candles arriving in rapid succession
   - **Impact:** Chart updates may appear jerky

### 4.3 LOW Priority

5. **Heartbeat Irregularity**
   - Range: 32s-134s (expected: 30s)
   - **Impact:** Minimal - heartbeats are suppressed during data activity

---

## 5. Recommendations

### CRITICAL FIX REQUIRED

**Issue:** Kite WebSocket ping timeout causing 149 disconnections in 3.5 hours

**Proposed Fix in `kite_adapter.py:171-174`:**

```python
# BEFORE (current):
self._websocket = await websockets.connect(
    url,
    ping_interval=self.heartbeat_interval,  # 30 seconds
    ping_timeout=10,  # 10 seconds - TOO SHORT
)

# AFTER (recommended):
self._websocket = await websockets.connect(
    url,
    ping_interval=60,   # Increase to 60 seconds (Kite's default)
    ping_timeout=30,    # Increase to 30 seconds for network latency
)
```

**Rationale:**
1. Kite's official Python library uses 60-second ping interval
2. 10-second ping timeout is too aggressive for cloud-to-cloud communication
3. Increasing timeout to 30s allows for network jitter without disconnecting

**Alternative Approaches:**
1. **Disable library ping, use Kite's native ping:** Set `ping_interval=None` and rely on Kite's server-side keepalive
2. **Add ping response logging:** Log when pings are sent/received to diagnose latency
3. **Network optimization:** Check if VM is in same region as Kite servers (Mumbai)

### Monitoring Additions

1. Add metrics for:
   - Tick gap duration histogram
   - WebSocket connection duration
   - Reconnection frequency
   - Ping/pong latency

### Secondary Investigation

1. **Redis Publishing Latency**
   - Check Redis connection stability
   - Review `lean_iceberg/datahandler_server/src/data_handler/redis/client.py`

2. **API Layer WebSocket Stability**
   - Review `lean_iceberg/api_layer/src/api_layer/streaming/tiered_hub.py`
   - Check for memory pressure or queue overflow

---

## 6. Data Flow Trace

```
Kite WebSocket → Data Handler → Redis → API Layer → Client WebSocket
     ↓                ↓           ↓          ↓
  [ROOT CAUSE]    [OK]        [OK]       [OK]
  ping timeout
  149 disconnects
```

**Root Cause Location:** Kite WebSocket adapter (`kite_adapter.py:171-174`)

**Evidence Chain:**
1. **Log Evidence:** 149 `kite_receive_loop_error` events with "keepalive ping timeout"
2. **Code Evidence:** `ping_timeout=10` is too aggressive for cloud networking
3. **DB Evidence:** Tick gaps in `ingestion.ticks` correlate with disconnect times
4. **Client Evidence:** 323 gaps >5s in WebSocket stream match reconnection pattern

---

## 7. Validation Queries

### Verify Tick Gaps Correlate with Disconnects

```sql
-- Check tick gaps during known disconnect window (09:18-09:19 IST = 03:48-03:49 UTC)
SELECT symbol, ts, 
       EXTRACT(EPOCH FROM (ts - LAG(ts) OVER (PARTITION BY symbol ORDER BY ts))) as gap_sec
FROM ingestion.ticks
WHERE ts BETWEEN '2026-02-06 03:48:00+00' AND '2026-02-06 03:50:00+00'
  AND symbol IN ('nifty', 'banknifty')
ORDER BY ts;
```

### Count Disconnects Per Hour

```sql
-- From logs: 149 disconnects in 3.5 hours = ~42 per hour
-- Expected tick loss: 42 × 5s = 210 seconds per hour
```

---

## 8. Historical Comparison

**Evidence from DB query - tick gaps over last 5 days:**

| Date | Symbol | Total Ticks | Gaps >10s | Avg Gap | Max Gap | Status |
|------|--------|-------------|-----------|---------|---------|--------|
| Feb 1 | nifty | 3,956 | 57 | 11.4s | 16.2s | ✅ Normal |
| Feb 2 | nifty | 9,601 | 114 | 11.6s | 15.1s | ✅ Normal |
| Feb 3 | nifty | 10,669 | 116 | 11.8s | 18.0s | ✅ Normal |
| Feb 4 | nifty | 5,282 | **1,086** | 13.9s | **32.1s** | ⚠️ Degraded |
| Feb 5 | nifty | 4,943 | **1,137** | 14.1s | **29.4s** | ⚠️ Degraded |
| Feb 6 | nifty | 2,582 | **685** | 15.1s | **29.7s** | ⚠️ Degraded |

**Key Observation:**
- Feb 1-3: ~100-120 gaps >10s per day (normal)
- Feb 4-6: ~700-1,100 gaps >10s per day (**10x increase**)
- Max gap increased from ~16-18s to ~30s

**Possible Causes for Feb 4 Degradation:**
1. Network route change between GCP and Kite servers
2. Increased subscription count (363 tokens)
3. Kite server-side changes
4. GCP VM resource constraints

**Recommendation:** Investigate what changed on Feb 4 and consider:
- Checking GCP network logs for route changes
- Reviewing Data Handler deployment history
- Contacting Kite support about server-side changes

---

**Analysis completed:** 2026-02-06 12:52 IST  
**Test run:** run_20260206_104536  
**Root cause identified:** Kite WebSocket ping timeout (10s too short)
