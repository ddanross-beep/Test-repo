"""Technical indicators used by the momentum strategy."""
from __future__ import annotations


def rsi(closes: list[float], period: int = 14) -> float | None:
    """Compute the most recent Wilder RSI value for a series of closing prices.

    Returns None if there isn't enough data to compute a value.
    """
    if len(closes) < period + 1:
        return None

    gains = []
    losses = []
    for prev, cur in zip(closes, closes[1:]):
        change = cur - prev
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def percent_change(closes: list[float]) -> float | None:
    """Percent change from the first to the last value in the series."""
    if len(closes) < 2 or closes[0] == 0:
        return None
    return (closes[-1] - closes[0]) / closes[0] * 100.0
