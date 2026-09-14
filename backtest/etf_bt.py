"""ETF allocation strategies: signals at month-end close, held through the next month.

Everything is evaluated on a daily equity curve. Weights decided at a month-end close
apply from the next trading day, so no signal ever sees the bar it trades on.
"""
from __future__ import annotations

import glob
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, sys.argv[1] if len(sys.argv) > 1 else "etf")
START_CASH = 10000.0


def sanity_check(closes: pd.DataFrame) -> None:
    """Refuse to run on corrupted prices: non-positive closes or absurd daily moves."""
    bad_nonpos = (closes <= 0).sum()
    r = closes.pct_change()
    # VNQ genuinely rose 30.0% on 2008-10-13; nothing broad moves 35% in a day without a data glitch
    bad_big = (r.abs() > 0.35).sum()
    problems = []
    for s in closes.columns:
        if bad_nonpos[s] or bad_big[s]:
            problems.append(f"{s}: {int(bad_nonpos[s])} non-positive closes, {int(bad_big[s])} days |ret|>30%")
    if problems:
        print("DATA SANITY FAILED:\n  " + "\n  ".join(problems))
        sys.exit(2)
    print("data sanity: OK (no non-positive closes, no |daily return| > 30%)")


# ---------------------------------------------------------------- data

def load_closes() -> tuple[pd.DataFrame, dict]:
    frames: dict[str, list[pd.DataFrame]] = {}
    meta: dict[str, set] = {}
    for path in sorted(glob.glob(os.path.join(DATA, "*.json"))):
        with open(path) as fh:
            blob = json.load(fh)
        for res in blob.get("data", {}).get("results", []):
            sym, bars = res.get("symbol"), res.get("bars") or []
            if not sym or not bars:
                continue
            df = pd.DataFrame(bars)
            # the API back-fills synthetic bars before an ETF's launch; they carry no information
            if "interpolated" in df.columns:
                df = df[df["interpolated"] != True]  # noqa: E712
            if df.empty:
                continue
            df["date"] = pd.to_datetime(df["begins_at"]).dt.tz_localize(None).dt.normalize()
            df["close"] = pd.to_numeric(df["close_price"], errors="coerce")
            frames.setdefault(sym, []).append(df[["date", "close"]])
            meta.setdefault(sym, set()).add(os.path.basename(path))
    series = {}
    for sym, parts in frames.items():
        s = pd.concat(parts).dropna().drop_duplicates("date").set_index("date")["close"].sort_index()
        series[sym] = s
    closes = pd.DataFrame(series).sort_index()
    return closes, meta


# ---------------------------------------------------------------- helpers

def month_ends(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    s = pd.Series(index, index=index)
    return pd.DatetimeIndex(s.groupby([index.year, index.month]).last().values)


def run_weights(closes: pd.DataFrame, weights: pd.DataFrame, slippage: float) -> pd.Series:
    """weights: rows at decision dates (month-ends), columns = symbols, sum<=1 (rest cash at 0%).
    Returns daily equity."""
    rets = closes.pct_change().fillna(0.0)
    w_daily = weights.reindex(rets.index).shift(1).ffill().fillna(0.0)   # apply from next day
    first = weights.index[0]
    rets = rets[rets.index > first]
    w_daily = w_daily.loc[rets.index]
    port = (w_daily * rets[w_daily.columns]).sum(axis=1)
    # transaction cost on rebalance days: slippage x turnover
    w_change = weights.diff().abs().sum(axis=1).fillna(weights.iloc[0].abs().sum())
    cost = pd.Series(0.0, index=rets.index)
    # cost lands on the first trading day after each decision date
    nxt = rets.index.searchsorted(weights.index, side="right")
    for i, pos in enumerate(nxt):
        if pos < len(rets.index):
            cost.iloc[pos] += slippage * w_change.iloc[i]
    eq = START_CASH * (1.0 + port - cost).cumprod()
    return eq


def metrics(eq: pd.Series, label: str, n_rebalances: int | None = None) -> dict:
    eq = eq.dropna()
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1
    dd = (eq / eq.cummax() - 1.0)
    r = eq.pct_change().dropna()
    sharpe = r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else np.nan
    yearly = eq.groupby(eq.index.year).apply(lambda s: s.iloc[-1] / s.iloc[0] - 1)
    return {
        "label": label,
        "total_pct": (eq.iloc[-1] / eq.iloc[0] - 1) * 100,
        "cagr_pct": cagr * 100,
        "max_dd_pct": dd.min() * 100,
        "sharpe": sharpe,
        "worst_year_pct": yearly.min() * 100,
        "best_year_pct": yearly.max() * 100,
        "years": yrs,
        "rebalances": n_rebalances,
    }


def window_ret(eq: pd.Series, a: str, b: str) -> float:
    s = eq[(eq.index >= a) & (eq.index <= b)]
    return (s.iloc[-1] / s.iloc[0] - 1) * 100 if len(s) > 1 else np.nan


# ---------------------------------------------------------------- strategies
# each returns a weights DataFrame indexed by month-end decision dates

def w_buy_hold(closes, sym, me):
    w = pd.DataFrame(0.0, index=me, columns=[sym]); w[sym] = 1.0
    return w


def w_fixed_mix(closes, mix: dict, me):
    w = pd.DataFrame(0.0, index=me, columns=list(mix))
    for k, v in mix.items():
        w[k] = v
    return w


def w_trend(closes, risk, safe, me, lookback=10):
    m = closes[risk].reindex(me)
    sma = m.rolling(lookback).mean()
    on = (m > sma)
    w = pd.DataFrame(0.0, index=me, columns=[risk, safe])
    w.loc[on, risk] = 1.0
    w.loc[~on & sma.notna(), safe] = 1.0
    return w[sma.notna()]


def w_gtaa(closes, assets, safe, me, lookback=10):
    cols = list(dict.fromkeys(assets + [safe]))
    w = pd.DataFrame(0.0, index=me, columns=cols)
    valid = pd.Series(True, index=me)
    for a in assets:
        m = closes[a].reindex(me)
        sma = m.rolling(lookback).mean()
        on = m > sma
        w.loc[on, a] += 1.0 / len(assets)
        w.loc[~on & sma.notna(), safe] += 1.0 / len(assets)
        valid &= sma.notna()
    return w[valid]


def w_dual_momentum(closes, risk_syms, safe, cash, me, lookback=12):
    m = closes.reindex(me)
    mom = m.pct_change(lookback)
    cols = list(dict.fromkeys(risk_syms + [safe]))
    w = pd.DataFrame(0.0, index=me, columns=cols)
    valid = mom[risk_syms + [cash]].notna().all(axis=1)
    mv = mom.loc[valid, risk_syms]
    best = mv.idxmax(axis=1)
    best_ret = mv.max(axis=1)
    for d in me[valid]:
        if best_ret[d] > mom.loc[d, cash]:
            w.loc[d, best[d]] = 1.0
        else:
            w.loc[d, safe] = 1.0
    return w[valid]


def w_vol_target(closes, risk, safe, me, target=0.15, lookback=21, max_lev=1.0):
    r = closes[risk].pct_change()
    vol = r.rolling(lookback).std() * np.sqrt(252)
    v = vol.reindex(me)
    exp = (target / v).clip(upper=max_lev)
    w = pd.DataFrame(0.0, index=me, columns=[risk, safe])
    w[risk] = exp
    w[safe] = 1.0 - exp
    return w[v.notna()]


# ---------------------------------------------------------------- main

def evaluate(closes, spec: list[tuple[str, pd.DataFrame]], start: str, slippage: float):
    rows, curves = [], {}
    for label, w in spec:
        w = w[w.index >= pd.Timestamp(start)]
        if len(w) < 12:
            continue
        need = [c for c in w.columns if (w[c] != 0).any()]
        c = closes[need].dropna()
        w = w[w.index >= c.index[0]]
        eq = run_weights(c, w, slippage)
        curves[label] = eq
        n_rb = int((w.diff().abs().sum(axis=1) > 1e-9).sum())
        rows.append(metrics(eq, label, n_rb))
    return pd.DataFrame(rows), curves


def show(df: pd.DataFrame):
    cols = ["label", "total_pct", "cagr_pct", "max_dd_pct", "sharpe", "worst_year_pct",
            "best_year_pct", "years", "rebalances"]
    d = df.reindex(columns=cols).copy()
    for c in cols[1:]:
        d[c] = pd.to_numeric(d[c], errors="coerce").round(2)
    pd.set_option("display.width", 220, "display.max_columns", 30)
    print(d.to_string(index=False, na_rep="-"))


def main():
    closes, meta = load_closes()
    # EEM carries an unadjusted 3:1 split discontinuity in this feed and no strategy uses it
    closes = closes.drop(columns=[c for c in ["EEM"] if c in closes.columns])
    print("data dir:", DATA)
    print("symbols:", ", ".join(f"{s} {closes[s].first_valid_index().date()}" for s in closes.columns))
    sanity_check(closes)
    me = month_ends(closes.index)
    slip = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0005

    spec_long = [
        ("SPY buy & hold",                         w_buy_hold(closes, "SPY", me)),
        ("QQQ buy & hold",                         w_buy_hold(closes, "QQQ", me)),
        ("60/40 SPY/AGG monthly",                  w_fixed_mix(closes, {"SPY": .6, "AGG": .4}, me)),
        ("TREND SPY>10mo SMA else AGG",            w_trend(closes, "SPY", "AGG", me, 10)),
        ("TREND SPY>10mo SMA else SHY",            w_trend(closes, "SPY", "SHY", me, 10)),
        ("TREND QQQ>10mo SMA else AGG",            w_trend(closes, "QQQ", "AGG", me, 10)),
        ("GTAA5 SPY/EFA/AGG/VNQ/DBC 10mo",         w_gtaa(closes, ["SPY", "EFA", "AGG", "VNQ", "DBC"], "SHY", me, 10)),
        ("DUAL MOM SPY/EFA vs SHY, else AGG 12mo", w_dual_momentum(closes, ["SPY", "EFA"], "AGG", "SHY", me, 12)),
        ("DUAL MOM SPY/QQQ/EFA vs SHY, else AGG",  w_dual_momentum(closes, ["SPY", "QQQ", "EFA"], "AGG", "SHY", me, 12)),
        ("DUAL MOM SPY/EFA vs SHY, else TLT",      w_dual_momentum(closes, ["SPY", "EFA"], "TLT", "SHY", me, 12)),
        ("VOL-TARGET SPY 15% else SHY",            w_vol_target(closes, "SPY", "SHY", me, 0.15)),
        ("VOL-TARGET SPY 20% else SHY",            w_vol_target(closes, "SPY", "SHY", me, 0.20)),
    ]

    for start, title in [("2008-01-01", "LONG WINDOW (includes 2008, 2020, 2022)"),
                         ("2014-01-01", "SINCE 2014 (adds factor ETFs)")]:
        spec = list(spec_long)
        if start >= "2014-01-01":
            spec += [(f"{f} factor buy & hold", w_buy_hold(closes, f, me)) for f in ["MTUM", "QUAL", "USMV", "VLUE"] if f in closes]
        res, curves = evaluate(closes, spec, start, slip)
        print("\n" + "=" * 120 + f"\n{title}   slippage {slip*100:.2f}%/side\n" + "=" * 120)
        show(res)
        if start == "2008-01-01":
            print("\nCRISIS WINDOWS (return over the window, %)")
            rows = []
            for label, eq in curves.items():
                rows.append({"label": label,
                             "2008 crash (Jan08-Mar09)": round(window_ret(eq, "2008-01-01", "2009-03-09"), 1),
                             "2020 covid (Feb-Mar20)": round(window_ret(eq, "2020-02-19", "2020-03-23"), 1),
                             "2022 bear (Jan-Oct22)": round(window_ret(eq, "2022-01-03", "2022-10-12"), 1),
                             "2023-24 bull": round(window_ret(eq, "2023-01-01", "2024-12-31"), 1)})
            print(pd.DataFrame(rows).to_string(index=False, na_rep="-"))

    # ---- parameter stability on the long window
    print("\n" + "=" * 120 + "\nPARAMETER STABILITY (long window)\n" + "=" * 120)
    stab = []
    for lb in (6, 8, 10, 12):
        stab.append((f"TREND SPY/AGG lookback {lb}mo", w_trend(closes, "SPY", "AGG", me, lb)))
    for lb in (6, 9, 12):
        stab.append((f"DUAL MOM SPY/EFA lookback {lb}mo", w_dual_momentum(closes, ["SPY", "EFA"], "AGG", "SHY", me, lb)))
    for t in (0.10, 0.15, 0.20):
        stab.append((f"VOL-TARGET SPY {int(t*100)}%", w_vol_target(closes, "SPY", "SHY", me, t)))
    res, _ = evaluate(closes, stab, "2008-01-01", slip)
    show(res)

    # ---- cost sensitivity
    print("\n" + "=" * 120 + "\nCOST SENSITIVITY (long window): TREND SPY/AGG 10mo and DUAL MOM 12mo\n" + "=" * 120)
    for s in (0.0, 0.0005, 0.002, 0.005):
        res, _ = evaluate(closes, [("TREND SPY/AGG 10mo", w_trend(closes, "SPY", "AGG", me, 10)),
                                   ("DUAL MOM SPY/EFA 12mo", w_dual_momentum(closes, ["SPY", "EFA"], "AGG", "SHY", me, 12)),
                                   ("SPY buy & hold", w_buy_hold(closes, "SPY", me))], "2008-01-01", s)
        res.insert(0, "slip_per_side_pct", s * 100)
        show(res.assign(label=res.label + f"  @{s*100:.2f}%"))


if __name__ == "__main__":
    main()
