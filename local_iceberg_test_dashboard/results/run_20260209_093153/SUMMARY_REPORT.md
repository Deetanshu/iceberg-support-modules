# Full Flow Validation Report

**Run Timestamp:** 20260209_093153
**Duration:** 10 minutes
**API URL:** https://api.botbro.trade

## Bootstrap
- Success: True
- Response Time: 271ms
- Symbols: ['nifty', 'banknifty', 'sensex', 'finnifty']

## WebSocket (Fast Stream)
- Connected: True
- Connection Time: 171ms
- Total Messages: 100
- Disconnects: 1
- Reconnects: 0
- Data Gaps (>5s): 1
- Symbols Seen: ['banknifty', 'finnifty', 'nifty', 'sensex']
- Pings/Pongs: 19/19

### Events by Type
- option_chain_ltp: 72
- ping: 19
- snapshot: 1
- tick: 8

### Tick Intervals - Overall (ms)
- Count: 7
- Min: 0
- Max: 422779
- Mean: 60398
- Median: 0
- Std Dev: 159795

### Tick Intervals - Per Symbol (ms)

**banknifty:**
- Count: 1
- Min: 5
- Max: 5
- Mean: 5
- Median: 5

**finnifty:**
- Count: 1
- Min: 0
- Max: 0
- Mean: 0
- Median: 0

**nifty:**
- Count: 2
- Min: 2
- Max: 422779
- Mean: 211391
- Median: 211391

### Option Chain LTP Intervals (ms)
- Count: 71
- Min: 627
- Max: 62149
- Mean: 8200

### Close Codes
- 0 (Unknown): 1
- Unexpected closes: 0

## SSE (Slow Stream)
- Connected: True
- Connection Time: 167ms
- Total Messages: 144
- Disconnects: 0
- Reconnects: 0
- Indicator Gaps (>90s): 0
- Symbols Seen: ['banknifty', 'data', 'finnifty', 'market_state', 'nifty', 'sensex']

### Events by Type
- candle_update: 16
- heartbeat: 8
- indicator_update: 80
- option_chain_update: 32
- snapshot: 8

### Indicator Update Intervals (ms)
- Count: 79
- Min: 0
- Max: 60052
- Mean: 6835

### Heartbeat Intervals (ms)
- Count: 7
- Min: 52599
- Max: 120042
- Mean: 76087

### Candle Update Intervals (ms)
- Count: 15
- Min: 1
- Max: 231010
- Mean: 25383

### Candle Updates by Symbol
- banknifty: 4
- finnifty: 4
- nifty: 4
- sensex: 4