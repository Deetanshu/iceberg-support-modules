# Iceberg Test Dashboard - Chart Components
"""
Chart components for the Iceberg Test Dashboard.

Provides professional trading chart visualizations using Plotly:
- Candlestick chart with volume subplot
- EMA indicator chart
- ADR treemap visualization

Requirements: 6.1, 6.3, 6.6, 7.1, 7.2, 7.5, 7.6, 14.1, 14.3, 14.4
"""

from typing import List, Optional, Tuple
from datetime import datetime
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .models import Candle, IndicatorData


# Chart color scheme - Professional dark theme
# Requirements 2.1, 2.2, 2.3: Professional theme with dark teal background
CHART_COLORS = {
    "bg": "#2D4A5E",  # Dark teal background
    "grid": "#3D5A6E",  # Slightly lighter grid
    "text": "#FFFFFF",  # White text
    "bullish": "#4CAF50",  # Green for up
    "bearish": "#F44336",  # Red for down
    "volume_up": "rgba(76, 175, 80, 0.5)",  # Semi-transparent green
    "volume_down": "rgba(244, 67, 54, 0.5)",  # Semi-transparent red
    "ema_fast": "#00BCD4",  # Cyan for EMA 5 (fast)
    "ema_slow": "#E040FB",  # Magenta for EMA 21 (slow)
    "rsi_line": "#FFC107",  # Amber for RSI
    "rsi_overbought": "#F44336",  # Red for overbought zone
    "rsi_oversold": "#4CAF50",  # Green for oversold zone
    "rsi_zone": "rgba(255, 255, 255, 0.1)",  # Subtle zone fill
}


def create_candlestick_chart(
    candles: List[Candle],
    symbol: str,
    rsi_values: Optional[List[Tuple[datetime, float]]] = None,
) -> go.Figure:
    """Create professional candlestick chart with volume and RSI subplots.

    Requirements:
        6.1: Display candlestick chart using 5-minute candle data
        6.3: Display RSI as a subplot below the main price chart
        6.6: Display volume as bars at the bottom of the price chart

    Args:
        candles: List of Candle objects with OHLCV data
        symbol: Trading symbol for chart title
        rsi_values: Optional list of (timestamp, rsi) tuples for RSI subplot

    Returns:
        Plotly Figure with candlestick, volume, and RSI subplots
    """
    if not candles:
        # Return empty chart with message
        fig = go.Figure()
        fig.add_annotation(
            text="No candle data available",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(size=16, color=CHART_COLORS["text"]),
        )
        fig.update_layout(
            paper_bgcolor=CHART_COLORS["bg"],
            plot_bgcolor=CHART_COLORS["bg"],
            font=dict(color=CHART_COLORS["text"]),
        )
        return fig

    # Determine if we have RSI data
    has_rsi = rsi_values is not None and len(rsi_values) > 0

    # Create subplots: candlestick (main), volume, and optionally RSI
    if has_rsi:
        fig = make_subplots(
            rows=3,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.03,
            row_heights=[0.6, 0.2, 0.2],
            subplot_titles=(f"{symbol.upper()} - 5min", "Volume", "RSI (14)"),
        )
    else:
        fig = make_subplots(
            rows=2,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.03,
            row_heights=[0.75, 0.25],
            subplot_titles=(f"{symbol.upper()} - 5min", "Volume"),
        )

    # Extract candle data
    timestamps = [c.ts for c in candles]
    opens = [c.open for c in candles]
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    closes = [c.close for c in candles]
    volumes = [c.volume for c in candles]

    # Candlestick trace (Requirement 6.1)
    fig.add_trace(
        go.Candlestick(
            x=timestamps,
            open=opens,
            high=highs,
            low=lows,
            close=closes,
            increasing_line_color=CHART_COLORS["bullish"],
            decreasing_line_color=CHART_COLORS["bearish"],
            increasing_fillcolor=CHART_COLORS["bullish"],
            decreasing_fillcolor=CHART_COLORS["bearish"],
            name="OHLC",
            showlegend=False,
        ),
        row=1,
        col=1,
    )

    # Volume bars with color based on candle direction (Requirement 6.6)
    volume_colors = [
        CHART_COLORS["volume_up"] if c >= o else CHART_COLORS["volume_down"]
        for o, c in zip(opens, closes)
    ]
    fig.add_trace(
        go.Bar(
            x=timestamps,
            y=volumes,
            marker_color=volume_colors,
            name="Volume",
            showlegend=False,
        ),
        row=2,
        col=1,
    )

    # RSI subplot if data available (Requirement 6.3)
    if has_rsi:
        rsi_ts = [r[0] for r in rsi_values]
        rsi_vals = [r[1] for r in rsi_values]

        # RSI line
        fig.add_trace(
            go.Scatter(
                x=rsi_ts,
                y=rsi_vals,
                mode="lines",
                line=dict(color=CHART_COLORS["rsi_line"], width=2),
                name="RSI",
                showlegend=False,
            ),
            row=3,
            col=1,
        )

        # Overbought line (70)
        fig.add_hline(
            y=70,
            line_dash="dash",
            line_color=CHART_COLORS["rsi_overbought"],
            row=3,
            col=1,
        )

        # Oversold line (30)
        fig.add_hline(
            y=30,
            line_dash="dash",
            line_color=CHART_COLORS["rsi_oversold"],
            row=3,
            col=1,
        )

        # RSI y-axis range
        fig.update_yaxes(range=[0, 100], row=3, col=1)

    # Apply professional dark theme
    fig.update_layout(
        paper_bgcolor=CHART_COLORS["bg"],
        plot_bgcolor=CHART_COLORS["bg"],
        font=dict(color=CHART_COLORS["text"], family="Arial, sans-serif"),
        xaxis_rangeslider_visible=False,
        showlegend=False,
        margin=dict(l=60, r=20, t=40, b=20),
        hovermode="x unified",
    )

    # Update all axes with grid styling
    for i in range(1, 4 if has_rsi else 3):
        fig.update_xaxes(
            gridcolor=CHART_COLORS["grid"],
            showgrid=True,
            zeroline=False,
            row=i,
            col=1,
        )
        fig.update_yaxes(
            gridcolor=CHART_COLORS["grid"],
            showgrid=True,
            zeroline=False,
            row=i,
            col=1,
        )

    # Style subplot titles
    for annotation in fig.layout.annotations:
        annotation.font = dict(color=CHART_COLORS["text"], size=12)

    return fig



def create_ema_chart(
    ema_history: List[Tuple[datetime, float, float]],
    symbol: str,
) -> go.Figure:
    """Create EMA indicator chart with fast and slow EMA lines.

    Requirements:
        7.1: Display separate chart showing EMA values over time
        7.2: Plot EMA_5 (fast) and EMA_21 (slow) as line series
        7.5: Use distinct colors for fast (cyan) and slow (magenta) EMAs
        7.6: Share the same time axis as the candlestick chart

    Args:
        ema_history: List of (timestamp, ema_5, ema_21) tuples
        symbol: Trading symbol for chart title

    Returns:
        Plotly Figure with EMA lines
    """
    fig = go.Figure()

    if not ema_history:
        # Return empty chart with message
        fig.add_annotation(
            text="No EMA data available",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(size=16, color=CHART_COLORS["text"]),
        )
        fig.update_layout(
            paper_bgcolor=CHART_COLORS["bg"],
            plot_bgcolor=CHART_COLORS["bg"],
            font=dict(color=CHART_COLORS["text"]),
        )
        return fig

    # Extract EMA data
    timestamps = [e[0] for e in ema_history]
    ema_5_values = [e[1] for e in ema_history]
    ema_21_values = [e[2] for e in ema_history]

    # EMA 5 (fast) - Cyan (Requirement 7.5)
    fig.add_trace(
        go.Scatter(
            x=timestamps,
            y=ema_5_values,
            mode="lines",
            name="EMA 5",
            line=dict(color=CHART_COLORS["ema_fast"], width=2),
            hovertemplate="EMA 5: %{y:.2f}<extra></extra>",
        )
    )

    # EMA 21 (slow) - Magenta (Requirement 7.5)
    fig.add_trace(
        go.Scatter(
            x=timestamps,
            y=ema_21_values,
            mode="lines",
            name="EMA 21",
            line=dict(color=CHART_COLORS["ema_slow"], width=2),
            hovertemplate="EMA 21: %{y:.2f}<extra></extra>",
        )
    )

    # Apply professional dark theme
    fig.update_layout(
        title=dict(
            text=f"{symbol.upper()} - EMA Indicator",
            font=dict(color=CHART_COLORS["text"], size=14),
        ),
        paper_bgcolor=CHART_COLORS["bg"],
        plot_bgcolor=CHART_COLORS["bg"],
        font=dict(color=CHART_COLORS["text"], family="Arial, sans-serif"),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            font=dict(color=CHART_COLORS["text"]),
        ),
        margin=dict(l=60, r=20, t=60, b=20),
        hovermode="x unified",
    )

    # Update axes with grid styling
    fig.update_xaxes(
        gridcolor=CHART_COLORS["grid"],
        showgrid=True,
        zeroline=False,
    )
    fig.update_yaxes(
        gridcolor=CHART_COLORS["grid"],
        showgrid=True,
        zeroline=False,
    )

    return fig



def create_adr_treemap(
    constituents: List[dict],
    symbol: str = "NIFTY",
) -> go.Figure:
    """Create ADR treemap visualization showing constituent performance.

    Requirements:
        14.1: Display ADR data as a treemap on the Advanced tab
        14.3: Size rectangles by LTP (larger stocks get bigger rectangles)
        14.4: Color rectangles green for advancing, red for declining constituents

    Args:
        constituents: List of dicts with 'symbol', 'change_pct', and 'ltp' keys
            Example: [{"symbol": "RELIANCE", "change_pct": 1.5, "ltp": 2500.0}, ...]
        symbol: Index symbol for chart title

    Returns:
        Plotly Figure with treemap visualization
    """
    fig = go.Figure()

    if not constituents:
        # Return empty chart with message
        fig.add_annotation(
            text="No constituent data available",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(size=16, color="#333333"),
        )
        fig.update_layout(
            paper_bgcolor="#F5F5F5",
            font=dict(color="#333333"),
        )
        return fig

    # Extract data
    labels = [c.get("symbol", "Unknown") for c in constituents]
    change_pcts = [c.get("change_pct", 0.0) for c in constituents]
    ltps = [c.get("ltp", 1.0) for c in constituents]

    # Size by LTP (market cap proxy) - larger stocks get bigger rectangles
    # Add small minimum to prevent zero-sized rectangles
    values = [max(ltp, 0.01) for ltp in ltps]

    # Color by direction: green for advancing, red for declining (Requirement 14.4)
    colors = []
    for pct in change_pcts:
        if pct >= 0:
            # Green shades based on magnitude
            intensity = min(abs(pct) / 3.0, 1.0)  # Normalize to 0-1
            colors.append(f"rgba(76, 175, 80, {0.4 + 0.6 * intensity})")
        else:
            # Red shades based on magnitude
            intensity = min(abs(pct) / 3.0, 1.0)  # Normalize to 0-1
            colors.append(f"rgba(244, 67, 54, {0.4 + 0.6 * intensity})")

    # Create text labels with symbol and change percentage
    text_labels = [
        f"{label}<br>{pct:+.2f}%" for label, pct in zip(labels, change_pcts)
    ]

    # Create treemap
    fig = go.Figure(
        go.Treemap(
            labels=labels,
            parents=[""] * len(labels),
            values=values,
            marker=dict(
                colors=colors,
                line=dict(width=1, color="#FFFFFF"),
            ),
            text=text_labels,
            textinfo="text",
            textfont=dict(size=12, color="#FFFFFF"),
            hovertemplate="<b>%{label}</b><br>Change: %{customdata:.2f}%<extra></extra>",
            customdata=change_pcts,
        )
    )

    # Apply light theme for treemap (matches dashboard content area)
    fig.update_layout(
        title=dict(
            text=f"{symbol.upper()} Constituents - ADR Treemap",
            font=dict(color="#333333", size=14),
        ),
        paper_bgcolor="#F5F5F5",
        font=dict(color="#333333", family="Arial, sans-serif"),
        margin=dict(l=10, r=10, t=50, b=10),
    )

    return fig


def create_empty_chart(message: str = "No data available") -> go.Figure:
    """Create an empty chart with a message.

    Utility function for displaying placeholder charts when data is unavailable.

    Args:
        message: Message to display in the empty chart

    Returns:
        Plotly Figure with centered message
    """
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        xref="paper",
        yref="paper",
        x=0.5,
        y=0.5,
        showarrow=False,
        font=dict(size=16, color=CHART_COLORS["text"]),
    )
    fig.update_layout(
        paper_bgcolor=CHART_COLORS["bg"],
        plot_bgcolor=CHART_COLORS["bg"],
        font=dict(color=CHART_COLORS["text"]),
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
    )
    return fig


def create_skew_pcr_chart(
    skew_pcr_history: List[Tuple[datetime, float, float]],
    symbol: str,
    mode: str = "current",
) -> go.Figure:
    """Create Skew/PCR timeseries chart with dual y-axes.

    Requirements:
        8.1: Display current Skew value with color coding
        8.2: Display current PCR value
        8.7: WHEN indicator values update via SSE, refresh display immediately

    Args:
        skew_pcr_history: List of (timestamp, skew, pcr) tuples
        symbol: Trading symbol for chart title
        mode: Expiry mode ('current' or 'positional')

    Returns:
        Plotly Figure with Skew and PCR lines on dual y-axes
    """
    fig = go.Figure()

    if not skew_pcr_history:
        # Return empty chart with message
        fig.add_annotation(
            text="No Skew/PCR data available",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(size=16, color=CHART_COLORS["text"]),
        )
        fig.update_layout(
            paper_bgcolor=CHART_COLORS["bg"],
            plot_bgcolor=CHART_COLORS["bg"],
            font=dict(color=CHART_COLORS["text"]),
        )
        return fig

    # Extract data
    timestamps = [h[0] for h in skew_pcr_history]
    skew_values = [h[1] for h in skew_pcr_history]
    pcr_values = [h[2] for h in skew_pcr_history]

    # Skew line (primary y-axis) - Green for positive, Red for negative
    # Use a gradient color based on value
    skew_colors = [
        CHART_COLORS["bullish"] if v >= 0 else CHART_COLORS["bearish"]
        for v in skew_values
    ]
    
    fig.add_trace(
        go.Scatter(
            x=timestamps,
            y=skew_values,
            mode="lines+markers",
            name="Skew",
            line=dict(color="#00BCD4", width=2),  # Cyan for Skew
            marker=dict(
                size=6,
                color=skew_colors,
                line=dict(width=1, color="#FFFFFF"),
            ),
            hovertemplate="Skew: %{y:.3f}<extra></extra>",
            yaxis="y1",
        )
    )

    # PCR line (secondary y-axis) - Amber/Orange
    fig.add_trace(
        go.Scatter(
            x=timestamps,
            y=pcr_values,
            mode="lines+markers",
            name="PCR",
            line=dict(color="#FFC107", width=2),  # Amber for PCR
            marker=dict(size=5),
            hovertemplate="PCR: %{y:.2f}<extra></extra>",
            yaxis="y2",
        )
    )

    # Add zero line for Skew reference
    fig.add_hline(
        y=0,
        line_dash="dash",
        line_color="rgba(255, 255, 255, 0.3)",
        annotation_text="Neutral",
        annotation_position="right",
    )

    # Add threshold lines for Skew signals
    fig.add_hline(
        y=0.3,
        line_dash="dot",
        line_color="rgba(76, 175, 80, 0.5)",  # Green
        annotation_text="BUY",
        annotation_position="right",
    )
    fig.add_hline(
        y=-0.3,
        line_dash="dot",
        line_color="rgba(244, 67, 54, 0.5)",  # Red
        annotation_text="SELL",
        annotation_position="right",
    )

    # Apply professional dark theme with dual y-axes
    mode_label = "Weekly" if mode == "current" else "Monthly"
    fig.update_layout(
        title=dict(
            text=f"{symbol.upper()} - Skew & PCR ({mode_label})",
            font=dict(color=CHART_COLORS["text"], size=14),
        ),
        paper_bgcolor=CHART_COLORS["bg"],
        plot_bgcolor=CHART_COLORS["bg"],
        font=dict(color=CHART_COLORS["text"], family="Arial, sans-serif"),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            font=dict(color=CHART_COLORS["text"]),
        ),
        margin=dict(l=60, r=60, t=60, b=20),
        hovermode="x unified",
        # Primary y-axis (Skew)
        yaxis=dict(
            title=dict(text="Skew", font=dict(color="#00BCD4")),
            tickfont=dict(color="#00BCD4"),
            gridcolor=CHART_COLORS["grid"],
            showgrid=True,
            zeroline=True,
            zerolinecolor="rgba(255, 255, 255, 0.3)",
            range=[-1.0, 1.0],  # Skew ranges from -1 to +1
        ),
        # Secondary y-axis (PCR)
        yaxis2=dict(
            title=dict(text="PCR", font=dict(color="#FFC107")),
            tickfont=dict(color="#FFC107"),
            anchor="x",
            overlaying="y",
            side="right",
            showgrid=False,
        ),
    )

    # Update x-axis with grid styling
    fig.update_xaxes(
        gridcolor=CHART_COLORS["grid"],
        showgrid=True,
        zeroline=False,
    )

    return fig
