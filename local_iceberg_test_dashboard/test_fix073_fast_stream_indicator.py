#!/usr/bin/env python3
"""
FIX-073 Fast Stream Indicator Update Validation Test

This script validates that indicator_update events are delivered via WebSocket
fast stream within ~6-10 seconds of candle close (vs ~67 seconds via SSE).

Expected behavior per FIX-073:
- T+0.0s: Candle closes (e.g., 15:05:00 IST)
- T+5.0s: Data Handler calculates indicators, writes to PostgreSQL
- T+5.1s: Data Handler publishes to Redis `iceberg:indicator_update` channel
- T+5.2s: API Layer receives via Redis subscriber
- T+5.3s: API Layer broadcasts `indicator_update` to Fast Stream WebSocket clients
- T+~6s: Client receives indicator_update (TARGET: <10 seconds)

Event format (FIX-073_2):
{
    "event": "indicator_update",
    "ts": "2026-02-25T09:35:05.123456+00:00",
    "symbol": "nifty",
    "mode": "current",
    "data": {
        "skew": 0.15,
        "pcr": 1.23,
        "signal": "BUY",
        "candle_ts": "2026-02-25T09:30:00+00:00"
    }
}

Usage:
    python test_fix073_fast_stream_indicator.py --duration 600
"""

import argparse
import json
import os
import sys
import time
import threading
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict

import websocket
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
DEFAULT_DURATION = 600  # 10 minutes
API_URL = os.getenv("ICEBERG_API_URL", "https://api.botbro.trade")
JWT_TOKEN = os.getenv("ICEBERG_JWT_TOKEN", "")
SYMBOLS = ["nifty", "banknifty", "sensex", "finnifty"]

# IST timezone
IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class IndicatorUpdateEvent:
    """Record of an indicator_update WebSocket event."""
    received_at: float  # Unix timestamp
    received_at_iso: str
    symbol: str
    mode: str
    skew: Optional[float]
    pcr: Optional[float]
    signal: Optional[str]
    candle_ts: Optional[str]
    event_ts: Optional[str]  # ts field from event
    delay_from_candle_close_seconds: Optional[float]


class FIX073Validator:
    """Validates FIX-073 Fast Stream Indicator Update implementation."""
    
    def __init__(self, jwt_token: str, duration: int = DEFAULT_DURATION):
        self.jwt_token = jwt_token
        self.duration = duration
        self.ws: Optional[websocket.WebSocketApp] = None
        self.running = False
        self.start_time: Optional[float] = None
        
        # Statistics
        self.stats = {
            "connected": False,
            "connection_time_ms": None,
            "messages_received": 0,
            "events_by_type": defaultdict(int),
            "symbols_seen": set(),
            "errors": [],
            "pings_received": 0,
            "pongs_sent": 0,
            "snapshots_received": 0,
            "ticks_received": 0,
            "indicator_updates_received": 0,
        }
        
        # Indicator update records
        self.indicator_updates: List[IndicatorUpdateEvent] = []
        
        # Raw message samples
        self.message_samples: Dict[str, List[Dict]] = defaultdict(list)
        self.max_samples = 5
        
    def _build_url(self) -> str:
        """Build WebSocket URL with token and symbols."""
        ws_url = API_URL.replace("https://", "wss://").replace("http://", "ws://")
        symbols_param = ",".join(SYMBOLS)
        return f"{ws_url}/v1/stream/fast?token={self.jwt_token}&symbols={symbols_param}"
    
    def _log(self, level: str, message: str, **kwargs):
        """Log with timestamp and structured data."""
        ts = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        extra = " ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
        print(f"[{ts}] [{level}] {message} {extra}")
    
    def _parse_iso_timestamp(self, ts_str: Optional[str]) -> Optional[datetime]:
        """Parse ISO timestamp string to datetime."""
        if not ts_str:
            return None
        try:
            if ts_str.endswith('Z'):
                ts_str = ts_str[:-1] + '+00:00'
            return datetime.fromisoformat(ts_str)
        except (ValueError, TypeError):
            return None
    
    def _calculate_delay_from_candle_close(
        self, 
        received_at: float, 
        candle_ts: Optional[str]
    ) -> Optional[float]:
        """
        Calculate delay in seconds from candle close to event receipt.
        Candle close = candle_ts + 5 minutes
        """
        candle_dt = self._parse_iso_timestamp(candle_ts)
        if not candle_dt:
            return None
        
        close_dt = candle_dt + timedelta(minutes=5)
        received_dt = datetime.fromtimestamp(received_at, tz=timezone.utc)
        delay = (received_dt - close_dt).total_seconds()
        return delay
    
    def _on_open(self, ws):
        """Handle WebSocket connection open."""
        self.stats["connected"] = True
        self.stats["connection_time_ms"] = (time.time() - self.start_time) * 1000
        self._log("INFO", "WebSocket CONNECTED", 
                  connection_time_ms=f"{self.stats['connection_time_ms']:.0f}")
    
    def _on_message(self, ws, message: str):
        """Handle incoming WebSocket message."""
        received_at = time.time()
        received_at_iso = datetime.now(IST).isoformat()
        self.stats["messages_received"] += 1
        
        try:
            data = json.loads(message)
            
            # FIX-073 uses "event_type", existing events use "event"
            event_type = data.get("event") or data.get("event_type", "unknown")
            self.stats["events_by_type"][event_type] += 1
            
            # Store sample
            if len(self.message_samples[event_type]) < self.max_samples:
                self.message_samples[event_type].append(data)
            
            # Handle specific event types
            if event_type == "ping":
                self.stats["pings_received"] += 1
                self._handle_ping(ws)
                
            elif event_type == "snapshot":
                self.stats["snapshots_received"] += 1
                symbols_in_snapshot = list(data.get("data", {}).keys())
                self.stats["symbols_seen"].update(symbols_in_snapshot)
                self._log("INFO", "SNAPSHOT received", symbols=symbols_in_snapshot)
                
            elif event_type == "tick":
                self.stats["ticks_received"] += 1
                tick_data = data.get("data", {})
                for symbol in tick_data.keys():
                    self.stats["symbols_seen"].add(symbol.lower())
                # Log every 100th tick
                if self.stats["ticks_received"] % 100 == 0:
                    self._log("DEBUG", f"Tick #{self.stats['ticks_received']}")
                
            elif event_type == "indicator_update":
                # FIX-073: This is what we're testing!
                self.stats["indicator_updates_received"] += 1
                self._handle_indicator_update(received_at, received_at_iso, data)
                
            elif event_type == "option_chain_ltp":
                symbol = data.get("symbol", "unknown")
                self.stats["symbols_seen"].add(symbol.lower())
                
        except json.JSONDecodeError as e:
            self.stats["errors"].append(f"JSON decode error: {e}")
            self._log("ERROR", "Failed to parse message", error=str(e))
    
    def _handle_indicator_update(self, received_at: float, received_at_iso: str, data: Dict[str, Any]):
        """Handle indicator_update event - the core of FIX-073 validation."""
        # FIX-073_2: Extract from data wrapper if present (backward compat with flat structure)
        indicator_data = data.get("data", data)
        symbol = data.get("symbol", "").lower()
        mode = data.get("mode", "")
        skew = indicator_data.get("skew")
        pcr = indicator_data.get("pcr")
        signal = indicator_data.get("signal")
        candle_ts = indicator_data.get("candle_ts")
        event_ts = data.get("ts")
        
        # Calculate delay from candle close
        delay = self._calculate_delay_from_candle_close(received_at, candle_ts)
        
        record = IndicatorUpdateEvent(
            received_at=received_at,
            received_at_iso=received_at_iso,
            symbol=symbol,
            mode=mode,
            skew=skew,
            pcr=pcr,
            signal=signal,
            candle_ts=candle_ts,
            event_ts=event_ts,
            delay_from_candle_close_seconds=delay,
        )
        self.indicator_updates.append(record)
        self.stats["symbols_seen"].add(symbol)
        
        delay_str = f"{delay:.2f}s" if delay is not None else "N/A"
        
        # This is the key validation - log prominently
        self._log("INFO", "=" * 50)
        self._log("INFO", f"🎯 INDICATOR_UPDATE RECEIVED (FIX-073)")
        self._log("INFO", f"   Symbol: {symbol}, Mode: {mode}")
        self._log("INFO", f"   Skew: {skew}, PCR: {pcr}, Signal: {signal}")
        self._log("INFO", f"   Candle TS: {candle_ts}")
        self._log("INFO", f"   Delay from candle close: {delay_str}")
        if delay is not None:
            if delay < 10:
                self._log("INFO", f"   ✅ PASS: Delay < 10 seconds (target met)")
            else:
                self._log("WARN", f"   ⚠️ SLOW: Delay >= 10 seconds")
        self._log("INFO", "=" * 50)
    
    def _handle_ping(self, ws):
        """Respond to ping with pong."""
        try:
            pong_message = json.dumps({"action": "pong"})
            ws.send(pong_message)
            self.stats["pongs_sent"] += 1
        except Exception as e:
            self.stats["errors"].append(f"Pong send error: {e}")
    
    def _on_error(self, ws, error):
        """Handle WebSocket error."""
        self.stats["errors"].append(str(error))
        self._log("ERROR", "WebSocket error", error=str(error))
    
    def _on_close(self, ws, close_status_code, close_msg):
        """Handle WebSocket close."""
        self._log("INFO", "WebSocket CLOSED", code=close_status_code, message=close_msg)
        self.running = False
    
    def run(self):
        """Run the validation test."""
        now_ist = datetime.now(IST)
        
        self._log("INFO", "=" * 70)
        self._log("INFO", "FIX-073 FAST STREAM INDICATOR UPDATE VALIDATION")
        self._log("INFO", "=" * 70)
        self._log("INFO", f"API URL: {API_URL}")
        self._log("INFO", f"Symbols: {SYMBOLS}")
        self._log("INFO", f"Duration: {self.duration} seconds ({self.duration // 60} minutes)")
        self._log("INFO", f"Current IST: {now_ist.strftime('%H:%M:%S')}")
        
        # Calculate next candle closes
        minute = now_ist.minute
        next_5min = ((minute // 5) + 1) * 5
        if next_5min >= 60:
            next_candle = now_ist.replace(hour=now_ist.hour + 1, minute=0, second=0)
        else:
            next_candle = now_ist.replace(minute=next_5min, second=0)
        
        self._log("INFO", f"Next candle close: {next_candle.strftime('%H:%M:%S')} IST")
        self._log("INFO", f"Expected indicator_update: ~{(next_candle + timedelta(seconds=6)).strftime('%H:%M:%S')} IST")
        self._log("INFO", "=" * 70)
        self._log("INFO", "Waiting for indicator_update events...")
        self._log("INFO", "(Events should arrive ~6 seconds after each 5-min candle close)")
        self._log("INFO", "=" * 70)
        
        url = self._build_url()
        self.start_time = time.time()
        self.running = True
        
        self.ws = websocket.WebSocketApp(
            url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        
        # Run WebSocket in a thread
        ws_thread = threading.Thread(target=self.ws.run_forever, kwargs={"ping_interval": 0})
        ws_thread.daemon = True
        ws_thread.start()
        
        # Wait for duration or until stopped
        try:
            end_time = time.time() + self.duration
            while self.running and time.time() < end_time:
                remaining = int(end_time - time.time())
                if remaining % 60 == 0 and remaining > 0:
                    self._log("INFO", f"Time remaining: {remaining // 60} minutes",
                              indicator_updates=len(self.indicator_updates),
                              ticks=self.stats["ticks_received"])
                time.sleep(1)
        except KeyboardInterrupt:
            self._log("INFO", "Interrupted by user")
        
        # Close connection
        if self.ws:
            self.ws.close()
        
        # Print summary
        self._print_summary()
        
        return self.stats
    
    def _print_summary(self):
        """Print validation summary."""
        print(f"\n{'='*70}")
        print("FIX-073 VALIDATION SUMMARY")
        print(f"{'='*70}")
        
        print(f"\nCONNECTION STATUS")
        print(f"  Connected: {self.stats['connected']}")
        if self.stats['connection_time_ms']:
            print(f"  Connection Time: {self.stats['connection_time_ms']:.0f}ms")
        
        print(f"\nMESSAGE STATISTICS")
        print(f"  Total Messages: {self.stats['messages_received']}")
        print(f"  Snapshots: {self.stats['snapshots_received']}")
        print(f"  Ticks: {self.stats['ticks_received']}")
        print(f"  Indicator Updates: {self.stats['indicator_updates_received']}")
        print(f"  Pings/Pongs: {self.stats['pings_received']}/{self.stats['pongs_sent']}")
        
        print(f"\nEVENTS BY TYPE")
        for event_type, count in sorted(self.stats['events_by_type'].items()):
            print(f"  {event_type}: {count}")
        
        print(f"\nSYMBOLS SEEN")
        print(f"  {sorted(self.stats['symbols_seen'])}")
        
        # FIX-073 specific validation
        print(f"\n{'='*70}")
        print("FIX-073 INDICATOR UPDATE ANALYSIS")
        print(f"{'='*70}")
        
        if not self.indicator_updates:
            print("  ⚠️ NO indicator_update events received!")
            print("  Possible reasons:")
            print("    - Market is closed (no indicator calculations)")
            print("    - Test duration too short (need to wait for 5-min candle close)")
            print("    - FIX-073 not deployed or not working")
        else:
            print(f"  Total indicator_update events: {len(self.indicator_updates)}")
            
            # Analyze delays
            delays = [r.delay_from_candle_close_seconds for r in self.indicator_updates 
                     if r.delay_from_candle_close_seconds is not None]
            
            if delays:
                import statistics
                print(f"\n  DELAY STATISTICS (from candle close):")
                print(f"    Min: {min(delays):.2f}s")
                print(f"    Max: {max(delays):.2f}s")
                print(f"    Mean: {statistics.mean(delays):.2f}s")
                print(f"    Median: {statistics.median(delays):.2f}s")
                
                # Check against target
                under_10s = sum(1 for d in delays if d < 10)
                print(f"\n  TARGET VALIDATION (<10 seconds):")
                print(f"    Events under 10s: {under_10s}/{len(delays)} ({100*under_10s/len(delays):.0f}%)")
                
                if all(d < 10 for d in delays):
                    print(f"    ✅ PASS: All events delivered within target")
                else:
                    print(f"    ⚠️ PARTIAL: Some events exceeded target")
            
            # Show individual events
            print(f"\n  INDIVIDUAL EVENTS:")
            for i, record in enumerate(self.indicator_updates):
                delay_str = f"{record.delay_from_candle_close_seconds:.2f}s" if record.delay_from_candle_close_seconds else "N/A"
                status = "✅" if record.delay_from_candle_close_seconds and record.delay_from_candle_close_seconds < 10 else "⚠️"
                print(f"    {i+1}. {record.symbol}/{record.mode} @ {record.received_at_iso}")
                print(f"       Candle: {record.candle_ts}, Delay: {delay_str} {status}")
                print(f"       Skew: {record.skew}, PCR: {record.pcr}, Signal: {record.signal}")
        
        # Show message samples
        if "indicator_update" in self.message_samples:
            print(f"\n{'='*70}")
            print("INDICATOR_UPDATE MESSAGE SAMPLES")
            print(f"{'='*70}")
            for i, sample in enumerate(self.message_samples["indicator_update"][:3]):
                print(f"\nSample {i+1}:")
                print(json.dumps(sample, indent=2, default=str))
        
        if self.stats['errors']:
            print(f"\n{'='*70}")
            print("ERRORS")
            print(f"{'='*70}")
            for error in self.stats['errors']:
                print(f"  - {error}")
        
        # Final verdict
        print(f"\n{'='*70}")
        print("FINAL VERDICT")
        print(f"{'='*70}")
        
        if not self.stats['connected']:
            print("  ❌ FAIL: Could not connect to WebSocket")
        elif not self.indicator_updates:
            print("  ⚠️ INCONCLUSIVE: No indicator_update events received")
            print("     (May need longer test duration or market hours)")
        else:
            delays = [r.delay_from_candle_close_seconds for r in self.indicator_updates 
                     if r.delay_from_candle_close_seconds is not None]
            if delays and all(d < 10 for d in delays):
                print("  ✅ PASS: FIX-073 working correctly")
                print(f"     All {len(delays)} indicator updates delivered within 10 seconds")
            elif delays:
                avg_delay = sum(delays) / len(delays)
                print(f"  ⚠️ PARTIAL: Average delay {avg_delay:.2f}s")
            else:
                print("  ⚠️ INCONCLUSIVE: Could not calculate delays (missing candle_ts)")


def main():
    parser = argparse.ArgumentParser(description="FIX-073 Fast Stream Indicator Update Validation")
    parser.add_argument("--duration", type=int, default=DEFAULT_DURATION,
                        help=f"Test duration in seconds (default: {DEFAULT_DURATION})")
    parser.add_argument("--token", type=str, default=JWT_TOKEN,
                        help="JWT token for authentication")
    args = parser.parse_args()
    
    if not args.token:
        print("ERROR: No JWT token provided. Set ICEBERG_JWT_TOKEN env var or use --token")
        sys.exit(1)
    
    validator = FIX073Validator(jwt_token=args.token, duration=args.duration)
    stats = validator.run()
    
    # Exit with appropriate code
    if not stats['connected']:
        sys.exit(1)
    elif stats['indicator_updates_received'] == 0:
        sys.exit(2)  # Inconclusive
    sys.exit(0)


if __name__ == "__main__":
    main()
