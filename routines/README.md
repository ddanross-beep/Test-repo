# Routine prompts

| File | Status | What it is |
|---|---|---|
| `vol_target_tqqq.md` | **LIVE** | Vol-targeted TQQQ/SHY, monthly rebalance. 27.6% CAGR / −46% DD backtested 2008–2026. |
| `stock_bot_waterfall.md` | retired | Model B momentum → Model A dip-buy → park in VOO. Tied SPY in backtest. |
| `stock_bot_hybrid_research.md` | retired | Model A with web/news research gate. |
| `stock_bot_hybrid_v1.md` | retired | First NNFX-style trend + ATR-stop version. |

To switch bots: paste the prompt (everything below the `---` line) over the
Routine's instructions in claude.ai. Update `BASELINE_VALUE` on every deposit.
