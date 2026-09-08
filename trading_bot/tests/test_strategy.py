from trading_bot.strategy import evaluate


def test_buy_signal_on_oversold_dip():
    closes = [20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6]
    signal = evaluate("XYZ", closes)
    assert signal.action == "buy"


def test_sell_signal_on_overbought_rip():
    closes = [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]
    signal = evaluate("XYZ", closes)
    assert signal.action == "sell"


def test_hold_on_insufficient_data():
    signal = evaluate("XYZ", [10, 11])
    assert signal.action == "hold"
