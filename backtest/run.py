"""Load the fetched bars, run the strategy and its benchmarks, print a report."""
from __future__ import annotations

import glob
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import Config, add_indicators, metrics, run_backtest  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, sys.argv[1] if len(sys.argv) > 1 else "data")
TAG = os.path.basename(DATA)
WARMUP = 200  # SMA200 needs this many bars before the strategy can trade


def load_bars(path: str) -> dict[str, pd.DataFrame]:
    with open(path) as fh:
        blob = json.load(fh)
    out = {}
    for res in blob.get("data", {}).get("results", []):
        sym = res.get("symbol")
        bars = res.get("bars") or []
        if not sym or len(bars) < WARMUP + 20:
            continue
        df = pd.DataFrame(bars)
        df["date"] = pd.to_datetime(df["begins_at"]).dt.tz_localize(None).dt.normalize()
        for src, dst in [
            ("open_price", "open"), ("close_price", "close"),
            ("high_price", "high"), ("low_price", "low"),
        ]:
            df[dst] = pd.to_numeric(df[src], errors="coerce")
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
        df = df[["date", "open", "high", "low", "close", "volume"]].dropna(subset=["close"])
        df = df.drop_duplicates("date").set_index("date").sort_index()
        if len(df) >= WARMUP + 20:
            out[sym] = df
    return out


def main():
    panels: dict[str, pd.DataFrame] = {}
    for path in sorted(glob.glob(os.path.join(DATA, "batch_*.json"))):
        panels.update(load_bars(path))
    spy_raw = load_bars(os.path.join(DATA, "spy.json"))
    spy = spy_raw.get("SPY")
    panels.pop("SPY", None)

    print(f"universe loaded: {len(panels)} symbols with >= {WARMUP+20} daily bars")
    if spy is None:
        print("WARNING: no SPY benchmark data")

    for sym in list(panels):
        panels[sym] = add_indicators(panels[sym])

    all_dates = sorted({d for df in panels.values() for d in df.index})
    trade_dates = all_dates[WARMUP:]
    print(f"date range: {all_dates[0].date()} -> {all_dates[-1].date()} "
          f"({len(all_dates)} sessions); scored from {trade_dates[0].date()}")

    # close-price matrix for the equal-weight benchmark
    closes = pd.DataFrame({s: df["close"] for s, df in panels.items()}).reindex(all_dates).ffill()

    START = 10000.0
    rows = []

    def window(eq: pd.DataFrame) -> pd.DataFrame:
        w = eq[eq.index >= trade_dates[0]].copy()
        w["equity"] = w["equity"] / w["equity"].iloc[0] * START
        return w

    # ---- benchmark 1: SPY buy and hold
    if spy is not None:
        s = spy["close"].reindex(all_dates).ffill().dropna()
        rows.append(metrics(window(pd.DataFrame({"equity": s})), None, "SPY buy & hold"))

    # ---- benchmark 2: equal-weight hold of the whole universe
    ew = closes.div(closes.iloc[0]).mean(axis=1) * START
    rows.append(metrics(window(pd.DataFrame({"equity": ew})), None,
                        "Universe equal-weight buy & hold"))

    # ---- the strategy, base case + variants
    variants = [
        ("STRATEGY (base: 0.15%/side slip)", dict()),
        ("  no slippage (idealized)", dict(slippage=0.0)),
        ("  high slippage 0.40%/side", dict(slippage=0.004)),
        ("  no 200d trend filter", dict(use_trend_filter=False)),
        ("  no stops (exits only)", dict(use_stops=False)),
        ("  RSI entry <=25 (stricter)", dict(rsi_entry=25.0)),
        ("  RSI entry <=45 (looser)", dict(rsi_entry=45.0)),
        ("  ATR mult 3 (wider stop)", dict(atr_mult=3.0)),
        ("  risk 1% per trade", dict(risk_pct=0.01)),
    ]

    trade_store = {}
    for label, kw in variants:
        cfg = Config(starting_cash=START, **kw)
        eq, tr = run_backtest(panels, cfg)
        trade_store[label] = tr
        rows.append(metrics(window(eq), tr, label))

    res = pd.DataFrame(rows)
    pd.set_option("display.width", 200, "display.max_columns", 30)

    print("\n" + "=" * 110)
    print("RESULTS")
    print("=" * 110)
    cols = ["label", "total_return_pct", "cagr_pct", "max_drawdown_pct", "sharpe",
            "n_trades", "win_rate_pct", "avg_win_pct", "avg_loss_pct", "profit_factor",
            "avg_hold_days"]
    show = res.reindex(columns=cols).copy()
    for c in cols[1:]:
        if c in show:
            show[c] = pd.to_numeric(show[c], errors="coerce").round(2)
    print(show.to_string(index=False, na_rep="-"))

    base = trade_store["STRATEGY (base: 0.15%/side slip)"]
    if len(base):
        print("\n" + "=" * 110)
        print("BASE CASE: exit reason breakdown")
        print("=" * 110)
        g = base.groupby("reason").agg(
            n=("pnl", "size"), total_pnl=("pnl", "sum"),
            avg_pct=("pct", "mean"), win_rate=("pnl", lambda x: (x > 0).mean() * 100),
        ).round(2)
        print(g.to_string())

        print("\nBest 5 trades:")
        print(base.nlargest(5, "pct")[["symbol", "entry_date", "exit_date", "pct", "pnl", "reason"]]
              .to_string(index=False))
        print("\nWorst 5 trades:")
        print(base.nsmallest(5, "pct")[["symbol", "entry_date", "exit_date", "pct", "pnl", "reason"]]
              .to_string(index=False))

    # ---- year-by-year: does it hold up outside a bull market?
    cfg = Config(starting_cash=START)
    eq_b, _ = run_backtest(panels, cfg)
    spy_s = spy["close"].reindex(all_dates).ffill() if spy is not None else None
    print("\n" + "=" * 110)
    print("CALENDAR-YEAR RETURNS (strategy vs SPY vs universe)")
    print("=" * 110)
    yr_rows = []
    for yr in sorted({d.year for d in trade_dates}):
        sel = [d for d in trade_dates if d.year == yr]
        if len(sel) < 20:
            continue
        def pct(series):
            s = series.reindex(sel).ffill().dropna()
            return (s.iloc[-1] / s.iloc[0] - 1) * 100 if len(s) > 1 else np.nan
        yr_rows.append({
            "year": yr, "sessions": len(sel),
            "strategy_pct": round(pct(eq_b["equity"]), 2),
            "spy_pct": round(pct(spy_s), 2) if spy_s is not None else np.nan,
            "universe_pct": round(pct(ew), 2),
        })
    print(pd.DataFrame(yr_rows).to_string(index=False, na_rep="-"))

    res.to_csv(os.path.join(HERE, f"results_{TAG}.csv"), index=False)
    base.to_csv(os.path.join(HERE, f"base_trades_{TAG}.csv"), index=False)
    print(f"\nwrote results_{TAG}.csv and base_trades_{TAG}.csv to {HERE}")


if __name__ == "__main__":
    main()
