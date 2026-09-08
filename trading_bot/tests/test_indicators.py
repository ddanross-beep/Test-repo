from trading_bot.indicators import percent_change, rsi


def test_rsi_none_when_insufficient_data():
    assert rsi([1.0, 2.0, 3.0], period=14) is None


def test_rsi_all_gains_is_100():
    closes = [float(i) for i in range(1, 20)]  # strictly increasing
    assert rsi(closes, period=14) == 100.0


def test_rsi_all_losses_is_0():
    closes = [float(i) for i in range(20, 1, -1)]  # strictly decreasing
    assert rsi(closes, period=14) == 0.0


def test_rsi_mixed_series_between_0_and_100():
    closes = [10, 11, 9, 12, 8, 13, 7, 14, 6, 15, 5, 16, 4, 17, 3]
    value = rsi(closes, period=14)
    assert value is not None
    assert 0.0 <= value <= 100.0


def test_percent_change_basic():
    assert percent_change([100.0, 110.0]) == 10.0


def test_percent_change_needs_two_points():
    assert percent_change([100.0]) is None
