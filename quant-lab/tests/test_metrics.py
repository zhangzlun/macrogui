import numpy as np
import pandas as pd
import pytest

from quantlab import metrics


def test_cagr_of_constant_return():
    r = pd.Series([0.001] * 252)
    assert metrics.cagr(r) == pytest.approx(1.001**252 - 1)


def test_max_drawdown_includes_start():
    r = pd.Series([-0.1, 0.05, -0.2, 0.5])
    # 淨值 0.9, 0.945, 0.756, 1.134：最低點相對起始 1.0 跌了 24.4%
    assert metrics.max_drawdown(r) == pytest.approx(0.756 - 1)


def test_sharpe_is_nan_without_volatility():
    assert np.isnan(metrics.sharpe_ratio(pd.Series([0.0] * 50)))


def test_sharpe_sign():
    rng = np.random.default_rng(0)
    r = pd.Series(rng.normal(0.001, 0.01, 1000))
    assert metrics.sharpe_ratio(r) > 0
    assert metrics.sharpe_ratio(-r) < 0


def test_win_rate_ignores_flat_days():
    assert metrics.win_rate(pd.Series([0.0, 0.01, -0.01, 0.02, 0.0])) == pytest.approx(2 / 3)
