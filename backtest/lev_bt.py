"""Aggressive variants: leveraged QQQ (synthetic 2x/3x daily-rebalanced) with trend / vol-target rules."""
import sys, os
import numpy as np, pandas as pd
sys.argv = [sys.argv[0], "etf_split"]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import etf_bt as E

closes, meta = E.load_closes()
closes = closes.drop(columns=[c for c in ["EEM"] if c in closes])
E.sanity_check(closes)
slip = 0.0005

# synthetic leveraged QQQ: L x daily return minus financing on borrowed (L-1) at SHY (T-bill proxy) minus expense ratio
qqq = closes["QQQ"].pct_change()
cash = closes["SHY"].pct_change().fillna(0.0)
def synth(L, expense=0.0095):
    r = L * qqq - (L - 1) * cash - expense / 252
    px = (1 + r.fillna(0.0)).cumprod() * 100
    return px
closes = closes.copy()
closes["QQQ2X"] = synth(2)
closes["QQQ3X"] = synth(3)
closes = closes.dropna(subset=["QQQ", "SHY"])
me = E.month_ends(closes.index)

def w_trend_lev(risk_signal, hold, safe, lookback=10):
    t = E.w_trend(closes, risk_signal, safe, me, lookback)  # 1/0 on the signal symbol
    w = pd.DataFrame(0.0, index=t.index, columns=[hold, safe])
    w[hold] = t[risk_signal].values
    w[safe] = 1.0 - w[hold]
    return w

spec = [
    ("QQQ buy&hold", E.w_buy_hold(closes, "QQQ", me)),
    ("QQQ 2x buy&hold (synthetic QLD)", E.w_buy_hold(closes, "QQQ2X", me)),
    ("QQQ 3x buy&hold (synthetic TQQQ)", E.w_buy_hold(closes, "QQQ3X", me)),
    ("VOL-TARGET QQQ 20%/SHY (baseline)", E.w_vol_target(closes, "QQQ", "SHY", me, 0.20)),
    ("VOL-TARGET QQQ 30% via 2x/SHY", E.w_vol_target(closes, "QQQ2X", "SHY", me, 0.30)),
    ("VOL-TARGET QQQ 30% via 3x/SHY", E.w_vol_target(closes, "QQQ3X", "SHY", me, 0.30)),
    ("VOL-TARGET QQQ 40% via 3x/SHY", E.w_vol_target(closes, "QQQ3X", "SHY", me, 0.40)),
    ("VOL-TARGET QQQ 50% via 3x/SHY", E.w_vol_target(closes, "QQQ3X", "SHY", me, 0.50)),
    ("TREND QQQ 10mo -> hold 2x else SHY", w_trend_lev("QQQ", "QQQ2X", "SHY")),
    ("TREND QQQ 10mo -> hold 3x else SHY", w_trend_lev("QQQ", "QQQ3X", "SHY")),
]
# trend + vol-target on 3x
def w_trend_vol(hold, target, lookback=10):
    t = E.w_trend(closes, "QQQ", "SHY", me, lookback)
    v = E.w_vol_target(closes, hold, "SHY", me, target)
    idx = t.index.intersection(v.index)
    w = pd.DataFrame(0.0, index=idx, columns=[hold, "SHY"])
    w[hold] = np.where(t.loc[idx, "QQQ"] > 0, v.loc[idx, hold], 0.0)
    w["SHY"] = 1 - w[hold]
    return w
spec += [
    ("TREND+VOL 30% via 3x/SHY", w_trend_vol("QQQ3X", 0.30)),
    ("TREND+VOL 40% via 3x/SHY", w_trend_vol("QQQ3X", 0.40)),
    ("TREND+VOL 40% via 2x/SHY", w_trend_vol("QQQ2X", 0.40)),
]

print("=== 2008-01 -> now, ex-dividends, 0.05%/side ===")
df, curves = E.evaluate(closes, spec, "2008-01-01", slip)
E.show(df)

print("\n=== crisis windows (total return %) ===")
wins = {"2008 crash": ("2008-01-01", "2009-03-09"), "2020 covid": ("2020-02-19", "2020-03-23"),
        "2022 bear": ("2022-01-03", "2022-12-30"), "2023-now": ("2023-01-03", "2026-12-31")}
rows = []
for label, eq in curves.items():
    rows.append({"label": label, **{k: round(E.window_ret(eq, a, b), 1) for k, (a, b) in wins.items()}})
print(pd.DataFrame(rows).to_string(index=False))

print("\n=== calendar years ===")
yr = pd.DataFrame({l: eq.groupby(eq.index.year).apply(lambda s: (s.iloc[-1]/s.iloc[0]-1)*100)
                   for l, eq in curves.items()}).round(1)
print(yr.T.to_string())

print("\n=== stability: TREND+VOL via 3x, lookback x target ===")
rows = []
for lb in (8, 10, 12):
    for tg in (0.30, 0.40, 0.50):
        d, _ = E.evaluate(closes, [(f"lb{lb}/tg{int(tg*100)}", w_trend_vol("QQQ3X", tg, lb))], "2008-01-01", slip)
        rows.append(d.iloc[0])
E.show(pd.DataFrame(rows))

print("\n=== cost sensitivity: TREND+VOL 40% via 3x ===")
for s in (0.0, 0.0005, 0.002, 0.004):
    d, _ = E.evaluate(closes, [(f"slip {s*100:.2f}%", w_trend_vol("QQQ3X", 0.40))], "2008-01-01", s)
    E.show(d)
