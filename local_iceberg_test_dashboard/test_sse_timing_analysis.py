#!/usr/bin/env python3
"""
SSE Timing Analysis Test Script

Comprehensive analysis of SSE (Slow Stream) and WebSocket (Fast Stream) timing.
Measures the delay between candle close and indicator/candle update receipt.

Key Metrics:
1. Indicator Update Delay: Time from candle close (candle_ts + 5min) to SSE receipt
2. Candle Update Delay: Time from candle close to SSE receipt
3. Fast Stream Tick Latency: Time between consecutive ticks

Breakdown by:
- Symbol (nifty, banknifty, sensex, finnifty)
- Mode (current, positional) for indicator updates
- Event type (indicator_update, candle_update, snapshot)

Usage:
    python test_sse_timing_analysis.py --duration 60 --token JWT_TOKEN
    
    # 6-minute validation run
    python test_sse_timing_analysis.py --duration 6 --token JWT_TOKEN
    
    # 1-hour production run
    python test_sse_timing_analysis.py --duration 60 --token JWT_TOKEN
"""

import argparse
import json
import os
import sys
import time
import threading
import statistics
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path
from dataclasses import dataclass, field, asdict

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

# IST timezone
IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class IndicatorUpdateRecord:
    """Record of an indicator_update SSE event."""
    received_at: float  # Unix timestamp
    received_at_iso: str
    symbol: str
    mode: str
    candle_ts: Optional[str]  # ISO timestamp of the candle bucket
    candle_close_time: Optional[str]  # candle_ts + 5 minutes
    delay_from_candle_close_seconds: Optional[float]  # How long after candle close we received this
    is_first_update: bool  # True if this is the first update for this (symbol, mode, candle_ts)
    skew: Optional[float]
    pcr: Optional[float]
    raw_event: Dict[str, Any]


@dataclass
class CandleUpdateRecord:
    """Record of a candle_update SSE event."""
    received_at: float
    received_at_iso: str
    symbol: str
    candle_ts: Optional[str]  # ts field from candle (bucket start time)
    candle_close_time: Optional[str]  # candle_ts + 5 minutes
    delay_from_candle_close_seconds: Optional[float]  # Positive = after close, Negative = before close (in-progress)
    is_completed_candle: bool  # True if received after candle close time
    close_price: Optional[float]
    raw_event: Dict[str, Any]


@dataclass
class SnapshotRecord:
    """Record of a snapshot SSE event."""
    received_at: float
    received_at_iso: str
    symbol: str
    mode: str
    candle_ts: Optional[str]
    raw_event: Dict[str, Any]


@dataclass
class FastStreamTickRecord:
    """Record of a fast stream tick event."""
    received_at: float
    received_at_iso: str
    symbol: str
    ltp: Optional[float]
    change: Optional[float]
    change_pct: Optional[float]


@dataclass
class TimingStats:
    """Statistics for a timing metric."""
    count: int = 0
    min_ms: Optional[float] = None
    max_ms: Optional[float] = None
    mean_ms: Optional[float] = None
    median_ms: Optional[float] = None
    std_dev_ms: Optional[float] = None
    p95_ms: Optional[float] = None
    p99_ms: Optional[float] = None
    values: List[float] = field(default_factory=list)
    
    def compute(self, values_ms: List[float]) -> None:
        """Compute statistics from a list of values in milliseconds."""
        self.values = values_ms
        self.count = len(values_ms)
        if self.count == 0:
            return
        self.min_ms = min(values_ms)
        self.max_ms = max(values_ms)
        self.mean_ms = statistics.mean(values_ms)
        self.median_ms = statistics.median(values_ms)
        if self.count > 1:
            self.std_dev_ms = statistics.stdev(values_ms)
        sorted_vals = sorted(values_ms)
        self.p95_ms = sorted_vals[int(self.count * 0.95)] if self.count >= 20 else None
        self.p99_ms = sorted_vals[int(self.count * 0.99)] if self.count >= 100 else None


class SSETimingAnalyzer:
    """Analyzes SSE and Fast Stream timing with detailed breakdown."""
    
    def __init__(self, jwt_token: str, duration_minutes: int = DEFAULT_DURATION_MINUTES):
        self.jwt_token = jwt_token
        self.duration_seconds = duration_minutes * 60
        self.running = False
        self.start_time: Optional[float] = None
        
        # Results directory
        self.results_dir = Path(__file__).parent / "results"
        self.results_dir.mkdir(exist_ok=True)
        self.run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Raw event storage
        self.indicator_updates: List[IndicatorUpdateRecord] = []
        self.candle_updates: List[CandleUpdateRecord] = []
        self.snapshots: List[SnapshotRecord] = []
        self.fast_stream_ticks: List[FastStreamTickRecord] = []
        self.heartbeats: List[Dict[str, Any]] = []
        self.raw_sse_events: List[Dict[str, Any]] = []
        self.raw_ws_events: List[Dict[str, Any]] = []
        
        # Connection stats
        self.sse_connected = False
        self.sse_connection_time_ms: Optional[float] = None
        self.ws_connected = False
        self.ws_connection_time_ms: Optional[float] = None
        self.sse_disconnects = 0
        self.ws_disconnects = 0
        self.sse_errors: List[str] = []
        self.ws_errors: List[str] = []
        
        # Thread references
        self._ws_thread: Optional[threading.Thread] = None
        self._sse_thread: Optional[threading.Thread] = None
        self._ws: Optional[websocket.WebSocketApp] = None
        
        # Tick timing tracking
        self._last_tick_time_by_symbol: Dict[str, float] = {}
        self._tick_intervals_by_symbol: Dict[str, List[float]] = defaultdict(list)
        
        # Track seen candle timestamps to only count FIRST update per candle
        # Key: (symbol, mode, candle_ts) for indicators, (symbol, candle_ts) for candles
        self._seen_indicator_candles: set = set()
        self._seen_candle_updates: set = set()
    
    def _log(self, level: str, component: str, message: str, **kwargs):
        """Log with timestamp and structured data."""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        extra = " ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
        print(f"[{ts}] [{level}] [{component}] {message} {extra}")
    
    def _parse_iso_timestamp(self, ts_str: Optional[str]) -> Optional[datetime]:
        """Parse ISO timestamp string to datetime."""
        if not ts_str:
            return None
        try:
            # Handle various ISO formats
            if ts_str.endswith('Z'):
                ts_str = ts_str[:-1] + '+00:00'
            return datetime.fromisoformat(ts_str)
        except (ValueError, TypeError):
            return None
    
    def _calculate_candle_close_time(self, candle_ts: Optional[str]) -> Tuple[Optional[str], Optional[datetime]]:
        """
        Calculate candle close time from candle_ts.
        Candle close = candle_ts + 5 minutes.
        """
        candle_dt = self._parse_iso_timestamp(candle_ts)
        if not candle_dt:
            return None, None
        close_dt = candle_dt + timedelta(minutes=5)
        return close_dt.isoformat(), close_dt
    
    def _calculate_delay_from_candle_close(
        self, 
        received_at: float, 
        candle_ts: Optional[str]
    ) -> Optional[float]:
        """
        Calculate delay in seconds from candle close to event receipt.
        
        Candle close = candle_ts + 5 minutes
        Delay = received_at - candle_close
        """
        _, close_dt = self._calculate_candle_close_time(candle_ts)
        if not close_dt:
            return None
        
        # Convert received_at (unix timestamp) to datetime
        received_dt = datetime.fromtimestamp(received_at, tz=timezone.utc)
        
        # Calculate delay
        delay = (received_dt - close_dt).total_seconds()
        return delay
    
    # =========================================================================
    # SSE (Slow Stream) Handler
    # =========================================================================
    
    def _run_sse(self):
        """Run SSE connection to collect indicator and candle updates."""
        symbols_param = ",".join(SYMBOLS)
        modes_param = ",".join(MODES)
        url = f"{API_URL}/v1/stream/indicators/tiered?token={self.jwt_token}&symbols={symbols_param}&modes={modes_param}&include_optional=true&include_candles=true"
        
        self._log("INFO", "SSE", "Connecting...", url_prefix=url[:80])
        
        while self.running:
            sse_start_time = time.time()
            try:
                response = requests.get(url, stream=True, timeout=300)
                
                if response.status_code != 200:
                    self.sse_errors.append(f"HTTP {response.status_code}")
                    self._log("ERROR", "SSE", f"HTTP {response.status_code}")
                    time.sleep(5)
                    continue
                
                elapsed_ms = (time.time() - sse_start_time) * 1000
                if not self.sse_connected:
                    self.sse_connected = True
                    self.sse_connection_time_ms = elapsed_ms
                    self._log("INFO", "SSE", "CONNECTED", connection_time_ms=f"{elapsed_ms:.0f}")
                else:
                    self._log("INFO", "SSE", "RECONNECTED", connection_time_ms=f"{elapsed_ms:.0f}")
                
                client = sseclient.SSEClient(response)
                
                for event in client.events():
                    if not self.running:
                        break
                    
                    received_at = time.time()
                    received_at_iso = datetime.now(IST).isoformat()
                    event_type = event.event or "message"
                    
                    try:
                        data = json.loads(event.data) if event.data else {}
                    except json.JSONDecodeError:
                        data = {"raw": event.data}
                    
                    # Store raw event
                    raw_event = {
                        "received_at": received_at,
                        "received_at_iso": received_at_iso,
                        "event_type": event_type,
                        "event_id": event.id,
                        "data": data,
                    }
                    self.raw_sse_events.append(raw_event)
                    
                    # Process by event type
                    if event_type == "indicator_update":
                        self._handle_indicator_update(received_at, received_at_iso, data)
                    elif event_type == "candle_update":
                        self._handle_candle_update(received_at, received_at_iso, data)
                    elif event_type == "snapshot":
                        self._handle_snapshot(received_at, received_at_iso, data)
                    elif event_type == "heartbeat":
                        self.heartbeats.append(raw_event)
                        
            except requests.exceptions.Timeout:
                self.sse_errors.append("Connection timeout")
                self._log("WARN", "SSE", "Connection timeout")
            except requests.exceptions.ConnectionError as e:
                self.sse_errors.append(f"Connection error: {e}")
                self._log("ERROR", "SSE", f"Connection error: {e}")
            except Exception as e:
                self.sse_errors.append(str(e))
                self._log("ERROR", "SSE", f"Error: {e}")
            
            if self.running:
                self.sse_disconnects += 1
                self._log("WARN", "SSE", "Reconnecting in 5s...")
                time.sleep(5)
    
    def _handle_indicator_update(self, received_at: float, received_at_iso: str, data: Dict[str, Any]):
        """Process indicator_update SSE event."""
        symbol = data.get("symbol", "").lower()
        mode = data.get("mode", "")
        candle_ts = data.get("candle_ts")  # FIX-070: New field
        
        # Check if this is the FIRST update for this (symbol, mode, candle_ts)
        candle_key = (symbol, mode, candle_ts)
        is_first_update = candle_key not in self._seen_indicator_candles
        if candle_ts:
            self._seen_indicator_candles.add(candle_key)
        
        # Calculate delay from candle close
        candle_close_time, _ = self._calculate_candle_close_time(candle_ts)
        delay = self._calculate_delay_from_candle_close(received_at, candle_ts)
        
        # Extract indicator values
        indicators = data.get("indicators", data)  # Handle both nested and flat structure
        skew = indicators.get("skew") if isinstance(indicators, dict) else data.get("skew")
        pcr = indicators.get("pcr") if isinstance(indicators, dict) else data.get("pcr")
        
        record = IndicatorUpdateRecord(
            received_at=received_at,
            received_at_iso=received_at_iso,
            symbol=symbol,
            mode=mode,
            candle_ts=candle_ts,
            candle_close_time=candle_close_time,
            delay_from_candle_close_seconds=delay,
            is_first_update=is_first_update,
            skew=skew,
            pcr=pcr,
            raw_event=data,
        )
        self.indicator_updates.append(record)
        
        delay_str = f"{delay:.1f}s" if delay is not None else "N/A"
        first_str = "[FIRST]" if is_first_update else "[REPEAT]"
        self._log("INFO", "SSE", f"indicator_update {symbol}/{mode} {first_str}", 
                  candle_ts=candle_ts, delay=delay_str)
    
    def _handle_candle_update(self, received_at: float, received_at_iso: str, data: Dict[str, Any]):
        """Process candle_update SSE event."""
        symbol = data.get("symbol", "").lower()
        candle = data.get("candle", {})
        candle_ts = candle.get("ts")  # Bucket start time
        close_price = candle.get("close")
        
        # Also check for candle_ts at top level (FIX-070)
        if not candle_ts:
            candle_ts = data.get("candle_ts")
        
        # Calculate delay from candle close
        candle_close_time, close_dt = self._calculate_candle_close_time(candle_ts)
        delay = self._calculate_delay_from_candle_close(received_at, candle_ts)
        
        # Determine if this is a completed candle (received after close time)
        is_completed = delay is not None and delay >= 0
        
        record = CandleUpdateRecord(
            received_at=received_at,
            received_at_iso=received_at_iso,
            symbol=symbol,
            candle_ts=candle_ts,
            candle_close_time=candle_close_time,
            delay_from_candle_close_seconds=delay,
            is_completed_candle=is_completed,
            close_price=close_price,
            raw_event=data,
        )
        self.candle_updates.append(record)
        
        delay_str = f"{delay:.1f}s" if delay is not None else "N/A"
        status = "COMPLETED" if is_completed else "IN-PROGRESS"
        self._log("INFO", "SSE", f"candle_update {symbol} [{status}]", 
                  candle_ts=candle_ts, delay=delay_str)
    
    def _handle_snapshot(self, received_at: float, received_at_iso: str, data: Dict[str, Any]):
        """Process snapshot SSE event."""
        # Snapshot can have data nested or at top level
        snapshot_data = data.get("data", data)
        symbol = snapshot_data.get("symbol", "").lower()
        mode = snapshot_data.get("mode", "")
        candle_ts = snapshot_data.get("candle_ts")
        
        record = SnapshotRecord(
            received_at=received_at,
            received_at_iso=received_at_iso,
            symbol=symbol,
            mode=mode,
            candle_ts=candle_ts,
            raw_event=data,
        )
        self.snapshots.append(record)
        
        self._log("INFO", "SSE", f"snapshot {symbol}/{mode}", candle_ts=candle_ts)

    
    # =========================================================================
    # WebSocket (Fast Stream) Handler
    # =========================================================================
    
    def _run_websocket(self):
        """Run WebSocket connection to collect tick data."""
        ws_url = API_URL.replace("https://", "wss://").replace("http://", "ws://")
        symbols_param = ",".join(SYMBOLS)
        url = f"{ws_url}/v1/stream/fast?token={self.jwt_token}&symbols={symbols_param}"
        
        ws_start_time = time.time()
        
        def on_open(ws):
            nonlocal ws_start_time
            elapsed_ms = (time.time() - ws_start_time) * 1000
            if not self.ws_connected:
                self.ws_connected = True
                self.ws_connection_time_ms = elapsed_ms
                self._log("INFO", "WS", "CONNECTED", connection_time_ms=f"{elapsed_ms:.0f}")
            else:
                self._log("INFO", "WS", "RECONNECTED", connection_time_ms=f"{elapsed_ms:.0f}")
            # Reset tick timing on reconnect
            self._last_tick_time_by_symbol.clear()
        
        def on_message(ws, message):
            received_at = time.time()
            received_at_iso = datetime.now(IST).isoformat()
            
            try:
                data = json.loads(message)
                event_type = data.get("event", "unknown")
                
                # Store raw event (sample - keep last 10000)
                if len(self.raw_ws_events) < 10000:
                    self.raw_ws_events.append({
                        "received_at": received_at,
                        "received_at_iso": received_at_iso,
                        "data": data,
                    })
                
                if event_type == "ping":
                    ws.send(json.dumps({"action": "pong"}))
                    
                elif event_type == "tick":
                    tick_data = data.get("data", {})
                    for symbol, tick_info in tick_data.items():
                        symbol_lower = symbol.lower()
                        
                        # Track tick interval per symbol
                        if symbol_lower in self._last_tick_time_by_symbol:
                            interval_ms = (received_at - self._last_tick_time_by_symbol[symbol_lower]) * 1000
                            self._tick_intervals_by_symbol[symbol_lower].append(interval_ms)
                        self._last_tick_time_by_symbol[symbol_lower] = received_at
                        
                        # Store tick record (sample - keep last 5000 per symbol)
                        if len([t for t in self.fast_stream_ticks if t.symbol == symbol_lower]) < 5000:
                            record = FastStreamTickRecord(
                                received_at=received_at,
                                received_at_iso=received_at_iso,
                                symbol=symbol_lower,
                                ltp=tick_info.get("ltp") if isinstance(tick_info, dict) else None,
                                change=tick_info.get("change") if isinstance(tick_info, dict) else None,
                                change_pct=tick_info.get("change_pct") if isinstance(tick_info, dict) else None,
                            )
                            self.fast_stream_ticks.append(record)
                    
                    # Log sample (every 500th tick)
                    if len(self.fast_stream_ticks) % 500 == 0:
                        self._log("INFO", "WS", f"Tick #{len(self.fast_stream_ticks)}", 
                                  symbols=list(tick_data.keys()))
                        
            except Exception as e:
                self.ws_errors.append(str(e))
                self._log("ERROR", "WS", f"Error: {e}")
        
        def on_error(ws, error):
            self.ws_errors.append(str(error))
            self._log("ERROR", "WS", f"Error: {error}")
        
        def on_close(ws, close_code, close_msg):
            self.ws_disconnects += 1
            self._log("INFO", "WS", f"CLOSED code={close_code}")
        
        self._log("INFO", "WS", "Connecting...", url_prefix=url[:60])
        
        while self.running:
            try:
                ws_start_time = time.time()
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
                self.ws_errors.append(str(e))
                self._log("ERROR", "WS", f"Connection error: {e}")
                if self.running:
                    time.sleep(2)
    
    # =========================================================================
    # Analysis and Reporting
    # =========================================================================
    
    def _compute_indicator_update_stats(self) -> Dict[str, Any]:
        """Compute statistics for indicator updates."""
        # Filter to only FIRST updates per candle for timing statistics
        first_updates = [r for r in self.indicator_updates if r.is_first_update]
        
        stats = {
            "total_count": len(self.indicator_updates),
            "first_update_count": len(first_updates),
            "repeat_update_count": len(self.indicator_updates) - len(first_updates),
            "by_symbol": {},
            "by_symbol_mode": {},
            "overall_delay": TimingStats(),  # Only from FIRST updates
        }
        
        # Group FIRST updates by symbol
        by_symbol: Dict[str, List[IndicatorUpdateRecord]] = defaultdict(list)
        for record in first_updates:
            by_symbol[record.symbol].append(record)
        
        # Group FIRST updates by (symbol, mode)
        by_symbol_mode: Dict[str, List[IndicatorUpdateRecord]] = defaultdict(list)
        for record in first_updates:
            key = f"{record.symbol}:{record.mode}"
            by_symbol_mode[key].append(record)
        
        # Compute stats by symbol (FIRST updates only)
        for symbol, records in by_symbol.items():
            delays = [r.delay_from_candle_close_seconds * 1000 
                      for r in records if r.delay_from_candle_close_seconds is not None]
            symbol_stats = TimingStats()
            symbol_stats.compute(delays)
            
            # Count total and first for this symbol
            total_for_symbol = len([r for r in self.indicator_updates if r.symbol == symbol])
            
            stats["by_symbol"][symbol] = {
                "total_count": total_for_symbol,
                "first_update_count": len(records),
                "with_candle_ts": sum(1 for r in records if r.candle_ts),
                "delay_stats": asdict(symbol_stats),
            }
        
        # Compute stats by (symbol, mode) (FIRST updates only)
        for key, records in by_symbol_mode.items():
            delays = [r.delay_from_candle_close_seconds * 1000 
                      for r in records if r.delay_from_candle_close_seconds is not None]
            key_stats = TimingStats()
            key_stats.compute(delays)
            
            # Count total for this key
            symbol, mode = key.split(":")
            total_for_key = len([r for r in self.indicator_updates if r.symbol == symbol and r.mode == mode])
            
            stats["by_symbol_mode"][key] = {
                "total_count": total_for_key,
                "first_update_count": len(records),
                "with_candle_ts": sum(1 for r in records if r.candle_ts),
                "delay_stats": asdict(key_stats),
            }
        
        # Overall delay stats (FIRST updates only)
        all_delays = [r.delay_from_candle_close_seconds * 1000 
                      for r in first_updates if r.delay_from_candle_close_seconds is not None]
        stats["overall_delay"].compute(all_delays)
        stats["overall_delay"] = asdict(stats["overall_delay"])
        
        return stats
    
    def _compute_candle_update_stats(self) -> Dict[str, Any]:
        """Compute statistics for candle updates."""
        # Separate completed vs in-progress candles
        completed_candles = [r for r in self.candle_updates if r.is_completed_candle]
        in_progress_candles = [r for r in self.candle_updates if not r.is_completed_candle]
        
        stats = {
            "total_count": len(self.candle_updates),
            "completed_count": len(completed_candles),
            "in_progress_count": len(in_progress_candles),
            "by_symbol": {},
            "completed_delay": TimingStats(),  # Only for completed candles
            "in_progress_timing": TimingStats(),  # How early we get in-progress updates
        }
        
        # Group by symbol
        by_symbol: Dict[str, List[CandleUpdateRecord]] = defaultdict(list)
        for record in self.candle_updates:
            by_symbol[record.symbol].append(record)
        
        # Compute stats by symbol
        for symbol, records in by_symbol.items():
            completed = [r for r in records if r.is_completed_candle]
            in_progress = [r for r in records if not r.is_completed_candle]
            
            # Completed candle delays (positive values)
            completed_delays = [r.delay_from_candle_close_seconds * 1000 
                               for r in completed if r.delay_from_candle_close_seconds is not None]
            completed_stats = TimingStats()
            completed_stats.compute(completed_delays)
            
            # In-progress timing (negative values converted to positive = how early)
            in_progress_early = [abs(r.delay_from_candle_close_seconds) * 1000 
                                for r in in_progress if r.delay_from_candle_close_seconds is not None]
            in_progress_stats = TimingStats()
            in_progress_stats.compute(in_progress_early)
            
            stats["by_symbol"][symbol] = {
                "total_count": len(records),
                "completed_count": len(completed),
                "in_progress_count": len(in_progress),
                "with_candle_ts": sum(1 for r in records if r.candle_ts),
                "completed_delay_stats": asdict(completed_stats),
                "in_progress_early_stats": asdict(in_progress_stats),
            }
        
        # Overall completed delay stats
        all_completed_delays = [r.delay_from_candle_close_seconds * 1000 
                               for r in completed_candles if r.delay_from_candle_close_seconds is not None]
        stats["completed_delay"].compute(all_completed_delays)
        stats["completed_delay"] = asdict(stats["completed_delay"])
        
        # Overall in-progress timing (how early before close)
        all_in_progress_early = [abs(r.delay_from_candle_close_seconds) * 1000 
                                for r in in_progress_candles if r.delay_from_candle_close_seconds is not None]
        stats["in_progress_timing"].compute(all_in_progress_early)
        stats["in_progress_timing"] = asdict(stats["in_progress_timing"])
        
        return stats
    
    def _compute_fast_stream_stats(self) -> Dict[str, Any]:
        """Compute statistics for fast stream ticks."""
        stats = {
            "total_ticks": len(self.fast_stream_ticks),
            "by_symbol": {},
        }
        
        # Compute stats by symbol
        for symbol, intervals in self._tick_intervals_by_symbol.items():
            symbol_stats = TimingStats()
            symbol_stats.compute(intervals)
            stats["by_symbol"][symbol] = {
                "tick_count": len([t for t in self.fast_stream_ticks if t.symbol == symbol]),
                "interval_stats": asdict(symbol_stats),
            }
        
        return stats
    
    # =========================================================================
    # Main Run
    # =========================================================================
    
    def run(self):
        """Run the timing analysis test."""
        self._log("INFO", "MAIN", "=" * 70)
        self._log("INFO", "MAIN", "SSE TIMING ANALYSIS TEST")
        self._log("INFO", "MAIN", "=" * 70)
        self._log("INFO", "MAIN", f"API URL: {API_URL}")
        self._log("INFO", "MAIN", f"Symbols: {SYMBOLS}")
        self._log("INFO", "MAIN", f"Modes: {MODES}")
        self._log("INFO", "MAIN", f"Duration: {self.duration_seconds // 60} minutes")
        self._log("INFO", "MAIN", "=" * 70)
        
        self.start_time = time.time()
        self.running = True
        
        # Start threads
        self._sse_thread = threading.Thread(target=self._run_sse, daemon=True)
        self._ws_thread = threading.Thread(target=self._run_websocket, daemon=True)
        
        self._sse_thread.start()
        self._ws_thread.start()
        
        self._log("INFO", "MAIN", "Streams started, running for duration...")
        
        # Wait for duration
        try:
            end_time = time.time() + self.duration_seconds
            while time.time() < end_time:
                remaining = int(end_time - time.time())
                if remaining % 60 == 0 and remaining > 0:
                    self._log("INFO", "MAIN", f"Time remaining: {remaining // 60} minutes",
                              indicator_updates=len(self.indicator_updates),
                              candle_updates=len(self.candle_updates),
                              ticks=len(self.fast_stream_ticks))
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
        for thread in [self._sse_thread, self._ws_thread]:
            if thread:
                thread.join(timeout=5)
        
        # Save and print results
        self._save_results()
        self._print_summary()
    
    def _save_results(self):
        """Save all data and statistics to files."""
        run_dir = self.results_dir / f"timing_analysis_{self.run_timestamp}"
        run_dir.mkdir(exist_ok=True)
        
        # Save indicator updates
        indicator_data = [asdict(r) for r in self.indicator_updates]
        # Remove raw_event from serialization to reduce size
        for d in indicator_data:
            d.pop("raw_event", None)
        with open(run_dir / "indicator_updates.json", "w") as f:
            json.dump(indicator_data, f, indent=2, default=str)
        
        # Save candle updates
        candle_data = [asdict(r) for r in self.candle_updates]
        for d in candle_data:
            d.pop("raw_event", None)
        with open(run_dir / "candle_updates.json", "w") as f:
            json.dump(candle_data, f, indent=2, default=str)
        
        # Save snapshots
        snapshot_data = [asdict(r) for r in self.snapshots]
        for d in snapshot_data:
            d.pop("raw_event", None)
        with open(run_dir / "snapshots.json", "w") as f:
            json.dump(snapshot_data, f, indent=2, default=str)
        
        # Save fast stream ticks (sample)
        tick_data = [asdict(r) for r in self.fast_stream_ticks[:5000]]
        with open(run_dir / "fast_stream_ticks_sample.json", "w") as f:
            json.dump(tick_data, f, indent=2, default=str)
        
        # Save raw SSE events
        with open(run_dir / "raw_sse_events.json", "w") as f:
            json.dump(self.raw_sse_events, f, indent=2, default=str)
        
        # Save raw WS events (sample)
        with open(run_dir / "raw_ws_events_sample.json", "w") as f:
            json.dump(self.raw_ws_events[:5000], f, indent=2, default=str)
        
        # Compute and save statistics
        stats = {
            "run_info": {
                "timestamp": self.run_timestamp,
                "duration_minutes": self.duration_seconds // 60,
                "api_url": API_URL,
                "symbols": SYMBOLS,
                "modes": MODES,
            },
            "connection": {
                "sse_connected": self.sse_connected,
                "sse_connection_time_ms": self.sse_connection_time_ms,
                "sse_disconnects": self.sse_disconnects,
                "sse_errors": self.sse_errors[:10],
                "ws_connected": self.ws_connected,
                "ws_connection_time_ms": self.ws_connection_time_ms,
                "ws_disconnects": self.ws_disconnects,
                "ws_errors": self.ws_errors[:10],
            },
            "event_counts": {
                "indicator_updates": len(self.indicator_updates),
                "candle_updates": len(self.candle_updates),
                "snapshots": len(self.snapshots),
                "heartbeats": len(self.heartbeats),
                "fast_stream_ticks": len(self.fast_stream_ticks),
            },
            "indicator_update_stats": self._compute_indicator_update_stats(),
            "candle_update_stats": self._compute_candle_update_stats(),
            "fast_stream_stats": self._compute_fast_stream_stats(),
        }
        
        with open(run_dir / "statistics.json", "w") as f:
            json.dump(stats, f, indent=2, default=str)
        
        # Save summary report
        self._save_summary_report(run_dir, stats)
        
        self._log("INFO", "SAVE", f"Results saved to {run_dir}")
    
    def _save_summary_report(self, run_dir: Path, stats: Dict[str, Any]):
        """Save human-readable summary report."""
        lines = []
        lines.append("# SSE Timing Analysis Report")
        lines.append(f"\n**Run Timestamp:** {self.run_timestamp}")
        lines.append(f"**Duration:** {self.duration_seconds // 60} minutes")
        lines.append(f"**API URL:** {API_URL}")
        
        lines.append("\n## Connection Status")
        lines.append(f"- SSE Connected: {self.sse_connected}")
        lines.append(f"- SSE Connection Time: {self.sse_connection_time_ms:.0f}ms" if self.sse_connection_time_ms else "- SSE Connection Time: N/A")
        lines.append(f"- SSE Disconnects: {self.sse_disconnects}")
        lines.append(f"- WS Connected: {self.ws_connected}")
        lines.append(f"- WS Connection Time: {self.ws_connection_time_ms:.0f}ms" if self.ws_connection_time_ms else "- WS Connection Time: N/A")
        lines.append(f"- WS Disconnects: {self.ws_disconnects}")
        
        lines.append("\n## Event Counts")
        lines.append(f"- Indicator Updates: {len(self.indicator_updates)}")
        lines.append(f"- Candle Updates: {len(self.candle_updates)}")
        lines.append(f"- Snapshots: {len(self.snapshots)}")
        lines.append(f"- Heartbeats: {len(self.heartbeats)}")
        lines.append(f"- Fast Stream Ticks: {len(self.fast_stream_ticks)}")
        
        # Indicator Update Analysis
        lines.append("\n## Indicator Update Timing Analysis")
        lines.append(f"\n- Total Updates: {stats['indicator_update_stats']['total_count']}")
        lines.append(f"- First Updates (unique candles): {stats['indicator_update_stats']['first_update_count']}")
        lines.append(f"- Repeat Updates: {stats['indicator_update_stats']['repeat_update_count']}")
        
        lines.append("\n### Overall Delay from Candle Close (First Updates Only)")
        ind_stats = stats["indicator_update_stats"]["overall_delay"]
        if ind_stats["count"] > 0:
            lines.append(f"- Count: {ind_stats['count']}")
            lines.append(f"- Min: {ind_stats['min_ms']:.0f}ms ({ind_stats['min_ms']/1000:.1f}s)")
            lines.append(f"- Max: {ind_stats['max_ms']:.0f}ms ({ind_stats['max_ms']/1000:.1f}s)")
            lines.append(f"- Mean: {ind_stats['mean_ms']:.0f}ms ({ind_stats['mean_ms']/1000:.1f}s)")
            lines.append(f"- Median: {ind_stats['median_ms']:.0f}ms ({ind_stats['median_ms']/1000:.1f}s)")
        else:
            lines.append("- No data with candle_ts available")
        
        lines.append("\n### By Symbol (First Updates Only)")
        for symbol, data in stats["indicator_update_stats"]["by_symbol"].items():
            lines.append(f"\n**{symbol.upper()}:**")
            lines.append(f"- Total Updates: {data['total_count']}, First Updates: {data['first_update_count']}")
            lines.append(f"- With candle_ts: {data['with_candle_ts']}")
            if data["delay_stats"]["count"] > 0:
                ds = data["delay_stats"]
                lines.append(f"- Delay Mean: {ds['mean_ms']:.0f}ms ({ds['mean_ms']/1000:.1f}s)")
                lines.append(f"- Delay Median: {ds['median_ms']:.0f}ms ({ds['median_ms']/1000:.1f}s)")
        
        lines.append("\n### By Symbol + Mode (First Updates Only)")
        for key, data in stats["indicator_update_stats"]["by_symbol_mode"].items():
            lines.append(f"\n**{key}:**")
            lines.append(f"- Total Updates: {data['total_count']}, First Updates: {data['first_update_count']}")
            lines.append(f"- With candle_ts: {data['with_candle_ts']}")
            if data["delay_stats"]["count"] > 0:
                ds = data["delay_stats"]
                lines.append(f"- Delay Mean: {ds['mean_ms']:.0f}ms ({ds['mean_ms']/1000:.1f}s)")
                lines.append(f"- Delay Median: {ds['median_ms']:.0f}ms ({ds['median_ms']/1000:.1f}s)")
        
        # Candle Update Analysis
        lines.append("\n## Candle Update Timing Analysis")
        lines.append(f"\n- Total Candle Updates: {stats['candle_update_stats']['total_count']}")
        lines.append(f"- Completed Candles: {stats['candle_update_stats']['completed_count']}")
        lines.append(f"- In-Progress Candles: {stats['candle_update_stats']['in_progress_count']}")
        
        lines.append("\n### Completed Candle Delay (from candle close)")
        completed_stats = stats["candle_update_stats"]["completed_delay"]
        if completed_stats["count"] > 0:
            lines.append(f"- Count: {completed_stats['count']}")
            lines.append(f"- Min: {completed_stats['min_ms']:.0f}ms ({completed_stats['min_ms']/1000:.1f}s)")
            lines.append(f"- Max: {completed_stats['max_ms']:.0f}ms ({completed_stats['max_ms']/1000:.1f}s)")
            lines.append(f"- Mean: {completed_stats['mean_ms']:.0f}ms ({completed_stats['mean_ms']/1000:.1f}s)")
            lines.append(f"- Median: {completed_stats['median_ms']:.0f}ms ({completed_stats['median_ms']/1000:.1f}s)")
        else:
            lines.append("- No completed candle updates received")
        
        lines.append("\n### In-Progress Candle Timing (how early before close)")
        in_progress_stats = stats["candle_update_stats"]["in_progress_timing"]
        if in_progress_stats["count"] > 0:
            lines.append(f"- Count: {in_progress_stats['count']}")
            lines.append(f"- Min: {in_progress_stats['min_ms']:.0f}ms ({in_progress_stats['min_ms']/1000:.1f}s) before close")
            lines.append(f"- Max: {in_progress_stats['max_ms']:.0f}ms ({in_progress_stats['max_ms']/1000:.1f}s) before close")
            lines.append(f"- Mean: {in_progress_stats['mean_ms']:.0f}ms ({in_progress_stats['mean_ms']/1000:.1f}s) before close")
        else:
            lines.append("- No in-progress candle updates received")
        
        lines.append("\n### By Symbol")
        for symbol, data in stats["candle_update_stats"]["by_symbol"].items():
            lines.append(f"\n**{symbol.upper()}:**")
            lines.append(f"- Total: {data['total_count']} (Completed: {data['completed_count']}, In-Progress: {data['in_progress_count']})")
            if data["completed_delay_stats"]["count"] > 0:
                ds = data["completed_delay_stats"]
                lines.append(f"- Completed Delay Mean: {ds['mean_ms']:.0f}ms ({ds['mean_ms']/1000:.1f}s)")
            if data["in_progress_early_stats"]["count"] > 0:
                es = data["in_progress_early_stats"]
                lines.append(f"- In-Progress Early Mean: {es['mean_ms']:.0f}ms ({es['mean_ms']/1000:.1f}s) before close")
        
        # Fast Stream Analysis
        lines.append("\n## Fast Stream Tick Analysis")
        lines.append(f"\n- Total Ticks: {len(self.fast_stream_ticks)}")
        
        lines.append("\n### Tick Intervals by Symbol")
        for symbol, data in stats["fast_stream_stats"]["by_symbol"].items():
            lines.append(f"\n**{symbol.upper()}:**")
            lines.append(f"- Tick Count: {data['tick_count']}")
            if data["interval_stats"]["count"] > 0:
                is_ = data["interval_stats"]
                lines.append(f"- Interval Mean: {is_['mean_ms']:.0f}ms")
                lines.append(f"- Interval Median: {is_['median_ms']:.0f}ms")
                lines.append(f"- Interval Min: {is_['min_ms']:.0f}ms")
                lines.append(f"- Interval Max: {is_['max_ms']:.0f}ms")
        
        # Write report
        with open(run_dir / "SUMMARY_REPORT.md", "w") as f:
            f.write("\n".join(lines))
    
    def _print_summary(self):
        """Print summary to console."""
        print("\n" + "=" * 70)
        print("SSE TIMING ANALYSIS SUMMARY")
        print("=" * 70)
        
        print("\n--- CONNECTION ---")
        print(f"  SSE Connected: {self.sse_connected}")
        print(f"  WS Connected: {self.ws_connected}")
        print(f"  SSE Disconnects: {self.sse_disconnects}")
        print(f"  WS Disconnects: {self.ws_disconnects}")
        
        print("\n--- EVENT COUNTS ---")
        print(f"  Indicator Updates: {len(self.indicator_updates)}")
        print(f"  Candle Updates: {len(self.candle_updates)}")
        print(f"  Snapshots: {len(self.snapshots)}")
        print(f"  Heartbeats: {len(self.heartbeats)}")
        print(f"  Fast Stream Ticks: {len(self.fast_stream_ticks)}")
        
        # Indicator delay summary
        print("\n--- INDICATOR UPDATE DELAY (from candle close) ---")
        first_updates = [r for r in self.indicator_updates if r.is_first_update]
        print(f"  Total updates: {len(self.indicator_updates)} (First: {len(first_updates)}, Repeat: {len(self.indicator_updates) - len(first_updates)})")
        
        delays = [r.delay_from_candle_close_seconds 
                  for r in first_updates if r.delay_from_candle_close_seconds is not None]
        if delays:
            print(f"  First Update Delays (count={len(delays)}):")
            print(f"    Mean: {statistics.mean(delays):.1f}s")
            print(f"    Median: {statistics.median(delays):.1f}s")
            print(f"    Min: {min(delays):.1f}s")
            print(f"    Max: {max(delays):.1f}s")
        else:
            print("  No first update data with candle_ts available")
        
        # Candle delay summary
        print("\n--- CANDLE UPDATE DELAY (from candle close) ---")
        completed_candles = [r for r in self.candle_updates if r.is_completed_candle]
        in_progress_candles = [r for r in self.candle_updates if not r.is_completed_candle]
        print(f"  Total: {len(self.candle_updates)} (Completed: {len(completed_candles)}, In-Progress: {len(in_progress_candles)})")
        
        # Completed candles
        completed_delays = [r.delay_from_candle_close_seconds 
                          for r in completed_candles if r.delay_from_candle_close_seconds is not None]
        if completed_delays:
            print(f"  Completed Candle Delay:")
            print(f"    Mean: {statistics.mean(completed_delays):.1f}s after close")
            print(f"    Median: {statistics.median(completed_delays):.1f}s after close")
            print(f"    Min: {min(completed_delays):.1f}s, Max: {max(completed_delays):.1f}s")
        
        # In-progress candles
        in_progress_early = [abs(r.delay_from_candle_close_seconds) 
                           for r in in_progress_candles if r.delay_from_candle_close_seconds is not None]
        if in_progress_early:
            print(f"  In-Progress Candle Timing:")
            print(f"    Mean: {statistics.mean(in_progress_early):.1f}s before close")
            print(f"    Median: {statistics.median(in_progress_early):.1f}s before close")
        
        # By symbol breakdown
        print("\n--- INDICATOR UPDATES BY SYMBOL (First Updates Only) ---")
        by_symbol: Dict[str, List[IndicatorUpdateRecord]] = defaultdict(list)
        for r in self.indicator_updates:
            if r.is_first_update:
                by_symbol[r.symbol].append(r)
        for symbol in sorted(by_symbol.keys()):
            records = by_symbol[symbol]
            delays = [r.delay_from_candle_close_seconds for r in records if r.delay_from_candle_close_seconds is not None]
            if delays:
                print(f"  {symbol}: count={len(records)}, mean_delay={statistics.mean(delays):.1f}s")
            else:
                print(f"  {symbol}: count={len(records)}, no candle_ts data")
        
        print("\n--- INDICATOR UPDATES BY SYMBOL+MODE (First Updates Only) ---")
        by_key: Dict[str, List[IndicatorUpdateRecord]] = defaultdict(list)
        for r in self.indicator_updates:
            if r.is_first_update:
                key = f"{r.symbol}:{r.mode}"
                by_key[key].append(r)
        for key in sorted(by_key.keys()):
            records = by_key[key]
            delays = [r.delay_from_candle_close_seconds for r in records if r.delay_from_candle_close_seconds is not None]
            if delays:
                print(f"  {key}: count={len(records)}, mean_delay={statistics.mean(delays):.1f}s")
            else:
                print(f"  {key}: count={len(records)}, no candle_ts data")
        
        print("\n" + "=" * 70)
        print(f"Results saved to: {self.results_dir / f'timing_analysis_{self.run_timestamp}'}")
        print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="SSE Timing Analysis Test")
    parser.add_argument("--duration", type=int, default=DEFAULT_DURATION_MINUTES,
                        help=f"Test duration in minutes (default: {DEFAULT_DURATION_MINUTES})")
    parser.add_argument("--token", type=str, default=JWT_TOKEN,
                        help="JWT token for authentication")
    
    args = parser.parse_args()
    
    if not args.token:
        print("ERROR: JWT token required. Set ICEBERG_JWT_TOKEN env var or use --token")
        sys.exit(1)
    
    analyzer = SSETimingAnalyzer(
        jwt_token=args.token,
        duration_minutes=args.duration,
    )
    
    analyzer.run()


if __name__ == "__main__":
    main()
