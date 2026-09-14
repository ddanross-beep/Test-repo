# Stock bot — NNFX-style hybrid (first version) — Routine prompt

First trend-filter + ATR-stop version of the stock bot (Sept 10, 2026).
Superseded. Kept for reference.

---

Run one hybrid trend/mean-reversion bot cycle, autonomously, no confirmation needed.

SETTINGS (edit these numbers, nothing else, when you change the account):
  BASELINE_VALUE = 198.52   <- account value when the bot started; update on every deposit/withdrawal
  RISK_PCT = 0.02           <- fraction of account value risked per trade if its stop is hit
  ATR_MULT = 2              <- stop distance = ATR_MULT x ATR(14, daily)
  MAX_POSITION_PCT = 0.50   <- no single position larger than this fraction of account value
  MAX_POSITIONS = 3         <- total open positions, BBAI included

0. CIRCUIT BREAKER: get_portfolio for account 788337921. If total_value < BASELINE_VALUE x 0.85,
   log "circuit breaker: account down >15%, halting" and STOP. Otherwise continue.

1. DATA: run scan "Momentum Bot - Hybrid Buy (Dip in Uptrend)" (scan_id 3fc3aad9-20c8-49b8-b742-ce8727ec849e)
   and scan "Momentum Bot - Hybrid Exit (Overbought)" (scan_id 1910e84f-5099-43d7-b4d1-30b406cfe566).
   Each row carries columns "RSI", "Average true range" (= ATR 14-day) and "SMA 200D".
   Then get_equity_positions (symbol, quantity, average_buy_price), get_portfolio (buying power, total_value),
   and get_equity_orders with state=confirmed (resting stop orders per symbol).

2. EXITS - for every held position EXCEPT BBAI (BBAI keeps its own manual bracket orders; never touch it):
   a. get_equity_quotes for the current price, and get_equity_technical_indicators type=sma period=200
      interval=day output=latest (start_time ~1 year back) for its 200-day SMA.
   b. TREND BREAK: if current price < 200-day SMA -> cancel that symbol's resting stop order (if any),
      then sell the full position at market (review_equity_order first). Log "trend-break exit".
   c. OVERBOUGHT: if the symbol appears in the Hybrid Exit scan -> cancel its resting stop, sell the full
      position at market (review first). Log "overbought exit".
   d. BACKSTOP: if current price <= average_buy_price - ATR_MULT x ATR and there is NO resting stop order
      covering it -> sell at market (review first). Log "stop backstop exit".
   Never place a sell for more shares than shares_available_for_sells; if shares are held by a resting
   stop order, cancel that order first and re-read positions.

3. ENTRY - at most ONE new buy per cycle:
   a. Re-read get_portfolio (live buying power + total_value) and count open positions. If positions
      >= MAX_POSITIONS or buying power < $10, log "no capacity" and skip to step 4.
   b. From the Hybrid Buy scan, take the lowest-RSI symbol that is not already held and has a non-empty
      "Average true range". Call it SYM with price P and ATR A.
   c. SIZE (whole shares only - never use dollar_amount):
        risk_dollars   = RISK_PCT x total_value
        stop_distance  = ATR_MULT x A
        shares_by_risk = floor(risk_dollars / stop_distance)
        shares_by_cap  = floor(MAX_POSITION_PCT x total_value / P)
        shares_by_cash = floor(buying_power / P)
        shares         = min(shares_by_risk, shares_by_cap, shares_by_cash)
      If shares < 1, log "too small to size" and skip to step 4.
   d. review_equity_order then place_equity_order: buy SYM, type=market, quantity=shares (whole number).
      Confirm the fill with get_equity_orders and read average_price.
   e. IMMEDIATELY place a GTC stop-market sell for the full filled quantity at
      stop_price = round(average_price - stop_distance, 2). Review first. Log the stop price.

4. LOG a short summary: every exit (symbol, reason, P/L %), any new buy (symbol, RSI, ATR, shares,
   dollars, stop price), open positions, buying power, and total_value vs BASELINE_VALUE.
   If nothing was actionable, say so and stop - never force a trade.

Rules: only act on tickers returned by this cycle's scans; whole shares only; one new buy per cycle;
BBAI is hands-off; if Robinhood tools are unavailable, log it and stop.
