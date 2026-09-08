"""Momentum ('buy low, sell high') signal logic on top of RSI."""
from __future__ import annotations

from dataclasses import dataclass

from trading_bot.indicators import percent_change, rsi

OVERSOLD_THRESHOLD = 30.0
OVERBOUGHT_THRESHOLD = 70.0


@dataclass
class Signal:
    symbol: str
    action: str  # "buy", "sell", or "hold"
    rsi: float | None
    percent_move: float | None
    reason: str


def evaluate(symbol: str, closes: list[float], rsi_period: int = 14) -> Signal:
    """Turn a series of recent closing prices into a buy/sell/hold signal.

    Strategy: a stock that is moving fast (large recent percent change) and
    whose RSI shows it dipped into oversold territory is a momentum "buy low"
    candidate. One that has run up and is now overbought is a "sell high"
    candidate.
    """
    value = rsi(closes, period=rsi_period)
    move = percent_change(closes)

    if value is None or move is None:
        return Signal(symbol, "hold", value, move, "not enough price history")

    if value <= OVERSOLD_THRESHOLD:
        return Signal(
            symbol,
            "buy",
            value,
            move,
            f"RSI {value:.1f} <= {OVERSOLD_THRESHOLD} (oversold) with {move:+.2f}% move",
        )

    if value >= OVERBOUGHT_THRESHOLD:
        return Signal(
            symbol,
            "sell",
            value,
            move,
            f"RSI {value:.1f} >= {OVERBOUGHT_THRESHOLD} (overbought) with {move:+.2f}% move",
        )

    return Signal(symbol, "hold", value, move, f"RSI {value:.1f} in neutral range")
