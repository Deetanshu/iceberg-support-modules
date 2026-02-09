#!/usr/bin/env python3
"""
Full Flow Validation Test Script

Simulates the complete dashboard flow:
1. Bootstrap API call
2. SSE (Slow Stream) connection for indicator updates
3. WebSocket (Fast Stream) connection for LTP updates

Collects statistics, timing data, and saves all raw events to files.

Usage:
    python test_full_flow.py [--duration MINUTES] [--token JWT_TOKEN]
"""

import argparse
import json
import os
import sys
import time
import threading
import statistics
from datetime import datetime
from collections import defaultdict
from typing import Optional, Dict, Any, List
from pathlib import Path

import requests
import websocket
import sseclient
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
DEFAULT_DURATION_MINUTES = 10
API_URL = os.getenv("ICEBERG_API_URL", "https://api.botbro.trade")
JWT_TOKEN = os.getenv("ICEBERG_JWT_TOKEN", "")
SYMBOLS = ["nifty", "banknifty", "sensex", "finnifty"]
MODES = ["current", "positional"]


class FullFlowValidator:
    """Validates the complete dashboard flow: Bootstrap + SSE + WebSocket."""
    
    def __init__(self, jwt_token: str, duration_minutes: int = DEFAULT_DURATION_MINUTES, tick_interval: float = 0.0):
        self.jwt_token = jwt_token
        self.duration_seconds = duration_minutes * 60
        self.tick_interval = tick_interval  # FIX-050: WebSocket tick throttling (0-10 seconds)
        self.running = False
        self.start_time: Optional[float] = None
        
        # Results directory
        self.results_dir = Path(__file__).parent / "results"
        self.results_dir.mkdir(exist_ok=True)
        self.run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Raw data storage
        self.bootstrap_data: Optional[Dict] = None
        self.ws_events: List[Dict] = []
        self.sse_events: List[Dict] = []
        
        # Statistics
        self.stats = {
            "bootstrap": {
                "success": False,
                "response_time_ms": None,
                "symbols_received": [],
                "error": None,
            },
            "websocket": {
                "connected": False,
                "connection_time_ms": None,
                "total_messages": 0,
                "events_by_type": defaultdict(int),
                "symbols_seen": set(),
                "tick_intervals_ms": [],
                "tick_intervals_by_symbol": defaultdict(list),  # Per-symbol tick intervals
                "option_chain_ltp_intervals_ms": [],
                "pings_received": 0,
                "pongs_sent": 0,
                "errors": [],
                "disconnects": 0,
                "reconnects": 0,
                "reconnect_times_ms": [],
                "data_gaps_over_5s": 0,
                "close_codes": defaultdict(int),  # FIX-050: Track close codes
                "unexpected_closes": 0,  # FIX-050: Closes other than 1000, 4001, 4003
            },
            "sse": {
                "connected": False,
                "connection_time_ms": None,
                "total_messages": 0,
                "events_by_type": defaultdict(int),
                "symbols_seen": set(),
                "indicator_intervals_ms": [],
                "heartbeat_intervals_ms": [],
                "candle_update_intervals_ms": [],  # FIX-047: candle_update tracking
                "candle_updates_by_symbol": defaultdict(int),  # FIX-047: count per symbol
                "errors": [],
                "disconnects": 0,
                "reconnects": 0,
                "reconnect_times_ms": [],
                "indicator_gaps_over_90s": 0,
            },
        }
        
        # Timing tracking
        self._last_ws_tick_time: Optional[float] = None
        self._last_ws_tick_time_by_symbol: Dict[str, float] = {}  # Per-symbol tick timing
        self._last_ws_option_chain_time: Optional[float] = None
        self._last_sse_indicator_time: Optional[float] = None
        self._last_sse_heartbeat_time: Optional[float] = None
        self._last_sse_candle_time: Optional[float] = None  # FIX-047: candle_update tracking
        
        # Thread references
        self._ws_thread: Optional[threading.Thread] = None
        self._sse_thread: Optional[threading.Thread] = None
        self._ws: Optional[websocket.WebSocketApp] = None
    
    def _log(self, level: str, component: str, message: str, **kwargs):
        """Log with timestamp and structured data."""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        extra = " ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
        print(f"[{ts}] [{level}] [{component}] {message} {extra}")
    
    # =========================================================================
    # Bootstrap
    # =========================================================================
    
    def _run_bootstrap(self) -> bool:
        """Execute bootstrap API call."""
        self._log("INFO", "BOOTSTRAP", "Starting bootstrap request...")
        
        url = f"{API_URL}/v1/dashboard/bootstrap"
        params = {
            "symbols": ",".join(SYMBOLS),
            "include_candles": "true",
            "include_option_chain": "true",
            "include_indicators": "true",
        }
        headers = {
            "Authorization": f"Bearer {self.jwt_token}",
            "Content-Type": "application/json",
        }
        
        start = time.time()
        try:
            response = requests.get(url, params=params, headers=headers, timeout=30)
            elapsed_ms = (time.time() - start) * 1000
            
            self.stats["bootstrap"]["response_time_ms"] = elapsed_ms
            
            if response.status_code == 200:
                data = response.json()
                if data.get("ok"):
                    self.bootstrap_data = data
                    self.stats["bootstrap"]["success"] = True
                    self.stats["bootstrap"]["symbols_received"] = list(data.get("data", {}).keys())
                    self._log("INFO", "BOOTSTRAP", "SUCCESS", 
                              response_time_ms=f"{elapsed_ms:.0f}",
                              symbols=self.stats["bootstrap"]["symbols_received"])
                    return True
                else:
                    self.stats["bootstrap"]["error"] = data.get("error", {}).get("message", "Unknown error")
                    self._log("ERROR", "BOOTSTRAP", "API returned ok=false", error=self.stats["bootstrap"]["error"])
            else:
                self.stats["bootstrap"]["error"] = f"HTTP {response.status_code}: {response.text[:200]}"
                self._log("ERROR", "BOOTSTRAP", "HTTP error", status=response.status_code)
                
        except Exception as e:
            self.stats["bootstrap"]["error"] = str(e)
            self._log("ERROR", "BOOTSTRAP", "Request failed", error=str(e))
        
        return False
    
    # =========================================================================
    # WebSocket (Fast Stream)
    # =========================================================================
    
    def _build_ws_url(self) -> str:
        """Build WebSocket URL with optional tick_interval for throttling."""
        ws_url = API_URL.replace("https://", "wss://").replace("http://", "ws://")
        symbols_param = ",".join(SYMBOLS)
        url = f"{ws_url}/v1/stream/fast?token={self.jwt_token}&symbols={symbols_param}"
        # FIX-050: Add tick_interval if specified (0 = no throttle, default)
        if self.tick_interval > 0:
            url += f"&tick_interval={self.tick_interval}"
        return url
    
    def _run_websocket(self):
        """Run WebSocket connection in background thread."""
        ws_start_time = time.time()
        
        def on_open(ws):
            elapsed_ms = (time.time() - ws_start_time) * 1000
            if self.stats["websocket"]["connected"]:
                # This is a reconnection
                self.stats["websocket"]["reconnects"] += 1
                self.stats["websocket"]["reconnect_times_ms"].append(elapsed_ms)
                self._log("INFO", "WS", "RECONNECTED", connection_time_ms=f"{elapsed_ms:.0f}")
            else:
                self.stats["websocket"]["connected"] = True
                self.stats["websocket"]["connection_time_ms"] = elapsed_ms
                self._log("INFO", "WS", "CONNECTED", connection_time_ms=f"{elapsed_ms:.0f}")
            # Reset per-symbol timing on connect/reconnect to avoid muddying interval data
            self._last_ws_tick_time = None
            self._last_ws_tick_time_by_symbol.clear()
            self._last_ws_option_chain_time = None
        
        def on_message(ws, message):
            now = time.time()
            try:
                data = json.loads(message)
                event_type = data.get("event", "unknown")
                
                # Store raw event
                self.ws_events.append({
                    "received_at": now,
                    "received_at_iso": datetime.now().isoformat(),
                    "data": data,
                })
                
                self.stats["websocket"]["total_messages"] += 1
                self.stats["websocket"]["events_by_type"][event_type] += 1
                
                # Handle specific events
                if event_type == "ping":
                    self.stats["websocket"]["pings_received"] += 1
                    ws.send(json.dumps({"action": "pong"}))
                    self.stats["websocket"]["pongs_sent"] += 1
                    
                elif event_type == "snapshot":
                    symbols = list(data.get("data", {}).keys())
                    self.stats["websocket"]["symbols_seen"].update(symbols)
                    self._log("INFO", "WS", "SNAPSHOT", symbols=symbols)
                    
                elif event_type == "tick":
                    tick_data = data.get("data", {})
                    for symbol in tick_data.keys():
                        self.stats["websocket"]["symbols_seen"].add(symbol)
                        # Track per-symbol interval
                        if symbol in self._last_ws_tick_time_by_symbol:
                            interval_ms = (now - self._last_ws_tick_time_by_symbol[symbol]) * 1000
                            self.stats["websocket"]["tick_intervals_by_symbol"][symbol].append(interval_ms)
                        self._last_ws_tick_time_by_symbol[symbol] = now
                    
                    # Track overall interval
                    if self._last_ws_tick_time:
                        interval_ms = (now - self._last_ws_tick_time) * 1000
                        self.stats["websocket"]["tick_intervals_ms"].append(interval_ms)
                        # Track data gaps (>5 seconds without tick)
                        if interval_ms > 5000:
                            self.stats["websocket"]["data_gaps_over_5s"] += 1
                            self._log("WARN", "WS", f"Data gap detected: {interval_ms:.0f}ms since last tick")
                    self._last_ws_tick_time = now
                    
                elif event_type == "option_chain_ltp":
                    symbol = data.get("symbol", "")
                    mode = data.get("mode", "")
                    strikes = len(data.get("data", {}).get("strikes", []))
                    self.stats["websocket"]["symbols_seen"].add(symbol)
                    self._log("INFO", "WS", f"OPTION_CHAIN_LTP {symbol}/{mode}", strikes=strikes)
                    
                    # Track interval
                    if self._last_ws_option_chain_time:
                        interval_ms = (now - self._last_ws_option_chain_time) * 1000
                        self.stats["websocket"]["option_chain_ltp_intervals_ms"].append(interval_ms)
                    self._last_ws_option_chain_time = now
                    
            except json.JSONDecodeError as e:
                error_str = f"JSON decode: {e}"
                self.stats["websocket"]["errors"].append(error_str)
                self._log("ERROR", "WS", f"JSON decode error: {e}")
            except Exception as e:
                error_str = str(e)
                self.stats["websocket"]["errors"].append(error_str)
                self._log("ERROR", "WS", f"Message handling error: {e}")
        
        def on_error(ws, error):
            error_str = str(error)
            self.stats["websocket"]["errors"].append(error_str)
            self._log("ERROR", "WS", f"WebSocket error: {error_str}")
        
        def on_close(ws, close_code, close_msg):
            self.stats["websocket"]["disconnects"] += 1
            # FIX-050: Track close codes
            code = close_code if close_code else 0
            self.stats["websocket"]["close_codes"][code] += 1
            # Expected close codes to ignore: 1000 (normal), 4001 (auth), 4003 (forbidden)
            expected_codes = {1000, 4001, 4003}
            if code not in expected_codes and code != 0:
                self.stats["websocket"]["unexpected_closes"] += 1
                self._log("WARN", "WS", f"Unexpected close code: {code}, msg: {close_msg}")
            else:
                self._log("INFO", "WS", f"CLOSED code={close_code} msg={close_msg}")
        
        url = self._build_ws_url()
        self._log("INFO", "WS", "Connecting...", url_prefix=url[:60])
        
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
                    ws_start_time = time.time()
                    
            except Exception as e:
                error_str = str(e)
                self.stats["websocket"]["errors"].append(error_str)
                self._log("ERROR", "WS", f"Connection error: {e}")
                if self.running:
                    time.sleep(2)
    
    # =========================================================================
    # SSE (Slow Stream)
    # =========================================================================
    
    def _build_sse_url(self) -> str:
        """Build SSE URL with include_candles=true for candle_update events."""
        symbols_param = ",".join(SYMBOLS)
        modes_param = ",".join(MODES)
        # FIX-047: Add include_candles=true to receive candle_update events
        return f"{API_URL}/v1/stream/indicators/tiered?token={self.jwt_token}&symbols={symbols_param}&modes={modes_param}&include_optional=true&include_candles=true"
    
    def _run_sse(self):
        """Run SSE connection in background thread."""
        url = self._build_sse_url()
        self._log("INFO", "SSE", "Connecting...", url_prefix=url[:60])
        
        while self.running:
            sse_start_time = time.time()
            try:
                response = requests.get(url, stream=True, timeout=300)
                
                if response.status_code != 200:
                    self.stats["sse"]["errors"].append(f"HTTP {response.status_code}")
                    self._log("ERROR", "SSE", "HTTP error", status=response.status_code)
                    time.sleep(5)
                    continue
                
                elapsed_ms = (time.time() - sse_start_time) * 1000
                if self.stats["sse"]["connected"]:
                    # This is a reconnection
                    self.stats["sse"]["reconnects"] += 1
                    self.stats["sse"]["reconnect_times_ms"].append(elapsed_ms)
                    self._log("INFO", "SSE", "RECONNECTED", connection_time_ms=f"{elapsed_ms:.0f}")
                else:
                    self.stats["sse"]["connected"] = True
                    self.stats["sse"]["connection_time_ms"] = elapsed_ms
                    self._log("INFO", "SSE", "CONNECTED", connection_time_ms=f"{elapsed_ms:.0f}")
                
                client = sseclient.SSEClient(response)
                
                for event in client.events():
                    if not self.running:
                        break
                    
                    now = time.time()
                    event_type = event.event or "message"
                    
                    try:
                        data = json.loads(event.data) if event.data else {}
                    except json.JSONDecodeError:
                        data = {"raw": event.data}
                    
                    # Store raw event
                    self.sse_events.append({
                        "received_at": now,
                        "received_at_iso": datetime.now().isoformat(),
                        "event_type": event_type,
                        "event_id": event.id,
                        "data": data,
                    })
                    
                    self.stats["sse"]["total_messages"] += 1
                    self.stats["sse"]["events_by_type"][event_type] += 1
                    
                    # Handle specific events
                    if event_type == "snapshot":
                        symbols = [k for k in data.keys() if k not in ["event_type", "timestamp", "event_id"]]
                        self.stats["sse"]["symbols_seen"].update(symbols)
                        self._log("INFO", "SSE", "SNAPSHOT", symbols=symbols[:4])
                        
                    elif event_type == "indicator_update":
                        symbol = data.get("symbol", "")
                        mode = data.get("mode", "")
                        self.stats["sse"]["symbols_seen"].add(symbol)
                        self._log("INFO", "SSE", f"INDICATOR_UPDATE {symbol}/{mode}")
                        
                        # Track interval
                        if self._last_sse_indicator_time:
                            interval_ms = (now - self._last_sse_indicator_time) * 1000
                            self.stats["sse"]["indicator_intervals_ms"].append(interval_ms)
                            # Track indicator gaps (>90 seconds without update - expected is 60s)
                            if interval_ms > 90000:
                                self.stats["sse"]["indicator_gaps_over_90s"] += 1
                                self._log("WARN", "SSE", f"Indicator gap detected: {interval_ms:.0f}ms since last update")
                        self._last_sse_indicator_time = now
                        
                    elif event_type == "heartbeat":
                        # Track interval
                        if self._last_sse_heartbeat_time:
                            interval_ms = (now - self._last_sse_heartbeat_time) * 1000
                            self.stats["sse"]["heartbeat_intervals_ms"].append(interval_ms)
                        self._last_sse_heartbeat_time = now
                    
                    # FIX-047: Handle candle_update events
                    elif event_type == "candle_update":
                        symbol = data.get("symbol", "")
                        candle = data.get("candle", {})
                        candle_ts = candle.get("ts", "")
                        self.stats["sse"]["symbols_seen"].add(symbol)
                        self.stats["sse"]["candle_updates_by_symbol"][symbol] += 1
                        self._log("INFO", "SSE", f"CANDLE_UPDATE {symbol}", ts=candle_ts)
                        
                        # Track interval between candle updates
                        if self._last_sse_candle_time:
                            interval_ms = (now - self._last_sse_candle_time) * 1000
                            self.stats["sse"]["candle_update_intervals_ms"].append(interval_ms)
                        self._last_sse_candle_time = now
                        
                    elif event_type == "option_chain_update":
                        symbol = data.get("symbol", "")
                        mode = data.get("mode", "")
                        strikes = len(data.get("strikes", []))
                        self._log("INFO", "SSE", f"OPTION_CHAIN_UPDATE {symbol}/{mode}", strikes=strikes)
                        
            except requests.exceptions.Timeout:
                self.stats["sse"]["errors"].append("Connection timeout")
                self._log("WARN", "SSE", "Connection timeout")
            except requests.exceptions.ConnectionError as e:
                error_str = f"Connection error: {e}"
                self.stats["sse"]["errors"].append(error_str)
                self._log("ERROR", "SSE", f"Connection error: {e}")
            except Exception as e:
                error_str = str(e)
                self.stats["sse"]["errors"].append(error_str)
                self._log("ERROR", "SSE", f"Error: {e}")
            
            if self.running:
                self.stats["sse"]["disconnects"] += 1
                self._log("WARN", "SSE", "Reconnecting in 5s...")
                time.sleep(5)
    
    # =========================================================================
    # Main Run
    # =========================================================================
    
    def run(self):
        """Run the full flow validation test."""
        self._log("INFO", "MAIN", "=" * 70)
        self._log("INFO", "MAIN", "FULL FLOW VALIDATION TEST")
        self._log("INFO", "MAIN", "=" * 70)
        self._log("INFO", "MAIN", f"API URL: {API_URL}")
        self._log("INFO", "MAIN", f"Symbols: {SYMBOLS}")
        self._log("INFO", "MAIN", f"Duration: {self.duration_seconds // 60} minutes")
        self._log("INFO", "MAIN", f"Tick Interval: {self.tick_interval}s (0=sub-second)")
        self._log("INFO", "MAIN", f"Results dir: {self.results_dir}")
        self._log("INFO", "MAIN", "=" * 70)
        
        self.start_time = time.time()
        
        # Step 1: Bootstrap
        if not self._run_bootstrap():
            self._log("ERROR", "MAIN", "Bootstrap failed, continuing with streams...")
        
        # Step 2: Start streams
        self.running = True
        
        self._ws_thread = threading.Thread(target=self._run_websocket, daemon=True)
        self._sse_thread = threading.Thread(target=self._run_sse, daemon=True)
        
        self._ws_thread.start()
        self._sse_thread.start()
        
        self._log("INFO", "MAIN", "Streams started, running for duration...")
        
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
        
        # Stop streams
        self._log("INFO", "MAIN", "Stopping streams...")
        self.running = False
        
        if self._ws:
            try:
                self._ws.close()
            except:
                pass
        
        # Wait for threads
        if self._ws_thread:
            self._ws_thread.join(timeout=5)
        if self._sse_thread:
            self._sse_thread.join(timeout=5)
        
        # Save results
        self._save_results()
        
        # Print summary
        self._print_summary()
        
        return self.stats
    
    def _save_results(self):
        """Save all raw data and statistics to files."""
        run_dir = self.results_dir / f"run_{self.run_timestamp}"
        run_dir.mkdir(exist_ok=True)
        
        # Save bootstrap data
        if self.bootstrap_data:
            with open(run_dir / "bootstrap_response.json", "w") as f:
                json.dump(self.bootstrap_data, f, indent=2, default=str)
            self._log("INFO", "SAVE", f"Saved bootstrap data: {len(json.dumps(self.bootstrap_data))} bytes")
        
        # Save WebSocket events
        with open(run_dir / "ws_events.json", "w") as f:
            json.dump(self.ws_events, f, indent=2, default=str)
        self._log("INFO", "SAVE", f"Saved {len(self.ws_events)} WebSocket events")
        
        # Save SSE events
        with open(run_dir / "sse_events.json", "w") as f:
            json.dump(self.sse_events, f, indent=2, default=str)
        self._log("INFO", "SAVE", f"Saved {len(self.sse_events)} SSE events")
        
        # Convert sets to lists for JSON serialization
        stats_serializable = json.loads(json.dumps(self.stats, default=lambda x: list(x) if isinstance(x, set) else str(x)))
        
        # Save statistics
        with open(run_dir / "statistics.json", "w") as f:
            json.dump(stats_serializable, f, indent=2)
        self._log("INFO", "SAVE", f"Saved statistics to {run_dir / 'statistics.json'}")
        
        # Save summary report
        self._save_summary_report(run_dir)
    
    def _save_summary_report(self, run_dir: Path):
        """Save human-readable summary report."""
        report_lines = []
        report_lines.append("# Full Flow Validation Report")
        report_lines.append(f"\n**Run Timestamp:** {self.run_timestamp}")
        report_lines.append(f"**Duration:** {self.duration_seconds // 60} minutes")
        report_lines.append(f"**API URL:** {API_URL}")
        
        # Bootstrap
        report_lines.append("\n## Bootstrap")
        report_lines.append(f"- Success: {self.stats['bootstrap']['success']}")
        report_lines.append(f"- Response Time: {self.stats['bootstrap']['response_time_ms']:.0f}ms" if self.stats['bootstrap']['response_time_ms'] else "- Response Time: N/A")
        report_lines.append(f"- Symbols: {self.stats['bootstrap']['symbols_received']}")
        if self.stats['bootstrap']['error']:
            report_lines.append(f"- Error: {self.stats['bootstrap']['error']}")
        
        # WebSocket
        report_lines.append("\n## WebSocket (Fast Stream)")
        report_lines.append(f"- Connected: {self.stats['websocket']['connected']}")
        report_lines.append(f"- Connection Time: {self.stats['websocket']['connection_time_ms']:.0f}ms" if self.stats['websocket']['connection_time_ms'] else "- Connection Time: N/A")
        report_lines.append(f"- Total Messages: {self.stats['websocket']['total_messages']}")
        report_lines.append(f"- Disconnects: {self.stats['websocket']['disconnects']}")
        report_lines.append(f"- Reconnects: {self.stats['websocket']['reconnects']}")
        report_lines.append(f"- Data Gaps (>5s): {self.stats['websocket']['data_gaps_over_5s']}")
        report_lines.append(f"- Symbols Seen: {sorted(self.stats['websocket']['symbols_seen'])}")
        report_lines.append(f"- Pings/Pongs: {self.stats['websocket']['pings_received']}/{self.stats['websocket']['pongs_sent']}")
        report_lines.append("\n### Events by Type")
        for event_type, count in sorted(self.stats['websocket']['events_by_type'].items()):
            report_lines.append(f"- {event_type}: {count}")
        
        # Tick intervals
        if self.stats['websocket']['tick_intervals_ms']:
            intervals = self.stats['websocket']['tick_intervals_ms']
            report_lines.append("\n### Tick Intervals - Overall (ms)")
            report_lines.append(f"- Count: {len(intervals)}")
            report_lines.append(f"- Min: {min(intervals):.0f}")
            report_lines.append(f"- Max: {max(intervals):.0f}")
            report_lines.append(f"- Mean: {statistics.mean(intervals):.0f}")
            report_lines.append(f"- Median: {statistics.median(intervals):.0f}")
            if len(intervals) > 1:
                report_lines.append(f"- Std Dev: {statistics.stdev(intervals):.0f}")
        
        # Per-symbol tick intervals
        if self.stats['websocket']['tick_intervals_by_symbol']:
            report_lines.append("\n### Tick Intervals - Per Symbol (ms)")
            for symbol, intervals in sorted(self.stats['websocket']['tick_intervals_by_symbol'].items()):
                if intervals:
                    report_lines.append(f"\n**{symbol}:**")
                    report_lines.append(f"- Count: {len(intervals)}")
                    report_lines.append(f"- Min: {min(intervals):.0f}")
                    report_lines.append(f"- Max: {max(intervals):.0f}")
                    report_lines.append(f"- Mean: {statistics.mean(intervals):.0f}")
                    report_lines.append(f"- Median: {statistics.median(intervals):.0f}")
        
        # Option chain LTP intervals
        if self.stats['websocket']['option_chain_ltp_intervals_ms']:
            intervals = self.stats['websocket']['option_chain_ltp_intervals_ms']
            report_lines.append("\n### Option Chain LTP Intervals (ms)")
            report_lines.append(f"- Count: {len(intervals)}")
            report_lines.append(f"- Min: {min(intervals):.0f}")
            report_lines.append(f"- Max: {max(intervals):.0f}")
            report_lines.append(f"- Mean: {statistics.mean(intervals):.0f}")
        
        # FIX-050: Close codes tracking
        if self.stats['websocket']['close_codes']:
            report_lines.append("\n### Close Codes")
            for code, count in sorted(self.stats['websocket']['close_codes'].items()):
                code_desc = {
                    0: "Unknown",
                    1000: "Normal close",
                    4001: "Auth failed",
                    4003: "Forbidden",
                    4005: "Slow client",
                }.get(code, "Other")
                report_lines.append(f"- {code} ({code_desc}): {count}")
            report_lines.append(f"- Unexpected closes: {self.stats['websocket']['unexpected_closes']}")
        
        if self.stats['websocket']['errors']:
            report_lines.append("\n### Errors")
            for error in self.stats['websocket']['errors'][:10]:
                report_lines.append(f"- {error}")
        
        # SSE
        report_lines.append("\n## SSE (Slow Stream)")
        report_lines.append(f"- Connected: {self.stats['sse']['connected']}")
        report_lines.append(f"- Connection Time: {self.stats['sse']['connection_time_ms']:.0f}ms" if self.stats['sse']['connection_time_ms'] else "- Connection Time: N/A")
        report_lines.append(f"- Total Messages: {self.stats['sse']['total_messages']}")
        report_lines.append(f"- Disconnects: {self.stats['sse']['disconnects']}")
        report_lines.append(f"- Reconnects: {self.stats['sse']['reconnects']}")
        report_lines.append(f"- Indicator Gaps (>90s): {self.stats['sse']['indicator_gaps_over_90s']}")
        report_lines.append(f"- Symbols Seen: {sorted(self.stats['sse']['symbols_seen'])}")
        report_lines.append("\n### Events by Type")
        for event_type, count in sorted(self.stats['sse']['events_by_type'].items()):
            report_lines.append(f"- {event_type}: {count}")
        
        # Indicator intervals
        if self.stats['sse']['indicator_intervals_ms']:
            intervals = self.stats['sse']['indicator_intervals_ms']
            report_lines.append("\n### Indicator Update Intervals (ms)")
            report_lines.append(f"- Count: {len(intervals)}")
            report_lines.append(f"- Min: {min(intervals):.0f}")
            report_lines.append(f"- Max: {max(intervals):.0f}")
            report_lines.append(f"- Mean: {statistics.mean(intervals):.0f}")
        
        # Heartbeat intervals
        if self.stats['sse']['heartbeat_intervals_ms']:
            intervals = self.stats['sse']['heartbeat_intervals_ms']
            report_lines.append("\n### Heartbeat Intervals (ms)")
            report_lines.append(f"- Count: {len(intervals)}")
            report_lines.append(f"- Min: {min(intervals):.0f}")
            report_lines.append(f"- Max: {max(intervals):.0f}")
            report_lines.append(f"- Mean: {statistics.mean(intervals):.0f}")
        
        # FIX-047: Candle update intervals
        if self.stats['sse']['candle_update_intervals_ms']:
            intervals = self.stats['sse']['candle_update_intervals_ms']
            report_lines.append("\n### Candle Update Intervals (ms)")
            report_lines.append(f"- Count: {len(intervals)}")
            report_lines.append(f"- Min: {min(intervals):.0f}")
            report_lines.append(f"- Max: {max(intervals):.0f}")
            report_lines.append(f"- Mean: {statistics.mean(intervals):.0f}")
        
        # FIX-047: Candle updates by symbol
        if self.stats['sse']['candle_updates_by_symbol']:
            report_lines.append("\n### Candle Updates by Symbol")
            for symbol, count in sorted(self.stats['sse']['candle_updates_by_symbol'].items()):
                report_lines.append(f"- {symbol}: {count}")
        
        if self.stats['sse']['errors']:
            report_lines.append("\n### Errors")
            for error in self.stats['sse']['errors'][:10]:
                report_lines.append(f"- {error}")
        
        # Write report
        with open(run_dir / "SUMMARY_REPORT.md", "w") as f:
            f.write("\n".join(report_lines))
        
        self._log("INFO", "SAVE", f"Saved summary report to {run_dir / 'SUMMARY_REPORT.md'}")
    
    def _print_summary(self):
        """Print validation summary to console."""
        print("\n" + "=" * 70)
        print("VALIDATION SUMMARY")
        print("=" * 70)
        
        print("\n--- BOOTSTRAP ---")
        print(f"  Success: {self.stats['bootstrap']['success']}")
        if self.stats['bootstrap']['response_time_ms']:
            print(f"  Response Time: {self.stats['bootstrap']['response_time_ms']:.0f}ms")
        print(f"  Symbols: {self.stats['bootstrap']['symbols_received']}")
        
        print("\n--- WEBSOCKET (Fast Stream) ---")
        print(f"  Connected: {self.stats['websocket']['connected']}")
        print(f"  Total Messages: {self.stats['websocket']['total_messages']}")
        print(f"  Events: {dict(self.stats['websocket']['events_by_type'])}")
        print(f"  Symbols: {sorted(self.stats['websocket']['symbols_seen'])}")
        print(f"  Disconnects/Reconnects: {self.stats['websocket']['disconnects']}/{self.stats['websocket']['reconnects']}")
        print(f"  Data Gaps (>5s): {self.stats['websocket']['data_gaps_over_5s']}")
        print(f"  Close Codes: {dict(self.stats['websocket']['close_codes'])}")
        print(f"  Unexpected Closes: {self.stats['websocket']['unexpected_closes']}")
        print(f"  Errors: {len(self.stats['websocket']['errors'])}")
        
        if self.stats['websocket']['tick_intervals_ms']:
            intervals = self.stats['websocket']['tick_intervals_ms']
            print(f"  Tick Interval (avg): {statistics.mean(intervals):.0f}ms")
        
        # Per-symbol tick intervals
        if self.stats['websocket']['tick_intervals_by_symbol']:
            print("  Per-Symbol Tick Intervals (avg ms):")
            for symbol, intervals in sorted(self.stats['websocket']['tick_intervals_by_symbol'].items()):
                if intervals:
                    print(f"    {symbol}: {statistics.mean(intervals):.0f}ms (n={len(intervals)})")
        
        print("\n--- SSE (Slow Stream) ---")
        print(f"  Connected: {self.stats['sse']['connected']}")
        print(f"  Total Messages: {self.stats['sse']['total_messages']}")
        print(f"  Events: {dict(self.stats['sse']['events_by_type'])}")
        print(f"  Symbols: {sorted(self.stats['sse']['symbols_seen'])}")
        print(f"  Disconnects/Reconnects: {self.stats['sse']['disconnects']}/{self.stats['sse']['reconnects']}")
        print(f"  Indicator Gaps (>90s): {self.stats['sse']['indicator_gaps_over_90s']}")
        print(f"  Errors: {len(self.stats['sse']['errors'])}")
        
        if self.stats['sse']['indicator_intervals_ms']:
            intervals = self.stats['sse']['indicator_intervals_ms']
            print(f"  Indicator Interval (avg): {statistics.mean(intervals):.0f}ms")
        
        print("\n--- OVERALL ---")
        total_errors = len(self.stats['websocket']['errors']) + len(self.stats['sse']['errors'])
        if total_errors == 0 and self.stats['bootstrap']['success']:
            print("  STATUS: PASS ✅")
        else:
            print(f"  STATUS: ISSUES FOUND ({total_errors} errors)")
        
        print(f"\n  Results saved to: {self.results_dir / f'run_{self.run_timestamp}'}")
        print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Full Flow Validation Test")
    parser.add_argument("--duration", type=int, default=DEFAULT_DURATION_MINUTES,
                        help=f"Test duration in minutes (default: {DEFAULT_DURATION_MINUTES})")
    parser.add_argument("--token", type=str, default=JWT_TOKEN,
                        help="JWT token for authentication")
    # FIX-050: Add tick_interval for WebSocket throttling
    parser.add_argument("--tick-interval", type=float, default=0.0,
                        help="WebSocket tick throttle in seconds (0-10, default: 0 = no throttle)")
    args = parser.parse_args()
    
    if not args.token:
        print("ERROR: No JWT token provided. Set ICEBERG_JWT_TOKEN env var or use --token")
        sys.exit(1)
    
    # Validate tick_interval range
    if args.tick_interval < 0 or args.tick_interval > 10:
        print("ERROR: tick_interval must be between 0 and 10 seconds")
        sys.exit(1)
    
    validator = FullFlowValidator(
        jwt_token=args.token,
        duration_minutes=args.duration,
        tick_interval=args.tick_interval,
    )
    stats = validator.run()
    
    # Exit with error code if validation failed
    total_errors = len(stats['websocket']['errors']) + len(stats['sse']['errors'])
    if not stats['bootstrap']['success'] or total_errors > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
