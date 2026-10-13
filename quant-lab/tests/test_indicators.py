import numpy as np
import pandas as pd
import pytest

from quantlab import indicators as ind


@pytest.fixture
def prices():
    idx = pd.bdate_range("2020-01-01", periods=10)
    return pd.Series([10, 11, 12, 11, 13, 14, 13, 15, 16, 17], index=idx, dtype=float)


def test_sma_needs_full_window(prices):
    out = ind.sma(prices, 3)
    assert out.iloc[:2].isna().all()
    assert out.iloc[2] == pytest.approx(11.0)
    assert out.iloc[-1] == pytest.approx(16.0)


def test_log_returns_sum_to_total(prices):
    total = np.expm1(ind.log_returns(prices).sum())
    assert total == pytest.approx(prices.iloc[-1] / prices.iloc[0] - 1)


def test_rsi_bounds_and_extremes():
    idx = pd.bdate_range("2020-01-01", periods=40)
    up = pd.Series(np.arange(40, dtype=float) + 1, index=idx)
    assert ind.rsi(up).dropna().eq(100).all()
    assert ind.rsi(-up + 100).dropna().eq(0).all()
    flat = pd.Series(5.0, index=idx)
    assert ind.rsi(flat).dropna().eq(50).all()


def test_indicators_do_not_look_ahead(prices):
    """改動最後一天的價格，不能影響之前任何一天的指標值。"""
    changed = prices.copy()
    changed.iloc[-1] = 999.0
    for fn in (lambda s: ind.sma(s, 3), lambda s: ind.ema(s, 3), lambda s: ind.rsi(s, 3), lambda s: ind.momentum(s, 2)):
        a, b = fn(prices).iloc[:-1], fn(changed).iloc[:-1]
        pd.testing.assert_series_equal(a, b)


def test_drawdown():
    eq = pd.Series([1.0, 1.2, 0.9, 1.3, 1.04])
    dd = ind.drawdown(eq)
    assert dd.iloc[2] == pytest.approx(0.9 / 1.2 - 1)
    assert dd.iloc[3] == 0
    assert dd.min() == pytest.approx(-0.25)
