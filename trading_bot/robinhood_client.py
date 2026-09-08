"""Thin wrapper around robin_stocks for the pieces this bot needs.

Credentials are read from environment variables (ROBINHOOD_USERNAME,
ROBINHOOD_PASSWORD, ROBINHOOD_MFA_CODE) so they never live in code or
version control.
"""
from __future__ import annotations

import os

import robin_stocks.robinhood as rh


class RobinhoodClient:
    def __init__(self) -> None:
        self._logged_in = False

    def login(self) -> None:
        if self._logged_in:
            return
        username = os.environ.get("ROBINHOOD_USERNAME")
        password = os.environ.get("ROBINHOOD_PASSWORD")
        mfa_code = os.environ.get("ROBINHOOD_MFA_CODE")
        if not username or not password:
            raise RuntimeError(
                "Set ROBINHOOD_USERNAME and ROBINHOOD_PASSWORD environment "
                "variables before running the bot."
            )
        rh.login(username=username, password=password, mfa_code=mfa_code)
        self._logged_in = True

    def logout(self) -> None:
        if self._logged_in:
            rh.logout()
            self._logged_in = False

    def top_movers(self, direction: str = "up", count: int = 20) -> list[dict]:
        """Return the day's top movers, most active first."""
        self.login()
        movers = rh.get_top_movers(direction=direction) or []
        return movers[:count]

    def closing_prices(self, symbol: str, interval: str = "5minute", span: str = "day") -> list[float]:
        self.login()
        historicals = rh.get_stock_historicals(symbol, interval=interval, span=span) or []
        return [float(bar["close_price"]) for bar in historicals if bar.get("close_price")]

    def quote(self, symbol: str) -> dict:
        self.login()
        return rh.get_quote(symbol) or {}

    def place_buy(self, symbol: str, quantity: float) -> dict:
        self.login()
        return rh.order_buy_market(symbol, quantity)

    def place_sell(self, symbol: str, quantity: float) -> dict:
        self.login()
        return rh.order_sell_market(symbol, quantity)
