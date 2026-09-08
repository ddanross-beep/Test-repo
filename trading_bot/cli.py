"""Command-line entry point for the momentum trading bot.

Default mode is a dry run: it scans for fast-moving stocks, computes RSI
signals, and prints what it *would* do. Live orders only fire with --live,
and each one still requires typed confirmation unless --yes is also passed.
"""
from __future__ import annotations

import argparse

from trading_bot.robinhood_client import RobinhoodClient
from trading_bot.strategy import Signal, evaluate


def scan(client: RobinhoodClient, count: int, rsi_period: int) -> list[Signal]:
    movers = client.top_movers(direction="up", count=count) + client.top_movers(
        direction="down", count=count
    )
    signals = []
    for mover in movers:
        symbol = mover.get("symbol")
        if not symbol:
            continue
        closes = client.closing_prices(symbol)
        signals.append(evaluate(symbol, closes, rsi_period=rsi_period))
    return signals


def confirm(prompt: str) -> bool:
    return input(f"{prompt} [y/N]: ").strip().lower() == "y"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Momentum ('buy low, sell high') stock scanner/trader.")
    parser.add_argument("--count", type=int, default=10, help="How many top movers per direction to scan")
    parser.add_argument("--rsi-period", type=int, default=14, help="RSI lookback period")
    parser.add_argument("--quantity", type=float, default=1, help="Share quantity per order")
    parser.add_argument("--live", action="store_true", help="Actually place orders (default: dry run only)")
    parser.add_argument("--yes", action="store_true", help="Skip the per-order confirmation prompt in --live mode")
    args = parser.parse_args(argv)

    client = RobinhoodClient()
    signals = scan(client, args.count, args.rsi_period)

    actionable = [s for s in signals if s.action != "hold"]
    if not actionable:
        print("No buy/sell signals found this scan.")
        return 0

    for signal in actionable:
        print(f"{signal.symbol}: {signal.action.upper()} — {signal.reason}")

        if not args.live:
            continue

        if not args.yes and not confirm(f"Place a {signal.action} order for {signal.symbol}?"):
            print(f"  skipped {signal.symbol}")
            continue

        if signal.action == "buy":
            result = client.place_buy(signal.symbol, args.quantity)
        else:
            result = client.place_sell(signal.symbol, args.quantity)
        print(f"  order result: {result}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
