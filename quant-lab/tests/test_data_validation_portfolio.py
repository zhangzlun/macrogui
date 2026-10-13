import pandas as pd
import pytest

from quantlab import portfolio as pf
from quantlab import strategies as st
from quantlab.data import load_csv, load_prices, synthetic_prices
from quantlab.validation import grid_search, train_test_compare, walk_forward


def test_synthetic_is_reproducible_and_positive():
    a = synthetic_prices(["X", "Y"], n_days=500, seed=7)
    b = synthetic_prices(["X", "Y"], n_days=500, seed=7)
    pd.testing.assert_frame_equal(a, b)
    assert (a > 0).all().all()
    assert list(a.columns) == ["X", "Y"]


def test_csv_roundtrip(tmp_path):
    df = synthetic_prices(["X"], n_days=50)
    path = tmp_path / "p.csv"
    df.to_csv(path)
    pd.testing.assert_frame_equal(load_csv(path), df, check_freq=False)
    assert len(load_prices("X", start="2010-02-01", source="csv", csv_path=path)) < 50


def test_grid_search_skips_invalid_combinations():
    p = synthetic_prices(["X"], n_days=800)["X"]
    out = grid_search(p, st.sma_crossover, {"fast": [10, 300], "slow": [50, 100]})
    assert len(out) == 2
    assert out["sharpe"].is_monotonic_decreasing


def test_train_test_compare_ranks():
    p = synthetic_prices(["X"], n_days=1500)["X"]
    t = train_test_compare(p, st.sma_crossover, {"fast": [10, 20], "slow": [50, 100]}, p.index[900])
    assert list(t["train_rank"]) == [1, 2, 3, 4]
    assert t["test_sharpe"].notna().all()


def test_walk_forward_tests_only_after_training():
    p = synthetic_prices(["X"], start="2010-01-01", n_days=252 * 7)["X"]
    windows, oos = walk_forward(p, st.sma_crossover, {"fast": [10, 20], "slow": [50, 100]}, 3, 1)
    assert len(windows) >= 3
    for _, w in windows.iterrows():
        assert w["test_start"] > w["train_end"]
    assert oos.index.is_monotonic_increasing
    assert not oos.index.duplicated().any()


def test_portfolio_targets_only_on_rebalance_dates():
    df = synthetic_prices(["A", "B", "C"], n_days=400)
    dates = set(pf.rebalance_dates(df.index))
    for w in (pf.equal_weight(df), pf.inverse_volatility(df, window=60)):
        set_rows = w.dropna(how="all")
        assert len(set_rows) > 0
        assert set(set_rows.index) <= dates
        assert set_rows.sum(axis=1).round(9).eq(1).all()


def test_auto_source_falls_back_to_synthetic(monkeypatch):
    import quantlab.data as data

    def boom(*a, **k):
        raise RuntimeError("no network")

    monkeypatch.setattr(data, "download_yfinance", boom)
    with pytest.warns(UserWarning, match="模擬資料"):
        out = load_prices("ZZZ", start="2020-01-01", end="2020-06-30")
    assert list(out.columns) == ["ZZZ"]


def test_download_yfinance_parses_multiindex(monkeypatch, tmp_path):
    """yfinance 回傳 (Price, Ticker) 兩層欄位、時區化日期；要轉成每欄一檔的收盤價。"""
    import sys
    import types

    import quantlab.data as data

    idx = pd.DatetimeIndex(["2020-01-02", "2020-01-03"]).tz_localize("America/New_York")
    cols = pd.MultiIndex.from_product([["Close", "Open"], ["SPY", "TLT"]], names=["Price", "Ticker"])
    raw = pd.DataFrame([[1, 2, 3, 4], [5, 6, 7, 8]], index=idx, columns=cols, dtype=float)
    fake = types.SimpleNamespace(download=lambda *a, **k: raw)
    monkeypatch.setitem(sys.modules, "yfinance", fake)
    monkeypatch.setattr(data, "CACHE_DIR", tmp_path)

    out = data.download_yfinance(["SPY", "TLT"], start="2020-01-01", end="2020-01-31")
    assert list(out.columns) == ["SPY", "TLT"]
    assert out["TLT"].tolist() == [2.0, 6.0]
    assert out.index.tz is None
    assert (tmp_path / "SPY_TLT_2020-01-01_2020-01-31.csv").exists()
