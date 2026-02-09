#!/usr/bin/env python3
"""
Fast Stream Validation Test Script

This script connects to the Iceberg Fast Stream WebSocket endpoint
and logs all received messages for validation.

Usage:
    python test_fast_stream.py [--duration SECONDS] [--token JWT_TOKEN]

Evidence-based validation:
- Logs all WebSocket events with timestamps
- Records message types and counts
- Validates expected message format
- Outputs summary statistics
"""

import argparse
import json
import os
import sys
import time
import threading
from datetime import datetime
from collections import defaultdict
from typing import Optional, Dict, Any, List

import websocket
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
DEFAULT_DURATION = 60  # seconds
API_URL = os.getenv("ICEBERG_API_URL", "https://api.botbro.trade")
JWT_TOKEN = os.getenv("ICEBERG_JWT_TOKEN", "")
SYMBOLS = ["nifty", "banknifty", "sensex", "finnifty"]


class FastStreamValidator:
    """Validates the Fast Stream WebSocket connection."""
    
    def __init__(self, jwt_token: str, duration: int = DEFAULT_DURATION):
        self.jwt_token = jwt_token
        self.duration = duration
        self.ws: Optional[websocket.WebSocketApp] = None
        self.running = False
        self.start_time: Optional[float] = None
        
        # Statistics
        self.stats = {
            "connected": False,
            "connection_time": None,
            "messages_received": 0,
            "events_by_type": defaultdict(int),
            "symbols_seen": set(),
            "first_message_time": None,
            "last_message_time": None,
            "errors": [],
            "pings_received": 0,
            "pongs_sent": 0,
            "snapshots_received": 0,
            "ticks_received": 0,
            "option_chain_ltp_received": 0,
        }
        
        # Message samples for evidence
        self.message_samples: Dict[str, List[Dict]] = defaultdict(list)
        self.max_samples = 3  # Keep up to 3 samples per event type
        
    def _build_url(self) -> str:
        """Build WebSocket URL with token and symbols."""
        ws_url = API_URL.replace("https://", "wss://").replace("http://", "ws://")
        symbols_param = ",".join(SYMBOLS)
        return f"{ws_url}/v1/stream/fast?token={self.jwt_token}&symbols={symbols_param}"
    
    def _log(self, level: str, message: str, **kwargs):
        """Log with timestamp and structured data."""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        extra = " ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
        print(f"[{ts}] [{level}] {message} {extra}")
    
    def _on_open(self, ws):
        """Handle WebSocket connection open."""
        self.stats["connected"] = True
        self.stats["connection_time"] = time.time() - self.start_time
        self._log("INFO", "WebSocket CONNECTED", 
                  connection_time_ms=f"{self.stats['connection_time']*1000:.0f}")
    
    def _on_message(self, ws, message: str):
        """Handle incoming WebSocket message."""
        now = time.time()
        self.stats["messages_received"] += 1
        
        if self.stats["first_message_time"] is None:
            self.stats["first_message_time"] = now - self.start_time
        self.stats["last_message_time"] = now - self.start_time
        
        try:
            data = json.loads(message)
            event_type = data.get("event", "unknown")
            self.stats["events_by_type"][event_type] += 1
            
            # Store sample for evidence
            if len(self.message_samples[event_type]) < self.max_samples:
                self.message_samples[event_type].append(data)
            
            # Handle specific event types
            if event_type == "ping":
                self.stats["pings_received"] += 1
                self._handle_ping(ws)
                self._log("DEBUG", "PING received, sending PONG")
                
            elif event_type == "snapshot":
                self.stats["snapshots_received"] += 1
                symbols_in_snapshot = list(data.get("data", {}).keys())
                self.stats["symbols_seen"].update(symbols_in_snapshot)
                self._log("INFO", "SNAPSHOT received", 
                          symbols=symbols_in_snapshot,
                          ts=data.get("ts"))
                
            elif event_type == "tick":
                self.stats["ticks_received"] += 1
                tick_data = data.get("data", {})
                for symbol, tick in tick_data.items():
                    self.stats["symbols_seen"].add(symbol)
                    if isinstance(tick, dict):
                        self._log("DEBUG", f"TICK {symbol}", 
                                  ltp=tick.get("ltp"),
                                  change=tick.get("change"),
                                  change_pct=tick.get("change_pct"))
                
            elif event_type == "option_chain_ltp":
                self.stats["option_chain_ltp_received"] += 1
                symbol = data.get("symbol", "unknown")
                mode = data.get("mode", "unknown")
                strikes_data = data.get("data", {})
                strikes_count = len(strikes_data.get("strikes", []))
                self.stats["symbols_seen"].add(symbol)
                self._log("INFO", f"OPTION_CHAIN_LTP {symbol}/{mode}", 
                          strikes=strikes_count,
                          expiry=data.get("expiry"))
                
            elif event_type == "option_tick":
                symbol = data.get("symbol", "unknown")
                self.stats["symbols_seen"].add(symbol)
                self._log("DEBUG", f"OPTION_TICK {symbol}")
                
            else:
                self._log("WARN", f"Unknown event type: {event_type}", 
                          data_keys=list(data.keys()))
                
        except json.JSONDecodeError as e:
            self.stats["errors"].append(f"JSON decode error: {e}")
            self._log("ERROR", "Failed to parse message", 
                      error=str(e), 
                      message_preview=message[:100])
    
    def _handle_ping(self, ws):
        """Respond to ping with pong."""
        try:
            pong_message = json.dumps({"action": "pong"})
            ws.send(pong_message)
            self.stats["pongs_sent"] += 1
        except Exception as e:
            self.stats["errors"].append(f"Pong send error: {e}")
            self._log("ERROR", "Failed to send pong", error=str(e))
    
    def _on_error(self, ws, error):
        """Handle WebSocket error."""
        self.stats["errors"].append(str(error))
        self._log("ERROR", "WebSocket error", error=str(error))
    
    def _on_close(self, ws, close_status_code, close_msg):
        """Handle WebSocket close."""
        self._log("INFO", "WebSocket CLOSED", 
                  code=close_status_code, 
                  message=close_msg)
        self.running = False
    
    def run(self):
        """Run the validation test."""
        self._log("INFO", "=" * 60)
        self._log("INFO", "FAST STREAM VALIDATION TEST")
        self._log("INFO", "=" * 60)
        self._log("INFO", f"API URL: {API_URL}")
        self._log("INFO", f"Symbols: {SYMBOLS}")
        self._log("INFO", f"Duration: {self.duration} seconds")
        self._log("INFO", f"JWT Token: {self.jwt_token[:50]}...")
        self._log("INFO", "=" * 60)
        
        url = self._build_url()
        self._log("INFO", f"Connecting to: {url[:80]}...")
        
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
                time.sleep(0.5)
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
        self._log("INFO", "=" * 60)
        self._log("INFO", "VALIDATION SUMMARY")
        self._log("INFO", "=" * 60)
        
        print(f"\n{'='*60}")
        print("CONNECTION STATUS")
        print(f"{'='*60}")
        print(f"  Connected: {self.stats['connected']}")
        if self.stats['connection_time']:
            print(f"  Connection Time: {self.stats['connection_time']*1000:.0f}ms")
        
        print(f"\n{'='*60}")
        print("MESSAGE STATISTICS")
        print(f"{'='*60}")
        print(f"  Total Messages: {self.stats['messages_received']}")
        print(f"  Snapshots: {self.stats['snapshots_received']}")
        print(f"  Ticks: {self.stats['ticks_received']}")
        print(f"  Option Chain LTP: {self.stats['option_chain_ltp_received']}")
        print(f"  Pings Received: {self.stats['pings_received']}")
        print(f"  Pongs Sent: {self.stats['pongs_sent']}")
        
        print(f"\n{'='*60}")
        print("EVENTS BY TYPE")
        print(f"{'='*60}")
        for event_type, count in sorted(self.stats['events_by_type'].items()):
            print(f"  {event_type}: {count}")
        
        print(f"\n{'='*60}")
        print("SYMBOLS SEEN")
        print(f"{'='*60}")
        print(f"  {sorted(self.stats['symbols_seen'])}")
        
        if self.stats['first_message_time']:
            print(f"\n{'='*60}")
            print("TIMING")
            print(f"{'='*60}")
            print(f"  First Message: {self.stats['first_message_time']*1000:.0f}ms after connect")
            print(f"  Last Message: {self.stats['last_message_time']*1000:.0f}ms after connect")
        
        if self.stats['errors']:
            print(f"\n{'='*60}")
            print("ERRORS")
            print(f"{'='*60}")
            for error in self.stats['errors']:
                print(f"  - {error}")
        
        # Print message samples as evidence
        print(f"\n{'='*60}")
        print("MESSAGE SAMPLES (EVIDENCE)")
        print(f"{'='*60}")
        for event_type, samples in self.message_samples.items():
            print(f"\n--- {event_type} ---")
            for i, sample in enumerate(samples[:2]):  # Show max 2 samples
                print(f"Sample {i+1}:")
                print(json.dumps(sample, indent=2, default=str)[:500])
                if len(json.dumps(sample)) > 500:
                    print("  ... (truncated)")
        
        # Validation result
        print(f"\n{'='*60}")
        print("VALIDATION RESULT")
        print(f"{'='*60}")
        
        issues = []
        if not self.stats['connected']:
            issues.append("Failed to connect to WebSocket")
        if self.stats['snapshots_received'] == 0:
            issues.append("No snapshot received on connection")
        if self.stats['ticks_received'] == 0 and self.stats['option_chain_ltp_received'] == 0:
            issues.append("No tick or option_chain_ltp events received (market may be closed)")
        if len(self.stats['symbols_seen']) == 0:
            issues.append("No symbols seen in messages")
        if self.stats['errors']:
            issues.append(f"{len(self.stats['errors'])} errors occurred")
        
        if issues:
            print("  STATUS: ISSUES FOUND")
            for issue in issues:
                print(f"  - {issue}")
        else:
            print("  STATUS: PASS")
            print("  - WebSocket connected successfully")
            print("  - Snapshot received on connection")
            print(f"  - {self.stats['messages_received']} messages received")
            print(f"  - {len(self.stats['symbols_seen'])} symbols seen")


def main():
    parser = argparse.ArgumentParser(description="Fast Stream Validation Test")
    parser.add_argument("--duration", type=int, default=DEFAULT_DURATION,
                        help=f"Test duration in seconds (default: {DEFAULT_DURATION})")
    parser.add_argument("--token", type=str, default=JWT_TOKEN,
                        help="JWT token for authentication")
    args = parser.parse_args()
    
    if not args.token:
        print("ERROR: No JWT token provided. Set ICEBERG_JWT_TOKEN env var or use --token")
        sys.exit(1)
    
    validator = FastStreamValidator(jwt_token=args.token, duration=args.duration)
    stats = validator.run()
    
    # Exit with error code if validation failed
    if not stats['connected'] or stats['errors']:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
