# Full Flow Validation Report

**Run Timestamp:** 20260205_115615
**Duration:** 20 minutes
**API URL:** https://api.botbro.trade

## Bootstrap
- Success: True
- Response Time: 312ms
- Symbols: ['nifty', 'banknifty', 'sensex', 'finnifty']

## WebSocket (Fast Stream)
- Connected: True
- Connection Time: 284ms
- Total Messages: 1053
- Disconnects: 4
- Reconnects: 3
- Data Gaps (>5s): 94
- Symbols Seen: ['banknifty', 'finnifty', 'nifty', 'sensex']
- Pings/Pongs: 39/39

### Events by Type
- option_chain_ltp: 133
- ping: 39
- snapshot: 4
- tick: 877

### Tick Intervals - Overall (ms)
- Count: 873
- Min: 0
- Max: 27606
- Mean: 1301
- Median: 0
- Std Dev: 3722

### Tick Intervals - Per Symbol (ms)

**banknifty:**
- Count: 241
- Min: 0
- Max: 27607
- Mean: 4711
- Median: 746

**finnifty:**
- Count: 249
- Min: 0
- Max: 27607
- Mean: 4562
- Median: 742

**nifty:**
- Count: 239
- Min: 0
- Max: 27607
- Mean: 4753
- Median: 742

**sensex:**
- Count: 132
- Min: 0
- Max: 27607
- Mean: 8606
- Median: 9196

### Option Chain LTP Intervals (ms)
- Count: 129
- Min: 45
- Max: 62971
- Mean: 7137

### Close Codes
- 0 (Unknown): 4
- Unexpected closes: 0

### Errors
- Connection to remote host was lost.
- Connection to remote host was lost.
- Connection to remote host was lost.

## SSE (Slow Stream)
- Connected: True
- Connection Time: 356ms
- Total Messages: 291
- Disconnects: 3
- Reconnects: 3
- Indicator Gaps (>90s): 0
- Symbols Seen: ['banknifty', 'data', 'finnifty', 'market_state', 'nifty', 'sensex']

### Events by Type
- candle_update: 28
- heartbeat: 17
- indicator_update: 160
- option_chain_update: 54
- snapshot: 32

### Indicator Update Intervals (ms)
- Count: 159
- Min: 0
- Max: 60109
- Mean: 7170

### Heartbeat Intervals (ms)
- Count: 16
- Min: 59929
- Max: 120048
- Mean: 71252

### Candle Update Intervals (ms)
- Count: 27
- Min: 0
- Max: 298879
- Mean: 33423

### Candle Updates by Symbol
- banknifty: 7
- finnifty: 7
- nifty: 7
- sensex: 7