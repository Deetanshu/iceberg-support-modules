# Full Flow Validation Report

**Run Timestamp:** 20260209_120731
**Duration:** 10 minutes
**API URL:** https://api.botbro.trade

## Bootstrap
- Success: True
- Response Time: 258ms
- Symbols: ['nifty', 'banknifty', 'sensex', 'finnifty']

## WebSocket (Fast Stream)
- Connected: True
- Connection Time: 230ms
- Total Messages: 4051
- Disconnects: 1
- Reconnects: 0
- Data Gaps (>5s): 2
- Symbols Seen: ['banknifty', 'finnifty', 'nifty', 'sensex']
- Pings/Pongs: 19/19

### Events by Type
- option_chain_ltp: 48
- ping: 19
- snapshot: 1
- tick: 3983

### Tick Intervals - Overall (ms)
- Count: 3982
- Min: 0
- Max: 6253
- Mean: 151
- Median: 1
- Std Dev: 258

### Tick Intervals - Per Symbol (ms)

**banknifty:**
- Count: 1136
- Min: 0
- Max: 7212
- Mean: 528
- Median: 501

**finnifty:**
- Count: 1131
- Min: 0
- Max: 9053
- Mean: 530
- Median: 506

**nifty:**
- Count: 1126
- Min: 0
- Max: 8369
- Mean: 532
- Median: 501

**sensex:**
- Count: 586
- Min: 0
- Max: 11243
- Mean: 1021
- Median: 1002

### Option Chain LTP Intervals (ms)
- Count: 47
- Min: 1389
- Max: 66688
- Mean: 10132

### Close Codes
- 0 (Unknown): 1
- Unexpected closes: 0

## SSE (Slow Stream)
- Connected: True
- Connection Time: 181ms
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
- Max: 60154
- Mean: 6836

### Heartbeat Intervals (ms)
- Count: 7
- Min: 59977
- Max: 125536
- Mean: 77944

### Candle Update Intervals (ms)
- Count: 15
- Min: 76
- Max: 281156
- Mean: 23188

### Candle Updates by Symbol
- banknifty: 4
- finnifty: 4
- nifty: 4
- sensex: 4