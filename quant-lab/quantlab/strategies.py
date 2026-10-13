"""策略：把價格變成「目標部位」。

每個策略回傳一個和價格同樣日期的 Series，數值是想持有的部位比例：
1.0 = 全部資金買進，0.0 = 空手，0.5 = 一半資金。

訊號在第 t 天收盤後才算得出來，所以回測引擎會把它延後一天才持有。
策略本身不需要處理延遲，只要保證「第 t 天的訊號只用到第 t 天以前的價格」。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quantlab import indicators as ind


def buy_and_hold(prices: pd.Series) -> pd.Series:
    """買進持有：永遠 100% 持有。所有策略都該先跟它比。"""
    return pd.Series(1.0, index=prices.index, name="buy_and_hold")


def sma_crossover(prices: pd.Series, fast: int = 50, slow: int = 200) -> pd.Series:
    """均線交叉：短均線在長均線之上就持有，否則空手。

    經典的趨勢追蹤策略，50/200 日的交叉常被稱為「黃金交叉／死亡交叉」。
    """
    if fast >= slow:
        raise ValueError(f"fast ({fast}) 必須小於 slow ({slow})")
    fast_ma = ind.sma(prices, fast)
    slow_ma = ind.sma(prices, slow)
    signal = (fast_ma > slow_ma).astype(float)
    # 長均線還沒算出來的前幾天，一律空手。
    return signal.where(slow_ma.notna(), 0.0).rename("sma_crossover")


def time_series_momentum(prices: pd.Series, lookback: int = 126) -> pd.Series:
    """時間序列動能：過去 lookback 天（預設約半年）是賺的就持有，否則空手。"""
    mom = ind.momentum(prices, lookback)
    signal = (mom > 0).astype(float)
    return signal.where(mom.notna(), 0.0).rename("momentum")


def rsi_mean_reversion(
    prices: pd.Series, window: int = 14, buy_below: float = 30, sell_above: float = 70
) -> pd.Series:
    """RSI 均值回歸：RSI 跌破 buy_below 時買進，漲破 sell_above 時賣出。

    想法和趨勢策略相反：賭「跌太多會彈回來」。
    進場後一直持有到出場訊號出現，所以用 ffill 把狀態延續下去。
    """
    if buy_below >= sell_above:
        raise ValueError("buy_below 必須小於 sell_above")
    r = ind.rsi(prices, window)
    state = pd.Series(np.nan, index=prices.index)
    state[r < buy_below] = 1.0
    state[r > sell_above] = 0.0
    return state.ffill().fillna(0.0).rename("rsi_mean_reversion")


def volatility_target(
    prices: pd.Series,
    target_vol: float = 0.15,
    window: int = 20,
    max_leverage: float = 1.0,
) -> pd.Series:
    """波動度目標：市場越動盪，持有越少。

    部位 = 目標波動度 / 最近的實際波動度，上限 max_leverage。
    例如目標 15%、最近波動 30%，就只持有 50%。
    """
    vol = ind.rolling_volatility(ind.simple_returns(prices), window)
    weight = (target_vol / vol).clip(upper=max_leverage)
    return weight.fillna(0.0).rename("vol_target")


STRATEGIES = {
    "買進持有": buy_and_hold,
    "均線交叉 50/200": sma_crossover,
    "動能 126 日": time_series_momentum,
    "RSI 均值回歸": rsi_mean_reversion,
    "波動度目標 15%": volatility_target,
}
