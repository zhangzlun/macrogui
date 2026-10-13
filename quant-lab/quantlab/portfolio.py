"""多資產投資組合的權重配置。

不把雞蛋放在同一個籃子：如果資產之間不是一起漲跌（相關性低），
組合起來的波動會比個別資產小，回撤也比較淺。

這裡的函式回傳「目標權重」DataFrame，交給 run_backtest 跑。
只有再平衡日有值，其他日子是 NaN：那些日子不交易，權重會隨漲跌漂移，
直到下一個再平衡日才調回目標。
"""

from __future__ import annotations

import pandas as pd

from quantlab import indicators as ind


def rebalance_dates(index: pd.DatetimeIndex, freq: str = "ME") -> pd.DatetimeIndex:
    """每個週期的最後一個交易日。freq："W-FRI" 每週、"ME" 每月、"QE" 每季、"YE" 每年。"""
    marker = pd.Series(index, index=index)
    return pd.DatetimeIndex(marker.resample(freq).last().dropna().values)


def _on_rebalance_dates(weights: pd.DataFrame, index: pd.DatetimeIndex) -> pd.DataFrame:
    """把再平衡日的權重放回完整日期，其他日子留 NaN（不交易）。"""
    return weights.reindex(index)


def equal_weight(prices: pd.DataFrame, freq: str = "ME") -> pd.DataFrame:
    """等權重：每檔都分到一樣多的資金。簡單但出乎意料地難打敗。"""
    dates = rebalance_dates(prices.index, freq)
    n = prices.shape[1]
    w = pd.DataFrame(1.0 / n, index=dates, columns=prices.columns)
    return _on_rebalance_dates(w, prices.index)


def inverse_volatility(
    prices: pd.DataFrame, window: int = 60, freq: str = "ME"
) -> pd.DataFrame:
    """反波動度加權：波動越小的資產分到越多資金，讓每檔對組合的「晃動」貢獻比較平均。"""
    vol = ind.simple_returns(prices).rolling(window, min_periods=window).std()
    raw = 1.0 / vol
    w = raw.div(raw.sum(axis=1), axis=0)
    dates = rebalance_dates(prices.index, freq)
    return _on_rebalance_dates(w.loc[dates].dropna(how="all"), prices.index)


def single_asset(prices: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """只持有其中一檔（買進後不再交易），當作比較基準。"""
    w = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
    w[ticker] = 1.0
    return w
