"""常用技術指標與報酬計算。

所有函式都只用「當天以前」的資料，不會偷看未來。
這點很重要：回測裡只要有一個指標用到未來資料，結果就全部不可信。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def simple_returns(prices: pd.Series | pd.DataFrame) -> pd.Series | pd.DataFrame:
    """簡單報酬率：今天價格 / 昨天價格 - 1。多資產加權時用它。"""
    return prices.pct_change()


def log_returns(prices: pd.Series | pd.DataFrame) -> pd.Series | pd.DataFrame:
    """對數報酬率：ln(今天 / 昨天)。可以直接相加得到多日報酬。"""
    return np.log(prices).diff()


def sma(series: pd.Series, window: int) -> pd.Series:
    """簡單移動平均：最近 window 天收盤價的平均。資料不足 window 天時為 NaN。"""
    return series.rolling(window, min_periods=window).mean()


def ema(series: pd.Series, span: int) -> pd.Series:
    """指數移動平均：越近的價格權重越大，反應比 SMA 快。"""
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def rsi(series: pd.Series, window: int = 14) -> pd.Series:
    """相對強弱指標（Wilder 平滑法），介於 0 到 100。

    = 100 - 100 / (1 + 平均漲幅 / 平均跌幅)
    一般把 70 以上視為「超買」、30 以下視為「超賣」。
    """
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    rs = avg_gain / avg_loss
    out = 100 - 100 / (1 + rs)
    # 完全沒漲也沒跌（例如停牌）時 0/0 為 NaN，視為中性 50。
    flat = (avg_gain == 0) & (avg_loss == 0)
    return out.mask(flat, 50.0)


def rolling_volatility(
    returns: pd.Series, window: int = 20, periods: int = TRADING_DAYS
) -> pd.Series:
    """滾動年化波動度：最近 window 天日報酬的標準差 × √252。"""
    return returns.rolling(window, min_periods=window).std() * np.sqrt(periods)


def momentum(series: pd.Series, lookback: int) -> pd.Series:
    """動能：過去 lookback 天的累積報酬。"""
    return series / series.shift(lookback) - 1


def bollinger_bands(
    series: pd.Series, window: int = 20, num_std: float = 2.0
) -> pd.DataFrame:
    """布林通道：中線是移動平均，上下軌是中線 ± num_std 個標準差。"""
    mid = sma(series, window)
    std = series.rolling(window, min_periods=window).std()
    return pd.DataFrame(
        {"middle": mid, "upper": mid + num_std * std, "lower": mid - num_std * std}
    )


def drawdown(equity: pd.Series) -> pd.Series:
    """回撤：目前淨值離歷史最高點跌了多少（0 代表在新高，-0.2 代表跌了 20%）。"""
    return equity / equity.cummax() - 1
