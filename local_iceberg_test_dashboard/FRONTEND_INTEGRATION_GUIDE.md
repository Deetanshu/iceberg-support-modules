# Iceberg API - Frontend Integration Guide

**For Next.js Frontend Engineers**  
**API Base URL:** `https://api.botbro.trade`  
**Last Updated:** 2026-01-23

---

## Table of Contents

1. [Overview](#1-overview)
2. [Authentication Flow](#2-authentication-flow)
3. [Bootstrap Data](#3-bootstrap-data)
4. [Real-Time Streaming](#4-real-time-streaming)
5. [Admin API](#5-admin-api)
6. [Error Handling](#6-error-handling)
7. [TypeScript Interfaces](#7-typescript-interfaces)

---

## 1. Overview

### API Response Envelope

**Every REST endpoint returns this envelope:**

```typescript
interface APIResponse<T> {
  ok: boolean;
  data: T | null;
  error: ErrorDetail | null;
  meta: ResponseMeta;
}

interface ResponseMeta {
  request_id: string;
  server_time: string;  // ISO 8601 UTC
  cache_stale: boolean;
  market_state: "OPEN" | "CLOSED" | "UNKNOWN";
}

interface ErrorDetail {
  code: string;
  message: string;
  details?: Record<string, any>;
}
```

### Supported Symbols

```typescript
const SYMBOLS = ["nifty", "banknifty", "sensex", "finnifty"] as const;
type Symbol = typeof SYMBOLS[number];
```

### Supported Modes

```typescript
const MODES = ["current", "positional"] as const;
type Mode = typeof MODES[number];
// current = weekly expiry, positional = monthly expiry
```


---

## 2. Authentication Flow

### Step 1: Google OAuth Login

Redirect user to Google OAuth with your client ID. After user consents, Google redirects back with an authorization code.

### Step 2: Exchange Code for JWT

**Endpoint:** `POST /v1/auth/google/exchange`

```typescript
// Request
const response = await fetch("https://api.botbro.trade/v1/auth/google/exchange", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    authorization_code: "4/0AX4XfWh..."  // From Google OAuth redirect
  })
});

const result: APIResponse<AuthExchangeResponse> = await response.json();
```

**Response Shape:**

```typescript
interface AuthExchangeResponse {
  access: "ALLOWED" | "DENIED";
  token: string | null;           // JWT token (store securely)
  user: UserInfo | null;
  user_exists: boolean | null;
  subscription: SubscriptionInfo | null;
  next: "DASHBOARD" | "SUBSCRIBE" | "SUBSCRIBE_OR_TRIAL" | "PENDING_APPROVAL";
}

interface UserInfo {
  id: string;
  email: string;
  name: string;
  role: "admin" | "customer" | "test_customer";
}

interface SubscriptionInfo {
  status: string;
  valid_until: string | null;  // ISO 8601
}
```

**Example Response:**

```json
{
  "ok": true,
  "data": {
    "access": "ALLOWED",
    "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "user": {
      "id": "usr_abc123",
      "email": "trader@example.com",
      "name": "John Trader",
      "role": "customer"
    },
    "subscription": {
      "status": "active",
      "valid_until": "2026-02-23T00:00:00+05:30"
    },
    "next": "DASHBOARD"
  },
  "error": null,
  "meta": {
    "request_id": "req_xyz789",
    "server_time": "2026-01-23T10:30:00Z",
    "cache_stale": false,
    "market_state": "OPEN"
  }
}
```

### Step 3: Use JWT for Authenticated Requests

```typescript
// All authenticated requests need Authorization header
const headers = {
  "Authorization": `Bearer ${jwtToken}`,
  "Content-Type": "application/json"
};
```

### Step 4: Get Current User Info

**Endpoint:** `GET /v1/auth/me`

```typescript
const response = await fetch("https://api.botbro.trade/v1/auth/me", {
  headers: { "Authorization": `Bearer ${jwtToken}` }
});
```

### Step 5: Refresh JWT Token

JWT tokens expire after 8 hours. Refresh when < 1 hour remaining.

**Endpoint:** `POST /v1/auth/refresh`

```typescript
const response = await fetch("https://api.botbro.trade/v1/auth/refresh", {
  method: "POST",
  headers: { "Authorization": `Bearer ${jwtToken}` }
});

const result = await response.json();
const newToken = result.data?.token;  // Store this new token
```


---

## 3. Bootstrap Data

Bootstrap provides all initial data needed to render the dashboard. Call this once on page load.

### Endpoint: `GET /v1/dashboard/bootstrap`

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `symbols` | string | all | Comma-separated: `nifty,banknifty` |
| `include_candles` | boolean | `false` | Include 5m OHLCV candles |
| `include_option_chain` | boolean | `true` | Include option chain data |
| `include_indicators` | boolean | `false` | Include EMA, RSI, ADR timeseries |

**Request:**

```typescript
const params = new URLSearchParams({
  include_candles: "true",
  include_option_chain: "true",
  include_indicators: "true"
});

const response = await fetch(
  `https://api.botbro.trade/v1/dashboard/bootstrap?${params}`,
  { headers: { "Authorization": `Bearer ${jwtToken}` } }
);

const result: APIResponse<BootstrapData> = await response.json();
```

### Bootstrap Response Shape

```typescript
interface BootstrapData {
  nifty: ModePayload;
  banknifty: ModePayload;
  sensex: ModePayload;
  finnifty: ModePayload;
}

interface ModePayload {
  current: SymbolPayload | null;      // Weekly expiry data
  positional: SymbolPayload | null;   // Monthly expiry data
  candles_5m: CandleData | null;      // Symbol-level (same for both modes)
  technical_indicators: TechnicalIndicators | null;  // Symbol-level
}

interface SymbolPayload {
  as_of: string;                      // ISO 8601 timestamp
  indicator_chart: IndicatorChart;
  option_chain: OptionChainData | null;
  intuition_engine: IntuitionEngine | null;
}
```


### Indicator Chart (Mode-Specific: Skew, PCR)

```typescript
interface IndicatorChart {
  levels: {
    upper: number;  // 30 (for skew chart Y-axis)
    lower: number;  // -30
  };
  series: IndicatorSeries;
}

interface IndicatorSeries {
  ts: string[];           // ISO timestamps, aligned to 5-min candles
  skew: (number | null)[];  // Range: -1.0 to +1.0
  pcr: (number | null)[];   // Put-Call Ratio, typically 0.5 to 2.0
}
```

### Technical Indicators (Symbol-Level)

```typescript
interface TechnicalIndicators {
  ts: string[];               // ISO timestamps
  rsi: (number | null)[];     // 0-100
  ema_9: (number | null)[];   // 9-period EMA price
  ema_21: (number | null)[];  // 21-period EMA price
  adr: (number | null)[];     // Advance/Decline Ratio
}
```

### Candle Data (Symbol-Level)

```typescript
interface CandleData {
  ts: string[];      // ISO timestamps (5-min intervals)
  open: number[];
  high: number[];
  low: number[];
  close: number[];
  volume: number[];
}
```

### Option Chain Data (Mode-Specific)

```typescript
interface OptionChainData {
  expiry: string;       // "2026-01-30"
  underlying: number;   // Current index LTP (e.g., 24850.50)
  ts: string;           // Last update timestamp
  columns: OptionChainColumns;
}

interface OptionChainColumns {
  strike: number[];     // [24700, 24750, 24800, 24850, ...]
  call_oi: number[];    // Open Interest for calls
  put_oi: number[];     // Open Interest for puts
  skew: number[];       // Per-strike skew values
  call_vol: number[];   // Call volume
  put_vol: number[];    // Put volume
}
```

### Intuition Engine (AI Insights)

```typescript
interface IntuitionEngine {
  ts_bucket: string;  // Timestamp of analysis
  text: string;       // AI-generated market insight text
}
```


### Full Bootstrap Response Example

```json
{
  "ok": true,
  "data": {
    "nifty": {
      "current": {
        "as_of": "2026-01-23T10:25:00+05:30",
        "indicator_chart": {
          "levels": { "upper": 30, "lower": -30 },
          "series": {
            "ts": ["2026-01-23T09:20:00+05:30", "2026-01-23T09:25:00+05:30"],
            "skew": [0.15, 0.18],
            "pcr": [0.92, 0.95]
          }
        },
        "option_chain": {
          "expiry": "2026-01-30",
          "underlying": 24850.50,
          "ts": "2026-01-23T10:25:00+05:30",
          "columns": {
            "strike": [24700, 24750, 24800, 24850, 24900],
            "call_oi": [125000, 180000, 250000, 320000, 280000],
            "put_oi": [95000, 140000, 200000, 280000, 350000],
            "skew": [-0.12, -0.08, 0.05, 0.12, 0.18],
            "call_vol": [5000, 8000, 12000, 15000, 10000],
            "put_vol": [4000, 6000, 10000, 12000, 14000]
          }
        },
        "intuition_engine": {
          "ts_bucket": "2026-01-23T10:25:00+05:30",
          "text": "NIFTY showing bullish bias with positive skew. PCR rising suggests put writing activity."
        }
      },
      "positional": {
        "as_of": "2026-01-23T10:25:00+05:30",
        "indicator_chart": { "levels": { "upper": 30, "lower": -30 }, "series": { "ts": [], "skew": [], "pcr": [] } },
        "option_chain": null,
        "intuition_engine": null
      },
      "candles_5m": {
        "ts": ["2026-01-23T09:15:00+05:30", "2026-01-23T09:20:00+05:30"],
        "open": [24800.00, 24825.50],
        "high": [24830.00, 24860.00],
        "low": [24795.00, 24820.00],
        "close": [24825.50, 24850.50],
        "volume": [1250000, 980000]
      },
      "technical_indicators": {
        "ts": ["2026-01-23T09:20:00+05:30", "2026-01-23T09:25:00+05:30"],
        "rsi": [52.5, 54.2],
        "ema_9": [24820.00, 24835.00],
        "ema_21": [24780.00, 24795.00],
        "adr": [1.25, 1.30]
      }
    },
    "banknifty": { /* same structure */ },
    "sensex": { /* same structure */ },
    "finnifty": { /* same structure */ }
  },
  "error": null,
  "meta": {
    "request_id": "req_abc123",
    "server_time": "2026-01-23T04:55:00Z",
    "cache_stale": false,
    "market_state": "OPEN"
  }
}
```


### ADR Constituents (Separate Endpoint)

For ADR treemap visualization, fetch constituent details separately:

**Endpoint:** `GET /v1/dashboard/adr/constituents?symbol=nifty`

```typescript
const response = await fetch(
  "https://api.botbro.trade/v1/dashboard/adr/constituents?symbol=nifty",
  { headers: { "Authorization": `Bearer ${jwtToken}` } }
);
```

**Response:**

```json
{
  "ok": true,
  "data": {
    "symbol": "nifty",
    "constituents": [
      { "symbol": "RELIANCE", "ltp": 2450.50, "change_pct": 1.25, "status": "advancing" },
      { "symbol": "TCS", "ltp": 3850.00, "change_pct": -0.50, "status": "declining" },
      { "symbol": "HDFCBANK", "ltp": 1680.25, "change_pct": 0.00, "status": "unchanged" }
    ],
    "summary": {
      "total": 50,
      "advancing": 28,
      "declining": 18,
      "unchanged": 4
    }
  },
  "meta": { /* ... */ }
}
```

---

## 4. Real-Time Streaming

The API provides two streaming channels:

| Stream | Protocol | Update Frequency | Data |
|--------|----------|------------------|------|
| Fast Stream | WebSocket | Sub-second | LTP (Last Traded Price) |
| Slow Stream | SSE | 60 seconds | Indicators (Skew, PCR, RSI, EMA, etc.) |

### 4.1 Slow Stream (SSE) - Indicators

**Endpoint:** `GET /v1/stream/indicators/tiered`

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `token` | string | required | JWT token |
| `symbols` | string | `nifty,banknifty` | Comma-separated symbols |
| `modes` | string | `current,positional` | Comma-separated modes |
| `include_optional` | boolean | `true` | Include RSI, EMA, BB, VWAP |

**Next.js Implementation:**

```typescript
// hooks/useIndicatorStream.ts
import { useEffect, useRef, useCallback } from 'react';

interface IndicatorUpdate {
  symbol: string;
  mode: string;
  indicators: {
    skew: number | null;
    raw_skew: number | null;
    pcr: number | null;
    adr: number | null;
    signal: string;
    skew_confidence: number;
    rsi: number | null;
    ema_5: number | null;
    ema_9: number | null;
    ema_21: number | null;
    bb_upper: number | null;
    bb_middle: number | null;
    bb_lower: number | null;
    vwap: number | null;
  };
  intuition_text: string | null;
  timestamp: string;
}

export function useIndicatorStream(
  jwtToken: string,
  onUpdate: (data: IndicatorUpdate) => void,
  onSnapshot: (data: Record<string, any>) => void
) {
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout>();
  const reconnectDelayRef = useRef(1000);

  const connect = useCallback(() => {
    const url = new URL("https://api.botbro.trade/v1/stream/indicators/tiered");
    url.searchParams.set("token", jwtToken);
    url.searchParams.set("symbols", "nifty,banknifty,sensex,finnifty");
    url.searchParams.set("modes", "current,positional");
    url.searchParams.set("include_optional", "true");

    const es = new EventSource(url.toString());
    eventSourceRef.current = es;

    es.addEventListener("snapshot", (event) => {
      const data = JSON.parse(event.data);
      onSnapshot(data);
      reconnectDelayRef.current = 1000; // Reset backoff on success
    });

    es.addEventListener("indicator_update", (event) => {
      const data: IndicatorUpdate = JSON.parse(event.data);
      onUpdate(data);
    });

    es.addEventListener("heartbeat", () => {
      // Connection alive - no action needed
    });

    es.addEventListener("market_closed", () => {
      // Show market closed banner
    });

    es.addEventListener("refresh_recommended", () => {
      // Re-fetch bootstrap data
    });

    es.onerror = () => {
      es.close();
      // Exponential backoff: 1s, 2s, 4s, 8s, max 30s
      reconnectTimeoutRef.current = setTimeout(() => {
        reconnectDelayRef.current = Math.min(reconnectDelayRef.current * 2, 30000);
        connect();
      }, reconnectDelayRef.current);
    };
  }, [jwtToken, onUpdate, onSnapshot]);

  useEffect(() => {
    connect();
    
    // Proactive reconnect every 55 minutes (before Cloud Run timeout)
    const proactiveReconnect = setInterval(() => {
      eventSourceRef.current?.close();
      connect();
    }, 55 * 60 * 1000);

    return () => {
      clearInterval(proactiveReconnect);
      clearTimeout(reconnectTimeoutRef.current);
      eventSourceRef.current?.close();
    };
  }, [connect]);
}
```


### SSE Event Types

**1. `snapshot` - Initial data on connection**

```json
{
  "event_type": "snapshot",
  "nifty": {
    "current": { /* SymbolPayload structure */ },
    "positional": { /* SymbolPayload structure */ }
  },
  "banknifty": { /* ... */ }
}
```

**2. `indicator_update` - Periodic updates (every 60s)**

```json
{
  "event_type": "indicator_update",
  "symbol": "nifty",
  "mode": "current",
  "indicators": {
    "skew": 0.18,
    "raw_skew": 0.15,
    "pcr": 0.95,
    "adr": 1.30,
    "signal": "NEUTRAL",
    "skew_confidence": 0.65,
    "rsi": 54.2,
    "ema_5": 24835.00,
    "ema_9": 24830.00,
    "ema_13": 24820.00,
    "ema_21": 24795.00,
    "ema_50": 24650.00,
    "bb_upper": 24920.00,
    "bb_middle": 24800.00,
    "bb_lower": 24680.00,
    "vwap": 24815.50,
    "pivot_point": 24780.00
  },
  "intuition_text": "NIFTY consolidating near resistance. Watch for breakout above 24900.",
  "timestamp": "2026-01-23T10:30:00+05:30"
}
```

**3. `option_chain_update` - Option chain changes**

```json
{
  "event_type": "option_chain_update",
  "symbol": "nifty",
  "mode": "current",
  "expiry": "2026-01-30",
  "underlying": 24855.00,
  "strikes": [
    { "strike": 24800, "call_oi": 255000, "put_oi": 205000, "call_coi": 5000, "put_coi": 3000, "strike_skew": 0.08 },
    { "strike": 24850, "call_oi": 325000, "put_oi": 285000, "call_coi": 8000, "put_coi": 6000, "strike_skew": 0.12 }
  ],
  "timestamp": "2026-01-23T10:30:00+05:30"
}
```

**4. `heartbeat` - Keep-alive (every 30s)**

```json
{
  "event_type": "heartbeat",
  "timestamp": "2026-01-23T10:30:30+05:30"
}
```

**5. `market_closed` - Market hours ended**

```json
{
  "event_type": "market_closed",
  "message": "Indian markets are closed. Trading hours: 09:15-15:30 IST"
}
```

**6. `refresh_recommended` - Re-fetch bootstrap**

```json
{
  "event_type": "refresh_recommended",
  "reason": "Data reset after market open"
}
```


### 4.2 Fast Stream (WebSocket) - LTP Updates

**Endpoint:** `wss://api.botbro.trade/v1/stream/fast`

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `token` | string | JWT token (required) |
| `symbols` | string | Comma-separated symbols |

**Next.js Implementation:**

```typescript
// hooks/useFastStream.ts
import { useEffect, useRef, useCallback } from 'react';

interface TickData {
  symbol: string;
  ltp: number;
  change: number;
  change_pct: number;
  ts: string;
}

interface OptionChainLTP {
  symbol: string;
  mode: string;
  strikes: number[];
  call_ltp: (number | null)[];
  put_ltp: (number | null)[];
}

export function useFastStream(
  jwtToken: string,
  onTick: (data: Record<string, TickData>) => void,
  onOptionLTP: (data: OptionChainLTP) => void,
  onJwtRefreshNeeded: () => Promise<string | null>
) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectDelayRef = useRef(1000);

  const connect = useCallback(() => {
    const url = new URL("wss://api.botbro.trade/v1/stream/fast");
    url.searchParams.set("token", jwtToken);
    url.searchParams.set("symbols", "nifty,banknifty,sensex,finnifty");

    const ws = new WebSocket(url.toString());
    wsRef.current = ws;

    ws.onopen = () => {
      console.log("WebSocket connected");
      reconnectDelayRef.current = 1000; // Reset backoff
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);

      switch (data.event) {
        case "tick":
          // data.data = { nifty: { ltp, change, change_pct, ts }, ... }
          onTick(data.data);
          break;

        case "option_chain_ltp":
          // Columnar format for option LTPs
          onOptionLTP({
            symbol: data.symbol,
            mode: data.mode,
            strikes: data.data.strikes,
            call_ltp: data.data.call_ltp,
            put_ltp: data.data.put_ltp
          });
          break;

        case "ping":
          // Must respond with pong within 60 seconds
          ws.send(JSON.stringify({ action: "pong" }));
          break;

        case "snapshot":
          // Initial data on connection
          onTick(data.data);
          break;
      }
    };

    ws.onclose = async (event) => {
      console.log("WebSocket closed", event.code, event.reason);

      if (event.code === 4001) {
        // JWT expired - refresh and reconnect
        const newToken = await onJwtRefreshNeeded();
        if (newToken) {
          connect(); // Will use new token
        }
        return;
      }

      if (event.code === 4005) {
        // Slow client warning - show user notification
        console.warn("Slow client detected - messages may be dropped");
      }

      // Exponential backoff reconnect
      setTimeout(() => {
        reconnectDelayRef.current = Math.min(reconnectDelayRef.current * 2, 30000);
        connect();
      }, reconnectDelayRef.current);
    };

    ws.onerror = (error) => {
      console.error("WebSocket error", error);
    };
  }, [jwtToken, onTick, onOptionLTP, onJwtRefreshNeeded]);

  useEffect(() => {
    connect();

    // Proactive reconnect every 55 minutes
    const proactiveReconnect = setInterval(() => {
      wsRef.current?.close();
      connect();
    }, 55 * 60 * 1000);

    return () => {
      clearInterval(proactiveReconnect);
      wsRef.current?.close();
    };
  }, [connect]);
}
```


### WebSocket Message Types

**1. `tick` - Index LTP updates (sub-second)**

```json
{
  "event": "tick",
  "data": {
    "nifty": { "ltp": 24855.50, "change": 55.50, "change_pct": 0.22, "ts": "2026-01-23T10:30:01+05:30" },
    "banknifty": { "ltp": 52450.00, "change": 150.00, "change_pct": 0.29, "ts": "2026-01-23T10:30:01+05:30" }
  },
  "ts": "2026-01-23T10:30:01+05:30"
}
```

**2. `option_chain_ltp` - Option LTP updates (columnar format)**

```json
{
  "event": "option_chain_ltp",
  "symbol": "nifty",
  "mode": "current",
  "data": {
    "strikes": [24800, 24850, 24900],
    "call_ltp": [125.50, 95.25, 72.00],
    "put_ltp": [85.25, 110.50, 145.75]
  }
}
```

**3. `ping` - Server keep-alive**

```json
{ "event": "ping" }
```

**Response required:**

```json
{ "action": "pong" }
```

**4. `snapshot` - Initial data on connection**

```json
{
  "event": "snapshot",
  "data": {
    "nifty": { "ltp": 24850.00, "change": 50.00, "change_pct": 0.20 },
    "banknifty": { "ltp": 52400.00, "change": 100.00, "change_pct": 0.19 }
  }
}
```

### WebSocket Close Codes

| Code | Meaning | Action |
|------|---------|--------|
| 4001 | JWT expired | Refresh token and reconnect |
| 4002 | Subscribe timeout | Reconnect |
| 4003 | Invalid subscribe message | Check message format |
| 4004 | Invalid symbols | Check symbol names |
| 4005 | Slow client | Show warning, messages may be dropped |


---

## 5. Admin API

Admin endpoints require:
1. JWT token with `role: "admin"`
2. OTP verification for sensitive operations (8-hour session)

### 5.1 OTP Flow for Admin Operations

**Step 1: Request OTP**

**Endpoint:** `POST /v1/admin/otp/request`

```typescript
const response = await fetch("https://api.botbro.trade/v1/admin/otp/request", {
  method: "POST",
  headers: {
    "Authorization": `Bearer ${jwtToken}`,
    "Content-Type": "application/json"
  },
  body: JSON.stringify({ action: "admin_session" })
});
```

**Response:**

```json
{
  "ok": true,
  "data": {
    "message": "OTP sent to your email",
    "expires_in_seconds": 300
  }
}
```

**Step 2: Verify OTP**

**Endpoint:** `POST /v1/admin/otp/verify`

```typescript
const response = await fetch("https://api.botbro.trade/v1/admin/otp/verify", {
  method: "POST",
  headers: {
    "Authorization": `Bearer ${jwtToken}`,
    "Content-Type": "application/json"
  },
  body: JSON.stringify({
    otp: "123456",
    action: "admin_session"
  })
});
```

**Response:**

```json
{
  "ok": true,
  "data": {
    "verified": true,
    "message": "OTP verified successfully",
    "session_valid_until": "2026-01-23T18:30:00+05:30",
    "session_hours": 8
  }
}
```

**Step 3: Check Session Status**

**Endpoint:** `GET /v1/admin/session/status`

```json
{
  "ok": true,
  "data": {
    "verified": true,
    "user_id": "usr_abc123",
    "message": "Admin session active"
  }
}
```


### 5.2 User Management

**Endpoint:** `GET /v1/admin/users`

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `page` | number | 1 | Page number (1-indexed) |
| `limit` | number | 100 | Users per page (max 100) |

```typescript
const response = await fetch(
  "https://api.botbro.trade/v1/admin/users?page=1&limit=50",
  { headers: { "Authorization": `Bearer ${jwtToken}` } }
);
```

**Response:**

```json
{
  "ok": true,
  "data": {
    "users": [
      {
        "id": "usr_abc123",
        "email": "trader@example.com",
        "name": "John Trader",
        "role": "customer",
        "status": "active",
        "created_at": "2026-01-15T10:00:00+05:30"
      },
      {
        "id": "usr_def456",
        "email": "admin@example.com",
        "name": "Admin User",
        "role": "admin",
        "status": "active",
        "created_at": "2026-01-01T09:00:00+05:30"
      }
    ],
    "total": 150,
    "page": 1,
    "limit": 50,
    "has_more": true
  }
}
```

### 5.3 Strike Range Configuration

**Endpoint:** `POST /v1/admin/strike-ranges`

Configure which strikes to include in option chain data.

```typescript
const response = await fetch("https://api.botbro.trade/v1/admin/strike-ranges", {
  method: "POST",
  headers: {
    "Authorization": `Bearer ${jwtToken}`,
    "Content-Type": "application/json"
  },
  body: JSON.stringify({
    symbol: "nifty",
    mode: "current",
    lower_strike: 24500,
    upper_strike: 25200
  })
});
```

**Response:**

```json
{
  "ok": true,
  "data": {
    "id": "sr_xyz789",
    "symbol": "nifty",
    "mode": "current",
    "lower_strike": 24500,
    "upper_strike": 25200,
    "effective_from": "2026-01-23T10:30:00+05:30",
    "effective_until": null,
    "created_by": "usr_admin123"
  }
}
```


---

## 6. Error Handling

### Standard Error Codes

| Code | HTTP Status | Description | Action |
|------|-------------|-------------|--------|
| `UNAUTHORIZED` | 401 | Invalid/missing JWT | Redirect to login |
| `SESSION_REVOKED` | 401 | Session invalidated (new login elsewhere) | Clear session, redirect to login |
| `TOKEN_EXPIRED` | 401 | JWT expired | Refresh token or re-login |
| `FORBIDDEN` | 403 | Insufficient permissions | Show access denied |
| `INVALID_SYMBOLS` | 400 | Unknown symbol requested | Check symbol names |
| `INVALID_MODES` | 400 | Unknown mode requested | Check mode names |
| `BOOTSTRAP_TIMEOUT` | 504 | Bootstrap took >15s | Retry with backoff |
| `STREAMING_UNAVAILABLE` | 503 | Streaming hub not running | Retry later |
| `PARTIAL_DATA` | 200 | Some data sources failed | Show available data with warning |

### Error Response Example

```json
{
  "ok": false,
  "data": null,
  "error": {
    "code": "UNAUTHORIZED",
    "message": "Invalid or expired token",
    "details": {
      "reason": "Token signature verification failed"
    }
  },
  "meta": {
    "request_id": "req_xyz789",
    "server_time": "2026-01-23T10:30:00Z",
    "cache_stale": false,
    "market_state": "UNKNOWN"
  }
}
```

### Next.js Error Handling Pattern

```typescript
// lib/api.ts
export class APIError extends Error {
  constructor(
    public code: string,
    public message: string,
    public status: number,
    public details?: Record<string, any>
  ) {
    super(message);
    this.name = 'APIError';
  }

  isAuthError(): boolean {
    return this.status === 401 || 
           ['UNAUTHORIZED', 'SESSION_REVOKED', 'TOKEN_EXPIRED'].includes(this.code);
  }
}

export async function fetchAPI<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const token = getStoredToken(); // Your token storage
  
  const response = await fetch(`https://api.botbro.trade${endpoint}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token && { 'Authorization': `Bearer ${token}` }),
      ...options.headers,
    },
  });

  const result = await response.json();

  if (!result.ok || response.status >= 400) {
    const error = new APIError(
      result.error?.code || 'UNKNOWN',
      result.error?.message || 'An error occurred',
      response.status,
      result.error?.details
    );

    if (error.isAuthError()) {
      clearStoredToken();
      window.location.href = '/login';
    }

    throw error;
  }

  return result.data;
}
```


### Staleness Handling

Check `meta.cache_stale` in every response:

```typescript
// Show warning banner when data is stale
if (response.meta.cache_stale) {
  showWarning("Data may be outdated. Last update was more than 5 minutes ago.");
}
```

### Retry Logic

Implement exponential backoff for transient failures:

```typescript
async function fetchWithRetry<T>(
  fn: () => Promise<T>,
  maxAttempts = 3
): Promise<T> {
  const delays = [0, 1000, 2000]; // immediate, 1s, 2s
  
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    try {
      return await fn();
    } catch (error) {
      if (error instanceof APIError) {
        // Don't retry auth errors
        if (error.isAuthError()) throw error;
        
        // Don't retry client errors (4xx except 429)
        if (error.status >= 400 && error.status < 500 && error.status !== 429) {
          throw error;
        }
      }
      
      if (attempt < maxAttempts - 1) {
        await new Promise(r => setTimeout(r, delays[attempt]));
      } else {
        throw error;
      }
    }
  }
  throw new Error('Retry logic failed');
}
```

---

## 7. TypeScript Interfaces

Complete TypeScript definitions for all API types:

```typescript
// types/api.ts

// ============================================================================
// Core Types
// ============================================================================

export const SYMBOLS = ["nifty", "banknifty", "sensex", "finnifty"] as const;
export type Symbol = typeof SYMBOLS[number];

export const MODES = ["current", "positional"] as const;
export type Mode = typeof MODES[number];

export const SIGNALS = ["STRONG_BUY", "BUY", "NEUTRAL", "SELL", "STRONG_SELL"] as const;
export type Signal = typeof SIGNALS[number];

export const MARKET_STATES = ["OPEN", "CLOSED", "UNKNOWN"] as const;
export type MarketState = typeof MARKET_STATES[number];

// ============================================================================
// Response Envelope
// ============================================================================

export interface ResponseMeta {
  request_id: string;
  server_time: string;
  cache_stale: boolean;
  market_state: MarketState;
}

export interface ErrorDetail {
  code: string;
  message: string;
  details?: Record<string, any>;
}

export interface APIResponse<T> {
  ok: boolean;
  data: T | null;
  error: ErrorDetail | null;
  meta: ResponseMeta;
}


// ============================================================================
// Authentication
// ============================================================================

export interface UserInfo {
  id: string;
  email: string;
  name: string;
  role: "admin" | "customer" | "test_customer";
}

export interface SubscriptionInfo {
  status: string;
  valid_until: string | null;
}

export interface AuthExchangeResponse {
  access: "ALLOWED" | "DENIED";
  token: string | null;
  user: UserInfo | null;
  user_exists: boolean | null;
  subscription: SubscriptionInfo | null;
  next: "DASHBOARD" | "SUBSCRIBE" | "SUBSCRIBE_OR_TRIAL" | "PENDING_APPROVAL";
}

// ============================================================================
// Dashboard Data
// ============================================================================

export interface IndicatorLevels {
  upper: number;
  lower: number;
}

export interface IndicatorSeries {
  ts: string[];
  skew: (number | null)[];
  pcr: (number | null)[];
}

export interface IndicatorChart {
  levels: IndicatorLevels;
  series: IndicatorSeries;
}

export interface TechnicalIndicators {
  ts: string[];
  rsi: (number | null)[];
  ema_9: (number | null)[];
  ema_21: (number | null)[];
  adr: (number | null)[];
}

export interface CandleData {
  ts: string[];
  open: number[];
  high: number[];
  low: number[];
  close: number[];
  volume: number[];
}

export interface OptionChainColumns {
  strike: number[];
  call_oi: number[];
  put_oi: number[];
  skew: number[];
  call_vol: number[];
  put_vol: number[];
}

export interface OptionChainData {
  expiry: string;
  underlying: number;
  ts: string;
  columns: OptionChainColumns;
}

export interface IntuitionEngine {
  ts_bucket: string;
  text: string;
}

export interface SymbolPayload {
  as_of: string;
  indicator_chart: IndicatorChart;
  option_chain: OptionChainData | null;
  intuition_engine: IntuitionEngine | null;
}

export interface ModePayload {
  current: SymbolPayload | null;
  positional: SymbolPayload | null;
  candles_5m: CandleData | null;
  technical_indicators: TechnicalIndicators | null;
}

export interface BootstrapData {
  nifty: ModePayload;
  banknifty: ModePayload;
  sensex: ModePayload;
  finnifty: ModePayload;
}


// ============================================================================
// Streaming Events
// ============================================================================

export interface IndicatorUpdateEvent {
  event_type: "indicator_update";
  symbol: Symbol;
  mode: Mode;
  indicators: {
    skew: number | null;
    raw_skew: number | null;
    pcr: number | null;
    adr: number | null;
    signal: Signal;
    skew_confidence: number;
    rsi: number | null;
    ema_5: number | null;
    ema_9: number | null;
    ema_13: number | null;
    ema_21: number | null;
    ema_50: number | null;
    bb_upper: number | null;
    bb_middle: number | null;
    bb_lower: number | null;
    vwap: number | null;
    pivot_point: number | null;
  };
  intuition_text: string | null;
  timestamp: string;
}

export interface OptionChainUpdateEvent {
  event_type: "option_chain_update";
  symbol: Symbol;
  mode: Mode;
  expiry: string;
  underlying: number;
  strikes: Array<{
    strike: number;
    call_oi: number;
    put_oi: number;
    call_coi: number | null;
    put_coi: number | null;
    strike_skew: number | null;
  }>;
  timestamp: string;
}

export interface TickEvent {
  event: "tick";
  data: Record<Symbol, {
    ltp: number;
    change: number;
    change_pct: number;
    ts: string;
  }>;
  ts: string;
}

export interface OptionChainLTPEvent {
  event: "option_chain_ltp";
  symbol: Symbol;
  mode: Mode;
  data: {
    strikes: number[];
    call_ltp: (number | null)[];
    put_ltp: (number | null)[];
  };
}

// ============================================================================
// Admin
// ============================================================================

export interface UserListItem {
  id: string;
  email: string;
  name: string;
  role: string;
  status: string;
  created_at: string;
}

export interface UserListResponse {
  users: UserListItem[];
  total: number;
  page: number;
  limit: number;
  has_more: boolean;
}

export interface StrikeRangeResponse {
  id: string;
  symbol: Symbol;
  mode: Mode;
  lower_strike: number;
  upper_strike: number;
  effective_from: string;
  effective_until: string | null;
  created_by: string;
}

export interface ADRConstituent {
  symbol: string;
  ltp: number;
  change_pct: number;
  status: "advancing" | "declining" | "unchanged";
}

export interface ADRConstituentsResponse {
  symbol: Symbol;
  constituents: ADRConstituent[];
  summary: {
    total: number;
    advancing: number;
    declining: number;
    unchanged: number;
  };
}
```


---

## 8. Complete Integration Example

### Next.js App Router Example

```typescript
// app/dashboard/page.tsx
'use client';

import { useEffect, useState, useCallback } from 'react';
import { useIndicatorStream } from '@/hooks/useIndicatorStream';
import { useFastStream } from '@/hooks/useFastStream';
import { fetchAPI } from '@/lib/api';
import type { BootstrapData, IndicatorUpdateEvent, TickEvent } from '@/types/api';

export default function DashboardPage() {
  const [data, setData] = useState<BootstrapData | null>(null);
  const [ltps, setLtps] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Get JWT from your auth context/store
  const jwtToken = useAuthStore(state => state.token);

  // Fetch bootstrap data on mount
  useEffect(() => {
    async function loadBootstrap() {
      try {
        setLoading(true);
        const bootstrap = await fetchAPI<BootstrapData>(
          '/v1/dashboard/bootstrap?include_candles=true&include_indicators=true'
        );
        setData(bootstrap);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load data');
      } finally {
        setLoading(false);
      }
    }
    
    if (jwtToken) {
      loadBootstrap();
    }
  }, [jwtToken]);

  // Handle indicator updates from SSE
  const handleIndicatorUpdate = useCallback((update: IndicatorUpdateEvent) => {
    setData(prev => {
      if (!prev) return prev;
      
      const symbol = update.symbol;
      const mode = update.mode;
      
      // Update the indicator series with new data point
      const currentPayload = prev[symbol]?.[mode];
      if (!currentPayload) return prev;

      return {
        ...prev,
        [symbol]: {
          ...prev[symbol],
          [mode]: {
            ...currentPayload,
            indicator_chart: {
              ...currentPayload.indicator_chart,
              series: {
                ts: [...currentPayload.indicator_chart.series.ts, update.timestamp],
                skew: [...currentPayload.indicator_chart.series.skew, update.indicators.skew],
                pcr: [...currentPayload.indicator_chart.series.pcr, update.indicators.pcr],
              }
            }
          }
        }
      };
    });
  }, []);

  // Handle snapshot from SSE (re-populate all data)
  const handleSnapshot = useCallback((snapshot: Record<string, any>) => {
    // Snapshot has same structure as bootstrap
    setData(snapshot as BootstrapData);
  }, []);

  // Handle LTP updates from WebSocket
  const handleTick = useCallback((ticks: Record<string, { ltp: number }>) => {
    setLtps(prev => {
      const updated = { ...prev };
      for (const [symbol, tick] of Object.entries(ticks)) {
        updated[symbol] = tick.ltp;
      }
      return updated;
    });
  }, []);

  // Handle option chain LTP updates
  const handleOptionLTP = useCallback((data: any) => {
    // Update option chain LTPs in state
    // Implementation depends on your state structure
  }, []);

  // JWT refresh callback for WebSocket
  const handleJwtRefresh = useCallback(async () => {
    try {
      const result = await fetchAPI<{ token: string }>('/v1/auth/refresh');
      // Update token in your auth store
      return result.token;
    } catch {
      return null;
    }
  }, []);

  // Connect to SSE stream
  useIndicatorStream(jwtToken, handleIndicatorUpdate, handleSnapshot);

  // Connect to WebSocket stream
  useFastStream(jwtToken, handleTick, handleOptionLTP, handleJwtRefresh);

  if (loading) return <div>Loading...</div>;
  if (error) return <div>Error: {error}</div>;
  if (!data) return <div>No data</div>;

  return (
    <div>
      {/* Render your dashboard with data and ltps */}
      <SymbolCard 
        symbol="nifty" 
        data={data.nifty} 
        ltp={ltps.nifty} 
      />
      {/* ... other symbols */}
    </div>
  );
}
```

---

## 9. Quick Reference

### Endpoints Summary

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/v1/auth/google/exchange` | POST | No | Exchange Google code for JWT |
| `/v1/auth/me` | GET | JWT | Get current user info |
| `/v1/auth/refresh` | POST | JWT | Refresh JWT token |
| `/v1/dashboard/bootstrap` | GET | JWT | Get all initial data |
| `/v1/dashboard/{symbol}/{mode}/snapshot` | GET | JWT | Get single symbol snapshot |
| `/v1/dashboard/adr/constituents` | GET | JWT | Get ADR constituent details |
| `/v1/stream/indicators/tiered` | GET (SSE) | JWT | Indicator updates stream |
| `/v1/stream/fast` | WS | JWT | LTP updates stream |
| `/v1/admin/otp/request` | POST | JWT (admin) | Request admin OTP |
| `/v1/admin/otp/verify` | POST | JWT (admin) | Verify admin OTP |
| `/v1/admin/users` | GET | JWT (admin) | List users (paginated) |
| `/v1/admin/strike-ranges` | POST | JWT (admin) | Configure strike ranges |

### Market Hours

- **Trading Hours:** 09:15 - 15:30 IST (Monday-Friday)
- **Pre-market:** Data Handler starts at 09:10 IST
- **Post-market:** Data Handler stops at 15:35 IST
- **Timezone:** All timestamps are in Asia/Kolkata (IST)

### Data Update Frequencies

| Data Type | Update Frequency | Source |
|-----------|------------------|--------|
| Index LTP | Sub-second | WebSocket `/v1/stream/fast` |
| Option LTP | Sub-second | WebSocket `/v1/stream/fast` |
| Indicators (Skew, PCR, etc.) | 60 seconds | SSE `/v1/stream/indicators/tiered` |
| Option Chain OI | 60 seconds | SSE |
| AI Intuition | 5 minutes | SSE |

---

**Document Version:** 1.0  
**Source of Truth:** `local_iceberg_test_dashboard/src/` code analysis  
**Last Verified:** 2026-01-23
