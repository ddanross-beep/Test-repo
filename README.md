# Test-repo

## Trading bot

A momentum ("buy low, sell high") stock scanner/trader built on Robinhood's
API via `robin_stocks`. It scans the day's top movers, computes RSI on each,
and flags oversold dips as buy candidates and overbought run-ups as sell
candidates.

### Setup

```bash
pip install -r requirements.txt
export ROBINHOOD_USERNAME=you@example.com
export ROBINHOOD_PASSWORD=your-password
export ROBINHOOD_MFA_CODE=123456  # if MFA is enabled
```

### Usage

Dry run (default — prints signals, places no orders):

```bash
python -m trading_bot.cli
```

Live trading (places real market orders, confirms each one unless `--yes`):

```bash
python -m trading_bot.cli --live --quantity 1
```

Run `python -m trading_bot.cli --help` for all options.

**This places real orders with real money when run with `--live`.** Start
with dry runs, understand the strategy in `trading_bot/strategy.py`, and use
small quantities before trusting it with size.

### Tests

```bash
python -m pytest trading_bot/tests
```
