#!/usr/bin/env python3
"""
Timing Analysis Test Script

Measures the timing of data flow through the Iceberg system:
1. Candle write timing (DB trigger)
2. Indicator write timing (scheduler)
3. SSE indicator event timing
4. SSE candle_update event timing
5. Fast stream tick latency

Usage:
    python test_timing_analysis.py [--duration MINUTES] [--token JWT_TOKEN]
"""

import argparse
import json
import os
import sys
import time
import threading
import statistics
from datetime import datetime, timezone
from collections import defaultdict
from typing import Optional, Dict, Any, List
from pathlib import Path

import requests
import websocket
import sseclient
import psycopg2
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
DEFAULT_DURATION_MINUTES = 10
API_URL = os.getenv("ICEBERG_API_URL", "https://api.botbro.trade")
JWT_TOKEN = os.getenv("ICEBERG_JWT_TOKEN", "")
SYMBOLS = ["nifty", "banknifty", "sensex", "finnifty"]
MODES = ["current", "positional"]

# Database connection (read-only)
DB_CONFIG = {
    "host": "34.180.57.7",
    "port": 5432,
    "database": "iceberg",
    "user": "iceberg",
    "password": "xw8vntEkMkLnOrwA6qsULpGmB1wUmgpT",
}


class TimingAnalyzer:
    """Analyzes timing of data flow through the Iceberg system."""
    
    def __init__(self, jwt_token: str, duration_minutes: int = DEFAULT_DURATION_MINUTES):
        self.jwt_token = jwt_token
        self.duration_seconds = duration_minutes * 60
        self.running = False
        self.start_time: Optional[float] = None
        
        # Results directory
        self.results_dir = Path(__file__).parent / "results"
        self.results_dir.mkdir(exist_ok=True)
        self.run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Timing data
        self.candle_timings: List[Dict] = []  # bucket_ts, created_at, delay_seconds
        self.indicator_timings: List[Dict] = []  # bucket_ts, created_at, delay_seconds
        self.sse_indicator_events: List[Dict] = []  # received_at, bucket_ts (from data)
        self.sse_candle_events: List[Dict] = []  # received_at, candle_ts
        self.ws_tick_events: List[Dict] = []  # received_at, tick_ts (from data)
        
        # Thread references
        self._ws_thread: Optional[threading.Thread] = None
        self._sse_thread: Optional[threading.Thread] = None
        self._db_thread: Optional[threading.Thread] = None
        self._ws: Optional[websocket.WebSocketApp] = None
    
    def _log(self, level: str, component: str, message: str, **kwargs):
        """Log with timestamp and structured data."""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        extra = " ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
        print(f"[{ts}] [{level}] [{component}] {message} {extra}")
    
    # =========================================================================
    # Database Polling (Candle and Indicator Timing)
    # =========================================================================
    
    def _poll_database(self):
        """Poll database for candle and indicator timing data."""
        self._log("INFO", "DB", "Starting database polling...")
        
        last_candle_check = None
        last_indicator_check = None
        
        while self.running:
            try:
                conn = psycopg2.connect(**DB_CONFIG)
                cursor = conn.cursor()
                
                # Query candle timing (last 5 minutes)
                cursor.execute("""
                    SELECT 
                        symbol,
                        bucket_ts AT TIME ZONE 'Asia/Kolkata' as bucket_ts_ist,
                        created_at AT TIME ZONE 'Asia/Kolkata' as created_at_ist,
                        EXTRACT(EPOCH FROM (created_at - bucket_ts)) as seconds_after_bucket
                    FROM processing.candles_5m
                    WHERE created_at >= NOW() - INTERVAL '5 minutes'
                    ORDER BY created_at DESC
                    LIMIT 20
                """)
                
                for row in cursor.fetchall():
                    symbol, bucket_ts, created_at, delay = row
                    key = f"{symbol}:{bucket_ts}"
                    if key != last_candle_check:
                        self.candle_timings.append({
                            "symbol": symbol,
                            "bucket_ts": str(bucket_ts),
                            "created_at": str(created_at),
                            "delay_seconds": float(delay) if delay else None,
                            "recorded_at": datetime.now().isoformat(),
                        })
                        self._log("INFO", "DB", f"Candle {symbol} bucket={bucket_ts} delay={delay:.1f}s")
                        last_candle_check = key
                
                # Query indicator timing (last 5 minutes)
                cursor.execute("""
                    SELECT 
                        'nifty' as symbol,
                        mode,
                        bucket_ts AT TIME ZONE 'Asia/Kolkata' as bucket_ts_ist,
                        created_at AT TIME ZONE 'Asia/Kolkata' as created_at_ist,
                        EXTRACT(EPOCH FROM (created_at - bucket_ts)) as seconds_after_bucket
                    FROM processing.nifty_indicators_5m
                    WHERE created_at >= NOW() - INTERVAL '5 minutes'
                    ORDER BY created_at DESC
                    LIMIT 10
                """)
                
                for row in cursor.fetchall():
                    symbol, mode, bucket_ts, created_at, delay = row
                    key = f"{symbol}:{mode}:{bucket_ts}"
                    if key != last_indicator_check:
                        self.indicator_timings.append({
                            "symbol": symbol,
                            "mode": mode,
                            "bucket_ts": str(bucket_ts),
                            "created_at": str(created_at),
                            "delay_seconds": float(delay) if delay else None,
                            "recorded_at": datetime.now().isoformat(),
                        })
                        self._log("INFO", "DB", f"Indicator {symbol}/{mode} bucket={bucket_ts} delay={delay:.1f}s")
                        last_indicator_check = key
                
                cursor.close()
                conn.close()
                
            except Exception as e:
                self._log("ERROR", "DB", f"Database error: {e}")
            
            # Poll every 10 seconds
            time.sleep(10)
    
    # =========================================================================
    # WebSocket (Fast Stream) - Tick Latency
    # =========================================================================
    
    def _run_websocket(self):
        """Run WebSocket connection to measure tick latency."""
        ws_url = API_URL.replace("https://", "wss://").replace("http://", "ws://")
        symbols_param = ",".join(SYMBOLS)
        url = f"{ws_url}/v1/stream/fast?token={self.jwt_token}&symbols={symbols_param}"
        
        def on_open(ws):
            self._log("INFO", "WS", "Connected")
        
        def on_message(ws, message):
            received_at = time.time()
            received_at_iso = datetime.now().isoformat()
            
            try:
                data = json.loads(message)
                event_type = data.get("event", "unknown")
                
                if event_type == "tick":
                    tick_data = data.get("data", {})
                    tick_ts = data.get("ts", "")
                    
                    for symbol, tick_info in tick_data.items():
                        self.ws_tick_events.append({
                            "symbol": symbol,
                            "received_at": received_at,
                            "received_at_iso": received_at_iso,
                            "tick_ts": tick_ts,
                            "ltp": tick_info.get("ltp"),
                        })
                    
                    # Log sample (every 100th tick)
                    if len(self.ws_tick_events) % 100 == 0:
                        self._log("INFO", "WS", f"Tick #{len(self.ws_tick_events)}", symbols=list(tick_data.keys()))
                
                elif event_type == "ping":
                    ws.send(json.dumps({"action": "pong"}))
                    
            except Exception as e:
                self._log("ERROR", "WS", f"Error: {e}")
        
        def on_error(ws, error):
            self._log("ERROR", "WS", f"Error: {error}")
        
        def on_close(ws, close_code, close_msg):
            self._log("INFO", "WS", f"Closed code={close_code}")
        
        self._log("INFO", "WS", "Connecting...")
        
        while self.running:
            try:
                self._ws = websocket.WebSocketApp(
                    url,
                    on_open=on_open,
                    on_message=on_message,
                    on_error=on_error,
                    on_close=on_close,
                )
                self._ws.run_forever(ping_interval=0)
                
                if self.running:
                    self._log("WARN", "WS", "Reconnecting in 2s...")
                    time.sleep(2)
                    
            except Exception as e:
                self._log("ERROR", "WS", f"Connection error: {e}")
                if self.running:
                    time.sleep(2)
    
    # =========================================================================
    # SSE (Slow Stream) - Indicator and Candle Event Timing
    # =========================================================================
    
    def _run_sse(self):
        """Run SSE connection to measure indicator and candle event timing."""
        symbols_param = ",".join(SYMBOLS)
        modes_param = ",".join(MODES)
        url = f"{API_URL}/v1/stream/indicators/tiered?token={self.jwt_token}&symbols={symbols_param}&modes={modes_param}&include_optional=true&include_candles=true"
        
        self._log("INFO", "SSE", "Connecting...")
        
        while self.running:
            try:
                response = requests.get(url, stream=True, timeout=300)
                
                if response.status_code != 200:
                    self._log("ERROR", "SSE", f"HTTP {response.status_code}")
                    time.sleep(5)
                    continue
                
                self._log("INFO", "SSE", "Connected")
                client = sseclient.SSEClient(response)
                
                for event in client.events():
                    if not self.running:
                        break
                    
                    received_at = time.time()
                    received_at_iso = datetime.now().isoformat()
                    event_type = event.event or "message"
                    
                    try:
                        data = json.loads(event.data) if event.data else {}
                    except json.JSONDecodeError:
                        continue
                    
                    if event_type == "indicator_update":
                        symbol = data.get("symbol", "")
                        mode = data.get("mode", "")
                        ts = data.get("timestamp", "")
                        
                        self.sse_indicator_events.append({
                            "symbol": symbol,
                            "mode": mode,
                            "received_at": received_at,
                            "received_at_iso": received_at_iso,
                            "event_ts": ts,
                            "skew": data.get("skew"),
                            "pcr": data.get("pcr"),
                        })
                        self._log("INFO", "SSE", f"indicator_update {symbol}/{mode}")
                    
                    elif event_type == "candle_update":
                        symbol = data.get("symbol", "")
                        candle = data.get("candle", {})
                        candle_ts = candle.get("ts", "")
                        
                        self.sse_candle_events.append({
                            "symbol": symbol,
                            "received_at": received_at,
                            "received_at_iso": received_at_iso,
                            "candle_ts": candle_ts,
                            "close": candle.get("close"),
                        })
                        self._log("INFO", "SSE", f"candle_update {symbol} ts={candle_ts}")
                    
                    elif event_type == "heartbeat":
                        pass  # Ignore heartbeats
                        
            except Exception as e:
                self._log("ERROR", "SSE", f"Error: {e}")
            
            if self.running:
                self._log("WARN", "SSE", "Reconnecting in 5s...")
                time.sleep(5)
    
    # =========================================================================
    # Main Run
    # =========================================================================
    
    def run(self):
        """Run the timing analysis test."""
        self._log("INFO", "MAIN", "=" * 70)
        self._log("INFO", "MAIN", "TIMING ANALYSIS TEST")
        self._log("INFO", "MAIN", "=" * 70)
        self._log("INFO", "MAIN", f"API URL: {API_URL}")
        self._log("INFO", "MAIN", f"Duration: {self.duration_seconds // 60} minutes")
        self._log("INFO", "MAIN", "=" * 70)
        
        self.start_time = time.time()
        self.running = True
        
        # Start threads
        self._db_thread = threading.Thread(target=self._poll_database, daemon=True)
        self._ws_thread = threading.Thread(target=self._run_websocket, daemon=True)
        self._sse_thread = threading.Thread(target=self._run_sse, daemon=True)
        
        self._db_thread.start()
        self._ws_thread.start()
        self._sse_thread.start()
        
        self._log("INFO", "MAIN", "All threads started, running for duration...")
        
        # Wait for duration
        try:
            end_time = time.time() + self.duration_seconds
            while time.time() < end_time:
                remaining = int(end_time - time.time())
                if remaining % 60 == 0 and remaining > 0:
                    self._log("INFO", "MAIN", f"Time remaining: {remaining // 60} minutes")
                time.sleep(1)
        except KeyboardInterrupt:
            self._log("INFO", "MAIN", "Interrupted by user")
        
        # Stop
        self._log("INFO", "MAIN", "Stopping...")
        self.running = False
        
        if self._ws:
            try:
                self._ws.close()
            except:
                pass
        
        # Wait for threads
        for thread in [self._db_thread, self._ws_thread, self._sse_thread]:
            if thread:
                thread.join(timeout=5)
        
        # Save and print results
        self._save_results()
        self._print_summary()
    
    def _save_results(self):
        """Save all timing data to files."""
        run_dir = self.results_dir / f"timing_{self.run_timestamp}"
        run_dir.mkdir(exist_ok=True)
        
        # Save candle timings
        with open(run_dir / "candle_timings.json", "w") as f:
            json.dump(self.candle_timings, f, indent=2)
        
        # Save indicator timings
        with open(run_dir / "indicator_timings.json", "w") as f:
            json.dump(self.indicator_timings, f, indent=2)
        
        # Save SSE indicator events
        with open(run_dir / "sse_indicator_events.json", "w") as f:
            json.dump(self.sse_indicator_events, f, indent=2)
        
        # Save SSE candle events
        with open(run_dir / "sse_candle_events.json", "w") as f:
            json.dump(self.sse_candle_events, f, indent=2)
        
        # Save WS tick events (sample - first 1000)
        with open(run_dir / "ws_tick_events_sample.json", "w") as f:
            json.dump(self.ws_tick_events[:1000], f, indent=2)
        
        self._log("INFO", "SAVE", f"Results saved to {run_dir}")
    
    def _print_summary(self):
        """Print timing analysis summary."""
        print("\n" + "=" * 70)
        print("TIMING ANALYSIS SUMMARY")
        print("=" * 70)
        
        # Candle timing
        print("\n## Candle Write Timing (DB Trigger)")
        if self.candle_timings:
            delays = [t["delay_seconds"] for t in self.candle_timings if t["delay_seconds"]]
            if delays:
                print(f"  Count: {len(delays)}")
                print(f"  Min: {min(delays):.1f}s")
                print(f"  Max: {max(delays):.1f}s")
                print(f"  Mean: {statistics.mean(delays):.1f}s")
                print(f"  Median: {statistics.median(delays):.1f}s")
        else:
            print("  No data collected")
        
        # Indicator timing
        print("\n## Indicator Write Timing (Scheduler)")
        if self.indicator_timings:
            delays = [t["delay_seconds"] for t in self.indicator_timings if t["delay_seconds"]]
            if delays:
                print(f"  Count: {len(delays)}")
                print(f"  Min: {min(delays):.1f}s")
                print(f"  Max: {max(delays):.1f}s")
                print(f"  Mean: {statistics.mean(delays):.1f}s")
                print(f"  Median: {statistics.median(delays):.1f}s")
        else:
            print("  No data collected")
        
        # SSE indicator events
        print("\n## SSE Indicator Events")
        print(f"  Total events: {len(self.sse_indicator_events)}")
        if self.sse_indicator_events:
            symbols = set(e["symbol"] for e in self.sse_indicator_events)
            print(f"  Symbols: {sorted(symbols)}")
        
        # SSE candle events
        print("\n## SSE Candle Update Events")
        print(f"  Total events: {len(self.sse_candle_events)}")
        if self.sse_candle_events:
            symbols = set(e["symbol"] for e in self.sse_candle_events)
            print(f"  Symbols: {sorted(symbols)}")
        
        # WS tick events
        print("\n## WebSocket Tick Events")
        print(f"  Total events: {len(self.ws_tick_events)}")
        if self.ws_tick_events:
            symbols = set(e["symbol"] for e in self.ws_tick_events)
            print(f"  Symbols: {sorted(symbols)}")
        
        print("\n" + "=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Timing Analysis Test")
    parser.add_argument("--duration", type=int, default=DEFAULT_DURATION_MINUTES,
                        help=f"Test duration in minutes (default: {DEFAULT_DURATION_MINUTES})")
    parser.add_argument("--token", type=str, default=JWT_TOKEN,
                        help="JWT token for authentication")
    
    args = parser.parse_args()
    
    if not args.token:
        print("ERROR: JWT token required. Set ICEBERG_JWT_TOKEN env var or use --token")
        sys.exit(1)
    
    analyzer = TimingAnalyzer(
        jwt_token=args.token,
        duration_minutes=args.duration,
    )
    
    analyzer.run()


if __name__ == "__main__":
    main()
