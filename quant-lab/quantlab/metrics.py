"""績效指標。輸入都是「每日報酬」Series。

幾個最常用的：
- 年化報酬 (CAGR)：如果每年都穩定成長，相當於每年賺多少
- 年化波動度：報酬上下晃動的幅度，常被當成風險
- 夏普值 (Sharpe)：每承擔一單位波動，換到多少超額報酬。> 1 通常算不錯
- 索提諾值 (Sortino)：同夏普值，但只把「下跌」的波動當風險
- 最大回撤 (MDD)：從最高點跌到最低點最多跌了多少。最貼近「心理上撐不撐得住」
- 卡瑪值 (Calmar)：年化報酬 / 最大回撤
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from quantlab.backtest import BacktestResult

TRADING_DAYS = 252


def total_return(returns: pd.Series) -> float:
    return float((1 + returns).prod() - 1)


def cagr(returns: pd.Series, periods: int = TRADING_DAYS) -> float:
    n = len(returns)
    if n == 0:
        return float("nan")
    growth = float((1 + returns).prod())
    if growth <= 0:
        return -1.0
    return growth ** (periods / n) - 1


def annualized_volatility(returns: pd.Series, periods: int = TRADING_DAYS) -> float:
    return float(returns.std(ddof=1) * np.sqrt(periods))


def sharpe_ratio(
    returns: pd.Series, risk_free: float = 0.0, periods: int = TRADING_DAYS
) -> float:
    """年化夏普值。risk_free 是年化無風險利率，例如 0.02。"""
    excess = returns - risk_free / periods
    std = excess.std(ddof=1)
    if not np.isfinite(std) or std < 1e-12:
        return float("nan")
    return float(excess.mean() / std * np.sqrt(periods))


def sortino_ratio(
    returns: pd.Series, risk_free: float = 0.0, periods: int = TRADING_DAYS
) -> float:
    excess = returns - risk_free / periods
    downside = np.sqrt((excess.clip(upper=0) ** 2).mean())
    if not np.isfinite(downside) or downside < 1e-12:
        return float("nan")
    return float(excess.mean() / downside * np.sqrt(periods))


def max_drawdown(returns: pd.Series) -> float:
    """最大回撤，回傳負數，例如 -0.35 代表最多跌了 35%。"""
    if len(returns) == 0:
        return float("nan")
    equity = (1 + returns).cumprod()
    peak = equity.cummax().clip(lower=1.0)  # 起始淨值 1 也算一個高點
    return float((equity / peak - 1).min())


def calmar_ratio(returns: pd.Series, periods: int = TRADING_DAYS) -> float:
    mdd = max_drawdown(returns)
    if not np.isfinite(mdd) or mdd == 0:
        return float("nan")
    return cagr(returns, periods) / abs(mdd)


def win_rate(returns: pd.Series) -> float:
    """有進出的日子裡，賺錢日子的比例（報酬剛好為 0 的日子不算）。"""
    active = returns[returns != 0]
    if len(active) == 0:
        return float("nan")
    return float((active > 0).mean())


def exposure(positions: pd.DataFrame | pd.Series) -> float:
    """有持倉的天數比例。"""
    if isinstance(positions, pd.DataFrame):
        positions = positions.abs().sum(axis=1)
    return float((positions.abs() > 1e-12).mean())


def summarize(result: BacktestResult, risk_free: float = 0.0) -> dict[str, float]:
    r = result.returns
    return {
        "total_return": total_return(r),
        "cagr": cagr(r),
        "volatility": annualized_volatility(r),
        "sharpe": sharpe_ratio(r, risk_free),
        "sortino": sortino_ratio(r, risk_free),
        "max_drawdown": max_drawdown(r),
        "calmar": calmar_ratio(r),
        "win_rate": win_rate(r),
        "exposure": exposure(result.positions),
        "trades": float(result.trades),
        "total_costs": float(result.costs.sum()),
    }


LABELS = {
    "total_return": ("總報酬", "pct"),
    "cagr": ("年化報酬", "pct"),
    "volatility": ("年化波動度", "pct"),
    "sharpe": ("夏普值", "num"),
    "sortino": ("索提諾值", "num"),
    "max_drawdown": ("最大回撤", "pct"),
    "calmar": ("卡瑪值", "num"),
    "win_rate": ("日勝率", "pct"),
    "exposure": ("持倉時間", "pct"),
    "trades": ("交易次數", "int"),
    "total_costs": ("累計成本", "pct"),
}


def _fmt(value: float, kind: str) -> str:
    if not np.isfinite(value):
        return "—"
    if kind == "pct":
        return f"{value:.1%}"
    if kind == "int":
        return f"{int(value)}"
    return f"{value:.2f}"


def summary_table(results: dict[str, BacktestResult]) -> pd.DataFrame:
    """把多個回測結果排成一張好讀的比較表（列是指標，欄是策略）。"""
    table = {}
    for name, res in results.items():
        stats = summarize(res)
        table[name] = {LABELS[k][0]: _fmt(v, LABELS[k][1]) for k, v in stats.items()}
    return pd.DataFrame(table)
