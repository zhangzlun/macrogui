"""驗證：避免把「運氣」誤認為「策略有效」。

量化新手最常掉的坑是過度擬合 (overfitting)：
試了一百組參數，挑出歷史上最賺的那組，結果只是剛好貼合過去的雜訊，
拿到新資料就失效。這個模組提供三個工具來看清楚這件事：

- grid_search          在一段期間內試遍所有參數組合
- train_test_compare   用前段挑參數，看它在後段（沒看過的資料）表現如何
- walk_forward         滾動前進：反覆「用過去幾年挑參數 → 在下一年實測」
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Mapping, Sequence

import pandas as pd

from quantlab import metrics
from quantlab.backtest import run_backtest

StrategyFn = Callable[..., pd.Series]


def evaluate(
    prices: pd.Series,
    strategy: StrategyFn,
    params: Mapping[str, object],
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    fee_bps: float = 10.0,
) -> pd.Series:
    """在 [start, end] 期間評估策略，回傳該期間的每日報酬。

    訊號用「整段歷史」計算，再只取這段期間的報酬。
    這樣長均線在期間一開始就已經有值；因為指標只看過去，不會偷看未來。
    """
    signal = strategy(prices, **params)
    result = run_backtest(prices, signal, fee_bps=fee_bps)
    return result.returns.loc[start:end]


def _param_combinations(grid: Mapping[str, Sequence[object]]) -> list[dict[str, object]]:
    keys = list(grid)
    return [dict(zip(keys, values)) for values in itertools.product(*grid.values())]


def grid_search(
    prices: pd.Series,
    strategy: StrategyFn,
    grid: Mapping[str, Sequence[object]],
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    fee_bps: float = 10.0,
) -> pd.DataFrame:
    """試遍 grid 的所有組合，依夏普值由高到低排序。無效組合（例如 fast >= slow）會略過。"""
    rows = []
    for params in _param_combinations(grid):
        try:
            r = evaluate(prices, strategy, params, start, end, fee_bps)
        except ValueError:
            continue
        rows.append(
            {
                **params,
                "sharpe": metrics.sharpe_ratio(r),
                "cagr": metrics.cagr(r),
                "max_drawdown": metrics.max_drawdown(r),
            }
        )
    if not rows:
        raise ValueError("沒有任何有效的參數組合")
    return pd.DataFrame(rows).sort_values("sharpe", ascending=False, na_position="last")


def train_test_compare(
    prices: pd.Series,
    strategy: StrategyFn,
    grid: Mapping[str, Sequence[object]],
    split_date: str | pd.Timestamp,
    fee_bps: float = 10.0,
) -> pd.DataFrame:
    """每組參數同時列出「訓練期」和「測試期」的夏普值。

    如果訓練期第一名在測試期掉到很後面，就是過度擬合的訊號。
    """
    split = pd.Timestamp(split_date)
    test_start = prices.index[prices.index > split][0]
    train = grid_search(prices, strategy, grid, end=split, fee_bps=fee_bps)
    param_cols = list(grid)
    test_sharpes = []
    for _, row in train.iterrows():
        params = {k: _native(row[k]) for k in param_cols}
        r = evaluate(prices, strategy, params, start=test_start, fee_bps=fee_bps)
        test_sharpes.append(metrics.sharpe_ratio(r))
    out = train[param_cols + ["sharpe"]].rename(columns={"sharpe": "train_sharpe"})
    out["test_sharpe"] = test_sharpes
    out["train_rank"] = range(1, len(out) + 1)
    out["test_rank"] = out["test_sharpe"].rank(ascending=False, method="min")
    return out.reset_index(drop=True)


def walk_forward(
    prices: pd.Series,
    strategy: StrategyFn,
    grid: Mapping[str, Sequence[object]],
    train_years: int = 3,
    test_years: int = 1,
    fee_bps: float = 10.0,
) -> tuple[pd.DataFrame, pd.Series]:
    """滾動前進驗證。

    每一輪：用前 train_years 年挑出夏普值最高的參數，
    在接下來 test_years 年實際跑，然後整段往後挪 test_years 年。
    把每一輪的測試期報酬接起來，才是比較誠實的「策略實戰表現」。

    回傳 (每一輪的紀錄, 接起來的樣本外每日報酬)。
    """
    index = prices.index
    windows = []
    oos_parts = []
    train_start = index[0]
    param_cols = list(grid)
    while True:
        train_end = train_start + pd.DateOffset(years=train_years)
        test_end = train_end + pd.DateOffset(years=test_years)
        if test_end > index[-1] + pd.Timedelta(days=1):
            break
        test_days = index[(index > train_end) & (index <= test_end)]
        if len(test_days) == 0:
            break

        ranked = grid_search(
            prices, strategy, grid, start=train_start, end=train_end, fee_bps=fee_bps
        )
        best = ranked.iloc[0]
        params = {k: _native(best[k]) for k in param_cols}
        oos = evaluate(
            prices, strategy, params, start=test_days[0], end=test_days[-1], fee_bps=fee_bps
        )
        oos_parts.append(oos)
        windows.append(
            {
                "train_start": train_start.date(),
                "train_end": train_end.date(),
                "test_start": test_days[0].date(),
                "test_end": test_days[-1].date(),
                **params,
                "train_sharpe": best["sharpe"],
                "test_sharpe": metrics.sharpe_ratio(oos),
            }
        )
        train_start = train_start + pd.DateOffset(years=test_years)

    if not windows:
        raise ValueError("資料太短，不夠做一輪滾動前進驗證")
    return pd.DataFrame(windows), pd.concat(oos_parts)


def _native(value: object) -> object:
    """把 numpy 數字轉回 Python 的 int/float，避免 rolling(window=50.0) 這種錯誤。"""
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value
