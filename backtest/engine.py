"""Backtest engine for the hybrid RSI mean-reversion / trend-filter strategy.

Signals are computed on day T's close; orders execute at day T+1's open.
No indicator ever reads a bar later than the one it is evaluated on.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------- indicators

def wilder_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - 100.0 / (1.0 + rs)
    return rsi.where(avg_loss != 0.0, 100.0)


def wilder_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def add_indicators(df: pd.DataFrame, rsi_p=14, atr_p=14, sma_p=200) -> pd.DataFrame:
    df = df.sort_index().copy()
    df["rsi"] = wilder_rsi(df["close"], rsi_p)
    df["atr"] = wilder_atr(df["high"], df["low"], df["close"], atr_p)
    df["sma"] = df["close"].rolling(sma_p, min_periods=sma_p).mean()
    df["sma50"] = df["close"].rolling(50, min_periods=50).mean()
    # trailing 252-session high, excluding today (no look-ahead)
    df["hi252"] = df["high"].rolling(252, min_periods=200).max().shift(1)
    return df


# ---------------------------------------------------------------- config

class Config:
    def __init__(self, **kw):
        self.risk_pct = 0.02
        self.atr_mult = 2.0
        self.min_stop_pct = 0.05
        self.max_position_pct = 0.20
        self.max_positions = 10
        self.max_buys_per_day = 3
        self.rsi_entry = 35.0
        self.rsi_exit = 65.0
        self.price_min = 2.0
        self.price_max = 15.0
        self.slippage = 0.0015      # per side, fraction of price
        self.starting_cash = 10000.0
        self.use_trend_filter = True
        self.use_stops = True
        # entry_mode: "meanrev" = Model A (RSI dip in uptrend)
        #             "momentum" = Model B (strength continuation)
        self.entry_mode = "meanrev"
        self.mom_rsi_lo = 50.0      # Model B: RSI band
        self.mom_rsi_hi = 70.0
        self.mom_near_high = 0.10   # Model B: within this fraction of the 252d high
        self.mom_exit_rsi = 40.0    # Model B: exit when momentum decays below this
        for k, v in kw.items():
            if not hasattr(self, k):
                raise AttributeError(f"unknown config key: {k}")
            setattr(self, k, v)


# ---------------------------------------------------------------- engine

class Position:
    __slots__ = ("symbol", "shares", "entry_price", "entry_date", "stop", "stop_distance")

    def __init__(self, symbol, shares, entry_price, entry_date, stop, stop_distance):
        self.symbol = symbol
        self.shares = shares
        self.entry_price = entry_price
        self.entry_date = entry_date
        self.stop = stop
        self.stop_distance = stop_distance


def run_backtest(panels: dict[str, pd.DataFrame], cfg: Config):
    """panels: symbol -> DataFrame indexed by date with open/high/low/close/volume + indicators."""
    all_dates = sorted({d for df in panels.values() for d in df.index})
    cash = cfg.starting_cash
    positions: dict[str, Position] = {}
    trades = []
    equity_curve = []

    # Pending orders decided on the previous close, executed at today's open.
    pending_buys: list[tuple[str, float, float]] = []   # (symbol, stop_distance, ref_price)
    pending_sells: list[tuple[str, str]] = []           # (symbol, reason)
    prev_equity = cfg.starting_cash  # equity as of the prior close; sizing must not peek at today

    for date in all_dates:
        bars = {}
        for sym, df in panels.items():
            if date in df.index:
                row = df.loc[date]
                if not np.isnan(row["open"]):
                    bars[sym] = row

        # ---- 1. execute pending sells at the open
        for sym, reason in pending_sells:
            if sym in positions and sym in bars:
                pos = positions.pop(sym)
                px = bars[sym]["open"] * (1 - cfg.slippage)
                cash += pos.shares * px
                trades.append(_close(pos, date, px, reason))
        pending_sells = []

        # ---- 2. execute pending buys at the open
        bought_today = 0
        for sym, stop_distance, _ref in pending_buys:
            if bought_today >= cfg.max_buys_per_day:
                break
            if sym in positions or sym not in bars:
                continue
            if len(positions) >= cfg.max_positions:
                break
            px = bars[sym]["open"] * (1 + cfg.slippage)
            if px <= 0 or np.isnan(px):
                continue
            # size off the PRIOR close's equity - using today's close would be look-ahead
            equity = prev_equity
            shares_risk = int(cfg.risk_pct * equity / stop_distance) if stop_distance > 0 else 0
            shares_cap = int(cfg.max_position_pct * equity / px)
            shares_cash = int(cash / px)
            shares = max(0, min(shares_risk, shares_cap, shares_cash))
            if shares < 1:
                continue
            cash -= shares * px
            positions[sym] = Position(
                sym, shares, px, date, px - stop_distance, stop_distance
            )
            bought_today += 1
        pending_buys = []

        # ---- 3. intraday stop checks on today's bar
        if cfg.use_stops:
            for sym in list(positions):
                if sym not in bars:
                    continue
                pos = positions[sym]
                if pos.entry_date == date:
                    continue  # don't stop out on the entry bar
                bar = bars[sym]
                if bar["low"] <= pos.stop:
                    # gap through the stop fills at the open, else at the stop
                    fill = min(pos.stop, bar["open"])
                    fill *= (1 - cfg.slippage)
                    positions.pop(sym)
                    cash += pos.shares * fill
                    trades.append(_close(pos, date, fill, "stop"))

        # ---- 4. mark to market
        equity = cash + sum(
            p.shares * bars[s]["close"] for s, p in positions.items() if s in bars
        )
        equity_curve.append((date, equity, cash, len(positions)))
        prev_equity = equity

        # ---- 5. decide tomorrow's orders from today's close
        for sym in list(positions):
            if sym not in bars:
                continue
            row = bars[sym]
            if np.isnan(row["close"]):
                continue
            if cfg.use_trend_filter and not np.isnan(row["sma"]) and row["close"] < row["sma"]:
                pending_sells.append((sym, "trend_break"))
            elif cfg.entry_mode == "momentum":
                # Model B rides strength: decay exit, plus the shared overbought exit
                if not np.isnan(row["rsi"]) and row["rsi"] <= cfg.mom_exit_rsi:
                    pending_sells.append((sym, "momentum_decay"))
                elif not np.isnan(row["rsi"]) and row["rsi"] >= cfg.rsi_exit:
                    pending_sells.append((sym, "overbought"))
            elif not np.isnan(row["rsi"]) and row["rsi"] >= cfg.rsi_exit:
                pending_sells.append((sym, "overbought"))

        selling = {s for s, _ in pending_sells}
        slots = cfg.max_positions - (len(positions) - len(selling))
        if slots > 0:
            cands = []
            for sym, row in bars.items():
                if sym in positions or sym in selling:
                    continue
                c, r, a, s = row["close"], row["rsi"], row["atr"], row["sma"]
                if np.isnan(r) or np.isnan(a) or a <= 0:
                    continue
                if cfg.use_trend_filter and (np.isnan(s) or c <= s):
                    continue
                if not (cfg.price_min <= c <= cfg.price_max):
                    continue
                sd = max(cfg.atr_mult * a, cfg.min_stop_pct * c)
                if cfg.entry_mode == "momentum":
                    hi = row["hi252"]
                    s50 = row["sma50"]
                    if np.isnan(hi) or np.isnan(s50):
                        continue
                    if c < hi * (1.0 - cfg.mom_near_high):   # must be near its 1yr high
                        continue
                    if c <= s50:                              # and above its 50d average
                        continue
                    if not (cfg.mom_rsi_lo <= r <= cfg.mom_rsi_hi):
                        continue
                    cands.append((-r, sym, sd, c))            # strongest RSI first
                else:
                    if r > cfg.rsi_entry:
                        continue
                    cands.append((r, sym, sd, c))             # weakest RSI first
            cands.sort()
            for r, sym, sd, c in cands[: cfg.max_buys_per_day]:
                pending_buys.append((sym, sd, c))

    # liquidate at the end so open positions are counted
    last = all_dates[-1]
    for sym, pos in list(positions.items()):
        df = panels[sym]
        px = df.loc[last, "close"] if last in df.index else df["close"].iloc[-1]
        cash += pos.shares * px
        trades.append(_close(pos, last, px, "final"))
    positions.clear()

    eq = pd.DataFrame(equity_curve, columns=["date", "equity", "cash", "n_pos"]).set_index("date")
    return eq, pd.DataFrame(trades)


def _close(pos: Position, date, price, reason) -> dict:
    pnl = (price - pos.entry_price) * pos.shares
    return {
        "symbol": pos.symbol,
        "entry_date": pos.entry_date,
        "exit_date": date,
        "entry": pos.entry_price,
        "exit": price,
        "shares": pos.shares,
        "pnl": pnl,
        "pct": (price / pos.entry_price - 1.0) * 100.0,
        "days": (pd.Timestamp(date) - pd.Timestamp(pos.entry_date)).days,
        "reason": reason,
    }


# ---------------------------------------------------------------- metrics

def metrics(eq: pd.DataFrame, trades: pd.DataFrame, label: str) -> dict:
    e = eq["equity"]
    start, end = e.iloc[0], e.iloc[-1]
    years = max((pd.Timestamp(e.index[-1]) - pd.Timestamp(e.index[0])).days / 365.25, 1e-9)
    cagr = (end / start) ** (1 / years) - 1 if start > 0 else np.nan
    dd = (e / e.cummax() - 1.0).min()
    rets = e.pct_change().dropna()
    sharpe = (rets.mean() / rets.std() * np.sqrt(252)) if rets.std() > 0 else np.nan

    out = {
        "label": label,
        "total_return_pct": (end / start - 1) * 100,
        "cagr_pct": cagr * 100,
        "max_drawdown_pct": dd * 100,
        "sharpe": sharpe,
        "final_equity": end,
        "years": years,
    }
    if trades is not None and len(trades):
        w = trades[trades.pnl > 0]
        l = trades[trades.pnl <= 0]
        gp, gl = w.pnl.sum(), -l.pnl.sum()
        out.update({
            "n_trades": len(trades),
            "win_rate_pct": len(w) / len(trades) * 100,
            "avg_win_pct": w.pct.mean() if len(w) else 0.0,
            "avg_loss_pct": l.pct.mean() if len(l) else 0.0,
            "profit_factor": (gp / gl) if gl > 0 else np.inf,
            "avg_hold_days": trades.days.mean(),
        })
    return out


def buy_and_hold(df: pd.DataFrame, cash: float) -> pd.DataFrame:
    px = df["close"].dropna()
    return pd.DataFrame({"equity": cash * px / px.iloc[0], "cash": 0.0, "n_pos": 1})


def equal_weight_hold(panels: dict[str, pd.DataFrame], cash: float, dates) -> pd.DataFrame:
    """Equal-weight buy-and-hold of every symbol with data on the first date."""
    first = dates[0]
    syms = [s for s, d in panels.items() if first in d.index and not np.isnan(d.loc[first, "close"])]
    per = cash / len(syms)
    shares = {s: per / panels[s].loc[first, "close"] for s in syms}
    vals = []
    for d in dates:
        v = 0.0
        for s in syms:
            df = panels[s]
            if d in df.index and not np.isnan(df.loc[d, "close"]):
                v += shares[s] * df.loc[d, "close"]
            else:
                sub = df["close"].dropna()
                sub = sub[sub.index <= d]
                if len(sub):
                    v += shares[s] * sub.iloc[-1]
        vals.append((d, v))
    return pd.DataFrame(vals, columns=["date", "equity"]).set_index("date")
