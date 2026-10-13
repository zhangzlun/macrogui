"""回測引擎。

核心概念只有幾行：
    實際持有部位 = 目標部位往後延 execution_lag 天
    每日策略報酬 = 實際部位 × 標的當日報酬 - 交易成本
    淨值        = 初始資金 × 每日 (1 + 策略報酬) 連乘

為什麼要延後？第 t 天的訊號要等第 t 天收盤才知道，
最早只能用第 t 天收盤價成交，賺的是第 t+1 天的漲跌。
如果不延後（execution_lag=0），等於用今天的收盤資訊去賺今天的漲跌，
這叫「前視偏誤 (look-ahead bias)」，回測會好看得不真實。第二課會示範。

目標部位的兩種給法：
- 每天都有值（策略的做法）：每天收盤都把部位調回目標
- 只有某些天有值、其他天是 NaN（投資組合的做法）：NaN 的日子不交易，
  各資產的權重會隨漲跌自然漂移，直到下一個有值的日子才再平衡

交易成本 = |目標權重 - 交易前的實際權重| 的總和 × 費率，
所以「漂移得越遠，再平衡越貴」也會反映在結果裡。

簡化假設（學習用，實際交易要更嚴謹）：
- 用收盤價成交，沒有滑價，可以買零股
- 沒有投入的資金放現金，利息為 0
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from quantlab import metrics


@dataclass(frozen=True)
class BacktestResult:
    """一次回測的結果。"""

    equity: pd.Series
    """每日淨值。"""
    returns: pd.Series
    """每日策略淨報酬（已扣成本）。"""
    positions: pd.DataFrame
    """每天開盤時實際持有的權重（交易後、當天漲跌之前）。"""
    turnover: pd.Series
    """每日換手率：權重變動的絕對值總和。1.0 代表一次全部買進或賣出。"""
    costs: pd.Series
    """每日交易成本（佔淨值的比例）。"""

    @property
    def trades(self) -> int:
        """有交易的天數。"""
        return int((self.turnover > 1e-12).sum())

    def summary(self) -> dict[str, float]:
        return metrics.summarize(self)


def _as_frame(data: pd.Series | pd.DataFrame, name: str = "asset") -> pd.DataFrame:
    if isinstance(data, pd.Series):
        return data.to_frame(name=data.name if data.name is not None else name)
    return data


def _drift(weights: np.ndarray, asset_ret: np.ndarray, gross: np.ndarray) -> np.ndarray:
    """經過一天的漲跌後，各資產佔淨值的比例。"""
    growth = 1.0 + gross
    safe = np.where(np.abs(growth) < 1e-12, 1.0, growth)
    return weights * (1.0 + asset_ret) / safe[:, None]


def _simulate_daily(targets: np.ndarray, asset_ret: np.ndarray, fee: float):
    """每天都調回目標：可以整批用陣列計算，速度快。"""
    gross = (targets * asset_ret).sum(axis=1)
    drifted = _drift(targets, asset_ret, gross)
    before_trade = np.vstack([np.zeros((1, targets.shape[1])), drifted[:-1]])
    turnover = np.abs(targets - before_trade).sum(axis=1)
    return targets, gross, turnover * fee, turnover


def _simulate_sparse(targets: np.ndarray, asset_ret: np.ndarray, fee: float):
    """只在有目標的日子交易，其他日子讓權重漂移：需要一天一天算。"""
    n_days, n_assets = targets.shape
    held = np.zeros((n_days, n_assets))
    gross = np.zeros(n_days)
    turnover = np.zeros(n_days)
    w = np.zeros(n_assets)
    has_target = ~np.isnan(targets).all(axis=1)
    for t in range(n_days):
        if has_target[t]:
            tgt = np.nan_to_num(targets[t])
            turnover[t] = np.abs(tgt - w).sum()
            w = tgt
        held[t] = w
        gross[t] = (w * asset_ret[t]).sum()
        w = _drift(w[None, :], asset_ret[t][None, :], np.array([gross[t]]))[0]
    return held, gross, turnover * fee, turnover


def run_backtest(
    prices: pd.Series | pd.DataFrame,
    weights: pd.Series | pd.DataFrame,
    fee_bps: float = 10.0,
    execution_lag: int = 1,
    initial_capital: float = 1.0,
) -> BacktestResult:
    """把目標部位套到價格上，算出淨值。

    prices         收盤價。單一標的給 Series，多資產給 DataFrame。
    weights        目標部位，格式同 prices。NaN 代表「那天不交易」。
    fee_bps        單邊交易成本，單位是 bp（萬分之一）。10 bp = 0.1%。
    execution_lag  訊號延後幾天才持有。1 是最基本的要求，2 更保守。
    """
    if execution_lag < 0:
        raise ValueError("execution_lag 不能是負數")

    price_df = _as_frame(prices).dropna(how="all")
    weight_df = _as_frame(weights)
    if weight_df.shape[1] == 1 and price_df.shape[1] == 1:
        weight_df = weight_df.set_axis(price_df.columns, axis=1)
    weight_df = weight_df.reindex(index=price_df.index, columns=price_df.columns)
    targets = weight_df.shift(execution_lag)
    # 一開始還沒有任何訊號的日子：空手。
    targets.iloc[:execution_lag] = 0.0

    asset_ret = price_df.pct_change().fillna(0.0).to_numpy()
    target_arr = targets.to_numpy(dtype=float)
    fee = fee_bps / 10_000

    row_missing = np.isnan(target_arr).all(axis=1)
    if row_missing.any():
        held, gross, costs, turnover = _simulate_sparse(target_arr, asset_ret, fee)
    else:
        held, gross, costs, turnover = _simulate_daily(
            np.nan_to_num(target_arr), asset_ret, fee
        )

    index = price_df.index
    net = gross - costs
    returns = pd.Series(net, index=index, name="returns")
    return BacktestResult(
        equity=(initial_capital * (1 + returns).cumprod()).rename("equity"),
        returns=returns,
        positions=pd.DataFrame(held, index=index, columns=price_df.columns),
        turnover=pd.Series(turnover, index=index, name="turnover"),
        costs=pd.Series(costs, index=index, name="costs"),
    )
