# Full Flow Validation Report

**Run Timestamp:** 20260204_152059
**Duration:** 6 minutes
**API URL:** https://api.botbro.trade

## Bootstrap
- Success: True
- Response Time: 432ms
- Symbols: ['nifty', 'banknifty', 'sensex', 'finnifty']

## WebSocket (Fast Stream)
- Connected: True
- Connection Time: 216ms
- Total Messages: 313
- Disconnects: 2
- Symbols Seen: ['banknifty', 'finnifty', 'nifty', 'sensex']
- Pings/Pongs: 11/11

### Events by Type
- option_chain_ltp: 40
- ping: 11
- snapshot: 2
- tick: 260

### Tick Intervals (ms)
- Count: 259
- Min: 0
- Max: 30031
- Mean: 1362
- Median: 0
- Std Dev: 3721

### Option Chain LTP Intervals (ms)
- Count: 39
- Min: 64
- Max: 62258
- Mean: 7156

### Errors
- Connection to remote host was lost.
- FullFlowValidator._log() got multiple values for argument 'message'
- FullFlowValidator._log() got multiple values for argument 'message'

## SSE (Slow Stream)
- Connected: True
- Connection Time: 223ms
- Total Messages: 85
- Disconnects: 1
- Symbols Seen: ['banknifty', 'data', 'finnifty', 'market_state', 'nifty', 'sensex']

### Events by Type
- heartbeat: 5
- indicator_update: 48
- option_chain_update: 16
- snapshot: 16

### Indicator Update Intervals (ms)
- Count: 47
- Min: 0
- Max: 60300
- Mean: 6382

### Heartbeat Intervals (ms)
- Count: 4
- Min: 54274
- Max: 120005
- Mean: 75004