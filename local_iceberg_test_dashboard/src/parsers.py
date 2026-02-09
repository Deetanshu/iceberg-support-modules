# Iceberg Test Dashboard - Data Parsers
"""
Parsers for bootstrap responses and SSE events.

Handles columnar data format parsing and date filtering.
Requirements: 5.4, 5.5, 12.3, 12.4, 12.5
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import pytz

from .models import (
    Candle,
    IndicatorData,
    OptionChainData,
    OptionStrike,
    SymbolData,
    VALID_SYMBOLS,
    VALID_MODES,
)

IST = pytz.timezone("Asia/Kolkata")


def derive_signal_from_skew(skew: Optional[float]) -> str:
    """
    Derive signal from skew value using standard thresholds.
    
    Thresholds (from product.md):
    - ≥0.6 → STRONG_BUY
    - >0.3 → BUY
    - ≤-0.6 → STRONG_SELL
    - <-0.3 → SELL
    - else → NEUTRAL
    
    Args:
        skew: Skew value (can be None)
    
    Returns:
        Signal string
    """
    if skew is None:
        return "NEUTRAL"
    if skew >= 0.6:
        return "STRONG_BUY"
    if skew > 0.3:
        return "BUY"
    if skew <= -0.6:
        return "STRONG_SELL"
    if skew < -0.3:
        return "SELL"
    return "NEUTRAL"


def parse_timestamp(ts_value: Any) -> datetime:
    """
    Parse a timestamp value into a datetime object with IST timezone.

    Handles multiple formats:
    - ISO format strings (with or without timezone)
    - Unix timestamps (seconds or milliseconds)
    - Already datetime objects

    Args:
        ts_value: Timestamp in various formats

    Returns:
        datetime object with IST timezone
    """
    if ts_value is None:
        return datetime.now(IST)

    if isinstance(ts_value, datetime):
        if ts_value.tzinfo is None:
            return IST.localize(ts_value)
        return ts_value.astimezone(IST)

    if isinstance(ts_value, (int, float)):
        # Handle Unix timestamps (seconds or milliseconds)
        if ts_value > 1e12:  # Milliseconds
            ts_value = ts_value / 1000
        return datetime.fromtimestamp(ts_value, tz=IST)

    if isinstance(ts_value, str):
        # Try ISO format first
        try:
            dt = datetime.fromisoformat(ts_value.replace("Z", "+00:00"))
            return dt.astimezone(IST)
        except ValueError:
            pass

        # Try common formats
        for fmt in [
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S.%f",
        ]:
            try:
                dt = datetime.strptime(ts_value, fmt)
                return IST.localize(dt)
            except ValueError:
                continue

    # Fallback to current time
    return datetime.now(IST)


def parse_columnar_candles(candles_raw: Dict[str, List]) -> List[Candle]:
    """
    Parse columnar candle data into Candle objects.

    Requirement 5.5: Parse columnar data format (ts[], open[], high[], low[], close[], volume[])

    Args:
        candles_raw: Dict with parallel arrays: ts[], open[], high[], low[], close[], volume[]

    Returns:
        List of Candle objects
    """
    if not candles_raw:
        return []

    ts_list = candles_raw.get("ts", [])
    open_list = candles_raw.get("open", [])
    high_list = candles_raw.get("high", [])
    low_list = candles_raw.get("low", [])
    close_list = candles_raw.get("close", [])
    volume_list = candles_raw.get("volume", [])

    if not ts_list:
        return []

    candles = []
    for i in range(len(ts_list)):
        try:
            candle = Candle(
                ts=parse_timestamp(ts_list[i]),
                open=float(open_list[i]) if i < len(open_list) else 0.0,
                high=float(high_list[i]) if i < len(high_list) else 0.0,
                low=float(low_list[i]) if i < len(low_list) else 0.0,
                close=float(close_list[i]) if i < len(close_list) else 0.0,
                volume=int(volume_list[i]) if i < len(volume_list) else 0,
            )
            candles.append(candle)
        except (ValueError, TypeError, IndexError):
            # Skip malformed entries
            continue

    return candles


def candles_to_columnar(candles: List[Candle]) -> Dict[str, List]:
    """
    Convert Candle objects back to columnar format.

    Property 5: Columnar Data Parsing Round-Trip support.

    Args:
        candles: List of Candle objects

    Returns:
        Dict with parallel arrays: ts[], open[], high[], low[], close[], volume[]
    """
    if not candles:
        return {"ts": [], "open": [], "high": [], "low": [], "close": [], "volume": []}

    return {
        "ts": [c.ts.isoformat() if c.ts else None for c in candles],
        "open": [c.open for c in candles],
        "high": [c.high for c in candles],
        "low": [c.low for c in candles],
        "close": [c.close for c in candles],
        "volume": [c.volume for c in candles],
    }


def filter_candles_to_today(candles: List[Candle], reference_date: Optional[datetime] = None) -> List[Candle]:
    """
    Filter candles to only include those from the current date.

    Requirement 5.4: Filter bootstrap candle data to current date only.

    Property 4: Bootstrap Candle Date Filtering - after filtering, all candles
    SHALL have timestamps with dates equal to the current date (today in IST).

    Args:
        candles: List of Candle objects to filter
        reference_date: Optional reference date (defaults to today in IST)

    Returns:
        List of Candle objects from today only
    """
    if reference_date is None:
        today = datetime.now(IST).date()
    else:
        today = reference_date.date() if isinstance(reference_date, datetime) else reference_date

    return [c for c in candles if c.ts and c.ts.date() == today]


def parse_columnar_option_chain(oc_raw: Dict[str, Any]) -> Optional[OptionChainData]:
    """
    Parse columnar option chain data into OptionChainData object.

    Requirement 5.5: Parse columnar option chain data.

    Args:
        oc_raw: Dict with option chain data including columns dict

    Returns:
        OptionChainData object or None if invalid
    """
    if not oc_raw:
        return None

    columns = oc_raw.get("columns", {})
    if not columns:
        return None

    strike_list = columns.get("strike", [])
    if not strike_list:
        return None

    call_oi_list = columns.get("call_oi", [])
    put_oi_list = columns.get("put_oi", [])
    call_coi_list = columns.get("call_coi", [])
    put_coi_list = columns.get("put_coi", [])
    skew_list = columns.get("skew", columns.get("strike_skew", []))
    signal_list = columns.get("signal", [])

    strikes = []
    for i in range(len(strike_list)):
        try:
            skew_val = float(skew_list[i]) if i < len(skew_list) and skew_list[i] is not None else None
            # Use signal from API if available, otherwise derive from skew
            signal_val = signal_list[i] if i < len(signal_list) and signal_list[i] else derive_signal_from_skew(skew_val)
            
            strike = OptionStrike(
                strike=float(strike_list[i]),
                call_oi=int(call_oi_list[i]) if i < len(call_oi_list) else 0,
                put_oi=int(put_oi_list[i]) if i < len(put_oi_list) else 0,
                call_coi=int(call_coi_list[i]) if i < len(call_coi_list) and call_coi_list[i] is not None else None,
                put_coi=int(put_coi_list[i]) if i < len(put_coi_list) and put_coi_list[i] is not None else None,
                strike_skew=skew_val,
                call_ltp=None,
                put_ltp=None,
                signal=signal_val,
            )
            strikes.append(strike)
        except (ValueError, TypeError, IndexError):
            continue

    return OptionChainData(
        expiry=oc_raw.get("expiry", ""),
        underlying=float(oc_raw.get("underlying", 0.0)),
        strikes=strikes,
        ts=parse_timestamp(oc_raw.get("ts")),
    )


def parse_indicator_series(indicator_raw: Dict[str, Any]) -> Optional[IndicatorData]:
    """
    Parse indicator data from bootstrap response.

    Args:
        indicator_raw: Dict with indicator values

    Returns:
        IndicatorData object or None if invalid
    """
    if not indicator_raw:
        return None

    # Convert adr to float if it's a string (API may return string)
    adr_raw = indicator_raw.get("adr")
    adr_value = float(adr_raw) if adr_raw is not None else None

    return IndicatorData(
        skew=indicator_raw.get("skew"),
        raw_skew=indicator_raw.get("raw_skew"),
        pcr=indicator_raw.get("pcr"),
        adr=adr_value,
        signal=indicator_raw.get("signal", "NEUTRAL"),
        skew_confidence=float(indicator_raw.get("skew_confidence", 0.0)),
        rsi=indicator_raw.get("rsi"),
        ema_5=indicator_raw.get("ema_5"),  # Legacy field
        ema_9=indicator_raw.get("ema_9"),  # FIX-023: correct column name
        ema_13=indicator_raw.get("ema_13"),
        ema_21=indicator_raw.get("ema_21"),
        ema_50=indicator_raw.get("ema_50"),
        bb_upper=indicator_raw.get("bb_upper"),
        bb_middle=indicator_raw.get("bb_middle"),
        bb_lower=indicator_raw.get("bb_lower"),
        vwap=indicator_raw.get("vwap"),
        pivot_point=indicator_raw.get("pivot_point"),
        ts=parse_timestamp(indicator_raw.get("ts")),
    )


def parse_response_meta(meta: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse response meta fields from API response.
    
    FIX-043: Added market info fields to meta.
    
    Args:
        meta: Meta dict from API response
        
    Returns:
        Dict with parsed meta fields:
        {
            "request_id": str,
            "server_time": datetime,
            "cache_stale": bool,
            "market_state": str,
            "is_trading_day": bool | None,
            "holiday_name": str | None,
            "previous_trading_day": str | None,
        }
    """
    if not meta:
        return {
            "request_id": None,
            "server_time": None,
            "cache_stale": False,
            "market_state": "UNKNOWN",
            "is_trading_day": None,
            "holiday_name": None,
            "previous_trading_day": None,
        }
    
    return {
        "request_id": meta.get("request_id"),
        "server_time": parse_timestamp(meta.get("server_time")) if meta.get("server_time") else None,
        "cache_stale": meta.get("cache_stale", False),
        "market_state": meta.get("market_state", "UNKNOWN"),
        "is_trading_day": meta.get("is_trading_day"),
        "holiday_name": meta.get("holiday_name"),
        "previous_trading_day": meta.get("previous_trading_day"),
    }



def parse_bootstrap_response(
    response: Dict[str, Any],
    filter_to_today: bool = True,
) -> Dict[str, Dict[str, SymbolData]]:
    """
    Parse bootstrap API response into structured data.

    Requirement 5.4: Filter bootstrap candle data to current date only.
    Requirement 5.5: Parse columnar data format.
    
    FIX-023 (2026-01-21): Bootstrap response structure changed:
    - candles_5m is now at symbol level (sibling of current/positional)
    - technical_indicators is at symbol level with ts, rsi, ema_9, ema_21, adr
    - indicator_chart.series contains ONLY mode-specific data: ts, skew, pcr

    Args:
        response: Bootstrap API response dict
        filter_to_today: Whether to filter candles to current date only

    Returns:
        Dict mapping symbol -> mode -> SymbolData
    """
    result: Dict[str, Dict[str, SymbolData]] = {}
    data = response.get("data", {})

    if not data:
        return result

    for symbol in VALID_SYMBOLS:
        if symbol not in data:
            continue

        result[symbol] = {}
        symbol_data = data[symbol]

        # FIX-023: Parse symbol-level candles_5m (new location)
        symbol_candles_raw = symbol_data.get("candles_5m", {})
        symbol_candles = parse_columnar_candles(symbol_candles_raw)
        if filter_to_today and symbol_candles:
            symbol_candles = filter_candles_to_today(symbol_candles)

        # FIX-023: Parse symbol-level technical_indicators
        tech_indicators_raw = symbol_data.get("technical_indicators", {})

        for mode in VALID_MODES:
            mode_data = symbol_data.get(mode, {})
            if not mode_data:
                continue

            # FIX-023: Try symbol-level candles first, then fall back to mode-level (legacy)
            if symbol_candles:
                candles = symbol_candles
            else:
                # Legacy: candles at mode level (pre-FIX-023)
                candles_raw = mode_data.get("candles_5m", mode_data.get("candles", {}))
                candles = parse_columnar_candles(candles_raw)
                if filter_to_today and candles:
                    candles = filter_candles_to_today(candles)

            # Parse option chain from columnar format
            oc_raw = mode_data.get("option_chain", {})
            option_chain = parse_columnar_option_chain(oc_raw)

            # Parse indicators from indicator_chart (mode-specific: skew, pcr)
            indicator_chart = mode_data.get("indicator_chart", {})
            series = indicator_chart.get("series", {})
            
            # Build indicator data combining mode-specific (skew, pcr) and symbol-level (ema, rsi, adr)
            indicator_data = IndicatorData()
            
            # Mode-specific indicators from indicator_chart.series
            if series:
                # Get latest values from series arrays
                skew_arr = series.get("skew", [])
                pcr_arr = series.get("pcr", [])
                ts_arr = series.get("ts", [])
                
                if skew_arr:
                    indicator_data.skew = skew_arr[-1] if skew_arr[-1] is not None else None
                if pcr_arr:
                    indicator_data.pcr = pcr_arr[-1] if pcr_arr[-1] is not None else None
                if ts_arr:
                    indicator_data.ts = parse_timestamp(ts_arr[-1])
            
            # FIX-023: Symbol-level technical indicators (ema_9, ema_21, rsi, adr)
            if tech_indicators_raw:
                ema_9_arr = tech_indicators_raw.get("ema_9", [])
                ema_21_arr = tech_indicators_raw.get("ema_21", [])
                rsi_arr = tech_indicators_raw.get("rsi", [])
                adr_arr = tech_indicators_raw.get("adr", [])
                
                if ema_9_arr:
                    indicator_data.ema_9 = ema_9_arr[-1] if ema_9_arr[-1] is not None else None
                    indicator_data.ema_5 = indicator_data.ema_9  # Legacy compatibility
                if ema_21_arr:
                    indicator_data.ema_21 = ema_21_arr[-1] if ema_21_arr[-1] is not None else None
                if rsi_arr:
                    indicator_data.rsi = rsi_arr[-1] if rsi_arr[-1] is not None else None
                if adr_arr:
                    indicator_data.adr = adr_arr[-1] if adr_arr[-1] is not None else None

            # Legacy fallback: indicators at mode level
            if not series and not tech_indicators_raw:
                indicator_raw = mode_data.get("indicators", {})
                if indicator_raw:
                    indicator_data = parse_indicator_series(indicator_raw)

            # FIX-042: Parse intuition_engine with confidence and recommendations
            intuition_engine = mode_data.get("intuition_engine", {})
            if intuition_engine:
                indicator_data.intuition_text = intuition_engine.get("text")
                indicator_data.intuition_confidence = intuition_engine.get("confidence")
                indicator_data.intuition_recommendations = intuition_engine.get("recommendations")

            result[symbol][mode] = SymbolData(
                candles=candles,
                option_chain=option_chain,
                indicators=indicator_data,
            )

    return result


# -----------------------------------------------------------------------------
# SSE Event Parsers (Requirements 12.3, 12.4, 12.5)
# -----------------------------------------------------------------------------


def parse_indicator_update(event: Dict[str, Any]) -> Tuple[str, str, IndicatorData]:
    """
    Parse indicator_update SSE event.

    Requirement 12.4: WHEN receiving an indicator_update event,
    THE Dashboard SHALL update indicator display.

    SSE indicator_update contains full indicator set:
    - skew, raw_skew, pcr, adr, signal, skew_confidence
    - rsi, ema_5, ema_9, ema_13, ema_21, ema_50
    - bb_upper, bb_middle, bb_lower, vwap, pivot_point
    - intuition_text (AI-generated market insight)

    Args:
        event: SSE event data dict

    Returns:
        Tuple of (symbol, mode, IndicatorData)
    """
    symbol = event.get("symbol", "").lower()
    mode = event.get("mode", "current").lower()
    ind = event.get("indicators", event.get("data", {}))

    # Convert adr to float if it's a string (API returns string in SSE)
    adr_raw = ind.get("adr")
    adr_value = float(adr_raw) if adr_raw is not None else None
    
    # Extract COI sums from support_fields
    support_fields = event.get("support_fields", {})
    call_coi_sum = support_fields.get("call_coi_sum")
    put_coi_sum = support_fields.get("put_coi_sum")
    
    indicator_data = IndicatorData(
        skew=ind.get("skew"),
        raw_skew=ind.get("raw_skew"),
        pcr=ind.get("pcr"),
        adr=adr_value,
        signal=ind.get("signal", "NEUTRAL"),
        skew_confidence=float(ind.get("skew_confidence", 0.0)),
        rsi=ind.get("rsi"),
        ema_5=ind.get("ema_5"),
        ema_9=ind.get("ema_9"),
        ema_13=ind.get("ema_13"),
        ema_21=ind.get("ema_21"),
        ema_50=ind.get("ema_50"),
        bb_upper=ind.get("bb_upper"),
        bb_middle=ind.get("bb_middle"),
        bb_lower=ind.get("bb_lower"),
        vwap=ind.get("vwap"),
        pivot_point=ind.get("pivot_point"),
        intuition_text=event.get("intuition_text"),  # AI-generated insight
        call_coi_sum=float(call_coi_sum) if call_coi_sum is not None else None,
        put_coi_sum=float(put_coi_sum) if put_coi_sum is not None else None,
        ts=parse_timestamp(event.get("timestamp", event.get("ts"))),
    )

    return symbol, mode, indicator_data


def parse_option_chain_update(event: Dict[str, Any]) -> Tuple[str, str, OptionChainData]:
    """
    Parse option_chain_update SSE event.

    Requirement 12.5: WHEN receiving an option_chain_update event,
    THE Dashboard SHALL update option chain OI/COI.

    Args:
        event: SSE event data dict

    Returns:
        Tuple of (symbol, mode, OptionChainData)
    """
    symbol = event.get("symbol", "").lower()
    mode = event.get("mode", "current").lower()

    strikes = []
    strikes_data = event.get("strikes", event.get("data", {}).get("strikes", []))

    for s in strikes_data:
        try:
            skew_val = float(s["strike_skew"]) if s.get("strike_skew") is not None else None
            # Use signal from SSE if available, otherwise derive from skew
            signal_val = s.get("signal") if s.get("signal") else derive_signal_from_skew(skew_val)
            
            strike = OptionStrike(
                strike=float(s.get("strike", 0)),
                call_oi=int(s.get("call_oi", 0)),
                put_oi=int(s.get("put_oi", 0)),
                call_coi=int(s["call_coi"]) if s.get("call_coi") is not None else None,
                put_coi=int(s["put_coi"]) if s.get("put_coi") is not None else None,
                strike_skew=skew_val,
                call_ltp=float(s["call_ltp"]) if s.get("call_ltp") is not None else None,
                put_ltp=float(s["put_ltp"]) if s.get("put_ltp") is not None else None,
                signal=signal_val,
            )
            strikes.append(strike)
        except (ValueError, TypeError, KeyError):
            continue

    option_chain = OptionChainData(
        expiry=event.get("expiry", ""),
        underlying=float(event.get("underlying", 0.0)),
        strikes=strikes,
        ts=parse_timestamp(event.get("timestamp", event.get("ts"))),
    )

    return symbol, mode, option_chain


def parse_snapshot_event(event: Dict[str, Any]) -> Dict[str, Dict[str, SymbolData]]:
    """
    Parse snapshot SSE event.

    Requirement 12.3: WHEN receiving a snapshot event,
    THE Dashboard SHALL populate initial indicator values.

    Args:
        event: SSE snapshot event data dict

    Returns:
        Dict mapping symbol -> mode -> SymbolData
    """
    # Snapshot events have similar structure to bootstrap
    return parse_bootstrap_response(event, filter_to_today=True)


def parse_sse_event(raw_data: str) -> Optional[Dict[str, Any]]:
    """
    Parse raw SSE event data line.

    Handles the "data:" prefix and JSON parsing.

    Args:
        raw_data: Raw SSE data line (e.g., "data: {...}")

    Returns:
        Parsed event dict or None if invalid
    """
    import json

    if not raw_data:
        return None

    # Remove "data:" prefix if present
    if raw_data.startswith("data:"):
        raw_data = raw_data[5:].strip()
    elif raw_data.startswith("data: "):
        raw_data = raw_data[6:].strip()

    if not raw_data:
        return None

    try:
        return json.loads(raw_data)
    except json.JSONDecodeError:
        return None


def get_event_type(event: Dict[str, Any]) -> str:
    """
    Extract event type from SSE event.

    Args:
        event: Parsed SSE event dict

    Returns:
        Event type string (snapshot, indicator_update, option_chain_update,
        market_closed, heartbeat, refresh_recommended)
    """
    return event.get("event_type", event.get("event", event.get("type", "unknown")))


def handle_sse_event(
    event: Dict[str, Any],
) -> Tuple[str, Any]:
    """
    Route SSE event to appropriate parser.

    Requirements 12.3, 12.4, 12.5: Handle snapshot, indicator_update,
    option_chain_update, market_closed events.

    Args:
        event: Parsed SSE event dict

    Returns:
        Tuple of (event_type, parsed_data)
        - For snapshot: (event_type, Dict[symbol, Dict[mode, SymbolData]])
        - For indicator_update: (event_type, (symbol, mode, IndicatorData))
        - For option_chain_update: (event_type, (symbol, mode, OptionChainData))
        - For market_closed: (event_type, None)
        - For heartbeat: (event_type, timestamp)
        - For refresh_recommended: (event_type, None)
    """
    event_type = get_event_type(event)

    if event_type == "snapshot":
        return event_type, parse_snapshot_event(event)

    elif event_type == "indicator_update":
        return event_type, parse_indicator_update(event)

    elif event_type == "option_chain_update":
        return event_type, parse_option_chain_update(event)

    elif event_type == "market_closed":
        return event_type, None

    elif event_type == "heartbeat":
        return event_type, parse_timestamp(event.get("timestamp", event.get("ts")))

    elif event_type == "refresh_recommended":
        return event_type, None

    else:
        return event_type, event
