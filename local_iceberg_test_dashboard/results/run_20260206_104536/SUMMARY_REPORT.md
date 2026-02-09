# Full Flow Validation Report

**Run Timestamp:** 20260206_104536
**Duration:** 70 minutes
**API URL:** https://api.botbro.trade

## Bootstrap
- Success: True
- Response Time: 1381ms
- Symbols: ['nifty', 'banknifty', 'sensex', 'finnifty']

## WebSocket (Fast Stream)
- Connected: True
- Connection Time: 409ms
- Total Messages: 3252
- Disconnects: 2
- Reconnects: 1
- Data Gaps (>5s): 323
- Symbols Seen: ['banknifty', 'finnifty', 'nifty', 'sensex']
- Pings/Pongs: 138/138

### Events by Type
- option_chain_ltp: 488
- ping: 138
- snapshot: 2
- tick: 2624

### Tick Intervals - Overall (ms)
- Count: 2622
- Min: 0
- Max: 27963
- Mean: 1595
- Median: 0
- Std Dev: 4265

### Tick Intervals - Per Symbol (ms)

**banknifty:**
- Count: 735
- Min: 0
- Max: 30608
- Mean: 5690
- Median: 837

**finnifty:**
- Count: 724
- Min: 0
- Max: 32853
- Mean: 5777
- Median: 861

**nifty:**
- Count: 741
- Min: 0
- Max: 27963
- Mean: 5629
- Median: 804

**sensex:**
- Count: 416
- Min: 0
- Max: 31143
- Mean: 10054
- Median: 11750

### Option Chain LTP Intervals (ms)
- Count: 486
- Min: 4
- Max: 64159
- Mean: 8431

### Close Codes
- 0 (Unknown): 2
- Unexpected closes: 0

### Errors
- Connection to remote host was lost.

## SSE (Slow Stream)
- Connected: True
- Connection Time: 175ms
- Total Messages: 959
- Disconnects: 1
- Reconnects: 1
- Indicator Gaps (>90s): 0
- Symbols Seen: ['banknifty', 'data', 'finnifty', 'market_state', 'nifty', 'sensex']

### Events by Type
- candle_update: 108
- heartbeat: 62
- indicator_update: 560
- option_chain_update: 213
- snapshot: 16

### Indicator Update Intervals (ms)
- Count: 559
- Min: 0
- Max: 60233
- Mean: 7406

### Heartbeat Intervals (ms)
- Count: 61
- Min: 31758
- Max: 133824
- Mean: 67724

### Candle Update Intervals (ms)
- Count: 107
- Min: 1
- Max: 300162
- Mean: 37760

### Candle Updates by Symbol
- banknifty: 27
- finnifty: 27
- nifty: 27
- sensex: 27

### Errors
- Response ended prematurely