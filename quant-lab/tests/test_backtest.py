import numpy as np
import pandas as pd
import pytest

from quantlab import run_backtest
from quantlab import strategies as st
from quantlab.data import synthetic_prices


@pytest.fixture
def prices():
    return synthetic_prices(["A"], n_days=600, seed=1)["A"]


def test_buy_and_hold_matches_asset_without_fees(prices):
    res = run_backtest(prices, st.buy_and_hold(prices), fee_bps=0)
    assert res.equity.iloc[-1] == pytest.approx(prices.iloc[-1] / prices.iloc[0])


def test_entry_fee_is_charged_once(prices):
    res = run_backtest(prices, st.buy_and_hold(prices), fee_bps=10)
    assert res.trades == 1
    assert res.costs.sum() == pytest.approx(0.001)


def test_round_trip_costs_two_fees():
    idx = pd.bdate_range("2020-01-01", periods=6)
    p = pd.Series(100.0, index=idx)
    sig = pd.Series([0, 1, 1, 0, 0, 0], index=idx, dtype=float)
    res = run_backtest(p, sig, fee_bps=25)
    assert res.trades == 2
    assert res.equity.iloc[-1] == pytest.approx((1 - 0.0025) ** 2)


def test_signal_is_held_from_the_next_day():
    """第 t 天的訊號只能賺第 t+1 天的報酬。"""
    idx = pd.bdate_range("2020-01-01", periods=5)
    p = pd.Series([100, 110, 99, 120, 120], index=idx, dtype=float)
    sig = pd.Series([0, 1, 0, 0, 0], index=idx, dtype=float)  # 第 1 天收盤決定買
    res = run_backtest(p, sig, fee_bps=0)
    assert res.returns.iloc[1] == 0  # 當天的 +10% 不屬於策略
    assert res.returns.iloc[2] == pytest.approx(99 / 110 - 1)  # 隔天的漲跌才算
    assert (res.returns.iloc[3:] == 0).all()


def test_lookahead_inflates_results(prices):
    peek = (prices.pct_change() > 0).astype(float)
    honest = run_backtest(prices, peek, fee_bps=0).summary()["cagr"]
    cheat = run_backtest(prices, peek, fee_bps=0, execution_lag=0).summary()["cagr"]
    assert cheat > honest + 0.5


def test_multi_asset_weights():
    df = synthetic_prices(["A", "B"], n_days=300, seed=3)
    w = pd.DataFrame(0.5, index=df.index, columns=df.columns)
    res = run_backtest(df, w, fee_bps=0)
    expected = 0.5 * df.pct_change().fillna(0).sum(axis=1)
    expected.iloc[0] = 0.0
    expected.iloc[1] = 0.5 * df.pct_change().iloc[1].sum()
    pd.testing.assert_series_equal(res.returns.iloc[1:], expected.iloc[1:], check_names=False)


def test_strategies_return_valid_positions(prices):
    for name, fn in st.STRATEGIES.items():
        sig = fn(prices)
        assert sig.index.equals(prices.index), name
        assert sig.notna().all(), name
        assert sig.between(0, 1).all(), name


def test_sma_crossover_rejects_bad_params(prices):
    with pytest.raises(ValueError):
        st.sma_crossover(prices, fast=200, slow=50)


def test_weights_drift_between_rebalances():
    """兩檔各 50%，一檔漲一倍、另一檔不動：沒再平衡時權重會漂成 2/3 與 1/3。"""
    idx = pd.bdate_range("2020-01-01", periods=4)
    df = pd.DataFrame({"A": [100, 100, 200, 200], "B": [100, 100, 100, 100]}, index=idx, dtype=float)
    w = pd.DataFrame(np.nan, index=idx, columns=df.columns)
    w.iloc[0] = 0.5  # 只在第一天設定目標，之後不交易
    res = run_backtest(df, w, fee_bps=0)
    assert res.positions.iloc[3]["A"] == pytest.approx(2 / 3)
    assert res.equity.iloc[-1] == pytest.approx(1.5)


def test_rebalancing_costs_reflect_drift():
    idx = pd.bdate_range("2020-01-01", periods=5)
    df = pd.DataFrame({"A": [100, 100, 200, 200, 200], "B": [100.0] * 5}, index=idx, dtype=float)
    w = pd.DataFrame(np.nan, index=idx, columns=df.columns)
    w.iloc[0] = 0.5
    w.iloc[3] = 0.5  # 漂移後拉回 50/50：A 從 2/3 賣到 1/2，B 從 1/3 買到 1/2
    res = run_backtest(df, w, fee_bps=100)
    assert res.turnover.iloc[4] == pytest.approx(1 / 3)
    assert res.costs.iloc[4] == pytest.approx(1 / 3 * 0.01)


def test_daily_and_sparse_paths_agree():
    """每天都給目標時，快速版和逐日版的算法要得到一樣的結果。"""
    from quantlab.backtest import _simulate_daily, _simulate_sparse

    df = synthetic_prices(["A", "B"], n_days=300, seed=5)
    rng = np.random.default_rng(1)
    targets = rng.uniform(0, 0.5, size=df.shape)
    r = df.pct_change().fillna(0).to_numpy()
    for a, b in zip(_simulate_daily(targets, r, 0.001), _simulate_sparse(targets, r, 0.001)):
        np.testing.assert_allclose(a, b)
