#!/usr/bin/env python3
"""Debug script to fetch and inspect bootstrap data."""

import asyncio
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

# Now import after path is set
from config import get_settings


async def main():
    """Fetch bootstrap and print structure."""
    settings = get_settings()
    
    # Check if JWT token is configured
    if not settings.iceberg_jwt_token:
        print("ERROR: No JWT token configured in .env")
        print("Please add ICEBERG_JWT_TOKEN=<your_token> to .env file")
        return
    
    # Import httpx here to make request directly
    import httpx
    
    print("Fetching bootstrap data...")
    print(f"API URL: {settings.iceberg_api_url}")
    print(f"Token: {settings.iceberg_jwt_token[:20]}...")
    print()
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{settings.iceberg_api_url}/v1/dashboard/bootstrap",
                params={
                    "symbols": "nifty,banknifty,sensex,finnifty",
                    "include_candles": "true",
                    "include_option_chain": "true",
                    "include_indicators": "true",
                },
                headers={"Authorization": f"Bearer {settings.iceberg_jwt_token}"},
            )
            
            response.raise_for_status()
            result = response.json()
            
            result = response.json()
        
        if not result.get("ok"):
            print("ERROR: Bootstrap failed")
            print(json.dumps(result, indent=2))
            return
        
        data = result.get("data", {})
        meta = result.get("meta", {})
        
        print("=== META ===")
        print(json.dumps(meta, indent=2))
        print()
        
        # Check each symbol
        for symbol in ["nifty", "banknifty", "sensex", "finnifty"]:
            print(f"\n=== {symbol.upper()} ===")
            symbol_data = data.get(symbol, {})
            
            if not symbol_data:
                print(f"  No data for {symbol}")
                continue
            
            # FIX-023: Check symbol-level candles_5m
            candles = symbol_data.get("candles_5m", {})
            if candles:
                ts_arr = candles.get("ts", [])
                print(f"  candles_5m (symbol-level): {len(ts_arr)} candles")
                if ts_arr:
                    print(f"    First ts: {ts_arr[0]}")
                    print(f"    Last ts: {ts_arr[-1]}")
            else:
                print(f"  candles_5m (symbol-level): NOT PRESENT")
            
            # FIX-023: Check symbol-level technical_indicators
            tech = symbol_data.get("technical_indicators", {})
            if tech:
                print(f"  technical_indicators keys: {list(tech.keys())}")
                ts_arr = tech.get("ts", [])
                ema_9_arr = tech.get("ema_9", [])
                ema_21_arr = tech.get("ema_21", [])
                rsi_arr = tech.get("rsi", [])
                adr_arr = tech.get("adr", [])
                print(f"    ts count: {len(ts_arr)}")
                print(f"    ema_9 count: {len(ema_9_arr)}")
                print(f"    ema_21 count: {len(ema_21_arr)}")
                print(f"    rsi count: {len(rsi_arr)}")
                print(f"    adr count: {len(adr_arr)}")
                if ema_9_arr:
                    print(f"    ✓ EMA data found at symbol level")
                    print(f"      ema_9 sample: {ema_9_arr[:3]}")
                    print(f"      ema_21 sample: {ema_21_arr[:3]}")
            else:
                print(f"  technical_indicators: NOT PRESENT")
            
            for mode in ["current", "positional"]:
                print(f"\n  Mode: {mode}")
                mode_data = symbol_data.get(mode, {})
                
                if not mode_data:
                    print(f"    No data for {mode}")
                    continue
                
                # Check indicator_chart
                indicator_chart = mode_data.get("indicator_chart", {})
                if indicator_chart:
                    series = indicator_chart.get("series", {})
                    print(f"    indicator_chart.series keys: {list(series.keys())}")
                    
                    # FIX-023: EMA data is now at symbol level in technical_indicators
                    # indicator_chart.series should only have: ts, skew, pcr
                    
                    if series:
                        ts_arr = series.get("ts", [])
                        skew_arr = series.get("skew", [])
                        pcr_arr = series.get("pcr", [])
                        print(f"      ts count: {len(ts_arr)}")
                        print(f"      skew count: {len(skew_arr)}")
                        print(f"      pcr count: {len(pcr_arr)}")
                        if ts_arr:
                            print(f"      First ts: {ts_arr[0]}")
                            print(f"      Last ts: {ts_arr[-1]}")
                else:
                    print("    No indicator_chart")
                
                # Check option_chain
                option_chain = mode_data.get("option_chain", {})
                if option_chain:
                    print(f"    option_chain keys: {list(option_chain.keys())}")
                    print(f"      expiry: {option_chain.get('expiry')}")
                    print(f"      underlying: {option_chain.get('underlying')}")
                    print(f"      ts: {option_chain.get('ts')}")
                    
                    columns = option_chain.get("columns", {})
                    if columns:
                        print(f"      columns keys: {list(columns.keys())}")
                        strikes = columns.get("strike", [])
                        print(f"      strike count: {len(strikes)}")
                        if strikes:
                            print(f"      First 3 strikes: {strikes[:3]}")
                else:
                    print("    No option_chain")
                
                # Check candles_5m at mode level (legacy, pre-FIX-023)
                if mode == "current":
                    candles = mode_data.get("candles_5m", {})
                    if candles:
                        ts_arr = candles.get("ts", [])
                        print(f"    candles_5m (mode-level, legacy): {len(ts_arr)} candles")
                    # Note: FIX-023 moves candles to symbol level
        
        # Save full response for inspection
        output_file = Path(__file__).parent / "bootstrap_debug.json"
        with open(output_file, "w") as f:
            json.dump(result, f, indent=2)
        print(f"\n\nFull response saved to: {output_file}")
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
