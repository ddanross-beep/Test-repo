# Backtests

Scripts behind the strategy decisions. Price data is not committed; it was
pulled from Robinhood's `get_equity_historicals` (interval `day`, adjustment
`split`, with interpolated pre-launch bars dropped) into `data/`, `data_long/`
and `etf_split/` directories next to these scripts.

- `engine.py`, `run.py` — the original stock-picking bot (RSI dip / momentum
  continuation with ATR stops) on a 200-symbol universe. Result: ties SPY at
  best, fragile to costs and parameters.
- `etf_bt.py` — monthly ETF allocation models 2008→now: buy & hold, trend
  (10-month SMA), dual momentum, GTAA, vol-targeting, factor ETFs.
- `lev_bt.py` — the same rules on synthetic 2x/3x QQQ (daily-rebalanced,
  minus financing at the SHY rate and a 0.95% expense ratio).

Headline (2008–2026, ex-dividends, 0.05%/side):

| Model | CAGR | Max DD | Sharpe |
|---|---|---|---|
| QQQ buy & hold | 15.9% | −49% | 0.78 |
| Vol-target 20% QQQ/SHY | 15.6% | −33% | 0.90 |
| Vol-target 30% via 3x/SHY | 27.6% | −46% | 0.88 |
| Vol-target 40% via 3x/SHY | 33.2% | −58% | 0.88 |
| 3x buy & hold | 32.6% | −92% | 0.76 |

The live routine prompt is in `../routines/vol_target_tqqq.md`.
