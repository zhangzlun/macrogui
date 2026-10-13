"""用專案裡的函式重算講義的例題與練習題，確認手算和程式的結果一樣。

執行：uv run python math/check_examples.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from quantlab import indicators as ind
from quantlab import metrics as m
from quantlab import run_backtest
from quantlab.portfolio import inverse_volatility

S = pd.Series
ROOT252 = np.sqrt(252)


def two_asset_vol(w_a, w_b, vol_a, vol_b, rho):
    var = w_a**2 * vol_a**2 + w_b**2 * vol_b**2 + 2 * w_a * w_b * rho * vol_a * vol_b
    return np.sqrt(var)


def rank_corr(a, b):
    return S(a).rank(ascending=False).corr(S(b).rank(ascending=False))


def inverse_vol_weights(vols):
    """用專案的 inverse_volatility，餵它「波動度剛好是 vols」的價格。"""
    idx = pd.bdate_range("2020-01-01", periods=62)
    sign = np.where(np.arange(61) % 2 == 0, 1.0, -1.0)
    prices = {}
    for i, v in enumerate(vols):
        daily = v / ROOT252
        prices[f"a{i}"] = 100 * np.concatenate([[1.0], np.cumprod(1 + sign * daily)])
    df = pd.DataFrame(prices, index=idx)
    w = inverse_volatility(df, window=60, freq="YE").dropna(how="all").iloc[-1]
    return w.to_numpy()


def drift_turnover(start_w, growth, target_w):
    """單日：權重 start_w，各資產成長 growth 倍後，再平衡回 target_w 的換手率。"""
    idx = pd.bdate_range("2020-01-01", periods=4)
    n = len(start_w)
    prices = pd.DataFrame(
        [[100.0] * n, [100.0] * n, [100.0 * g for g in growth], [100.0 * g for g in growth]],
        index=idx,
    )
    w = pd.DataFrame(np.nan, index=idx, columns=prices.columns)
    w.iloc[0] = start_w
    w.iloc[2] = target_w
    res = run_backtest(prices, w, fee_bps=0)
    return res.turnover.iloc[3]


CHECKS = [
    # (講義, 題目, 手算答案, 程式算出來的值)
    ("01", "例題：漲10%再跌10%", -0.01, m.total_return(S([0.10, -0.10]))),
    ("01", "例題：對數報酬相加後換回", -0.01, np.expm1(ind.log_returns(S([100, 110, 99.0])).sum())),
    ("01", "例題：100→200 十年的年化", 0.0718, m.cagr(S([1.0] + [0.0] * 9), periods=1)),
    ("01", "例題：日標準差", 0.0212, S([0.01, -0.02, 0.03, 0.0, -0.02]).std()),
    ("01", "例題：年化波動度", 0.337, m.annualized_volatility(S([0.01, -0.02, 0.03, 0.0, -0.02]))),
    ("01", "例題：夏普值 0.04%/1%", 0.63, 0.0004 / 0.01 * ROOT252),
    ("01", "例題：夏普值（扣無風險利率）", 0.5, (0.10 - 0.02) / 0.16),
    ("01", "例題：高點要看整段歷史", -0.333, ind.drawdown(S([100, 120, 90, 110, 80.0])).min()),
    ("01", "例題：最大回撤", -0.25, ind.drawdown(S([100, 120, 90, 130, 104.0])).min()),
    ("01", "例題：虧50%回本要漲", 1.0, 1 / (1 - 0.5) - 1),
    ("01", "練習1", 0.20, 60 / 50 - 1),
    ("01", "練習2", 0.0389, m.total_return(S([0.05, -0.03, 0.02]))),
    ("01", "練習3", 0.1447, 1.5 ** (1 / 3) - 1),
    ("01", "練習4 日標準差", 0.0258, S([0.02, 0.0, -0.02, 0.04]).std()),
    ("01", "練習4 年化", 0.41, m.annualized_volatility(S([0.02, 0.0, -0.02, 0.04]))),
    ("01", "練習5", 0.66, 0.0005 / 0.012 * ROOT252),
    ("01", "練習6", -0.308, ind.drawdown(S([1.0, 1.3, 1.1, 0.9, 1.2, 1.4])).min()),
    ("01", "練習7", 0.667, 1 / 0.6 - 1),
    ("02", "例題：淨值三天", 1.0195, (1 + S([0.01, -0.02, 0.03])).prod()),
    (
        "02",
        "例題：延後一天，第3天報酬",
        -0.10,
        run_backtest(S([100, 110, 99, 120.0]), S([0, 1, 0, 0.0]), fee_bps=0).returns.iloc[2],
    ),
    ("02", "例題：26次成本（精確）", 0.0257, 1 - 0.999**26),
    ("02", "例題：5日SMA 第5天", 11.4, ind.sma(S([10, 11, 12, 11, 13, 14.0]), 5).iloc[4]),
    ("02", "例題：5日SMA 第6天", 12.2, ind.sma(S([10, 11, 12, 11, 13, 14.0]), 5).iloc[5]),
    ("02", "例題：3日EMA 第4天", 11.125, ind.ema(S([10, 11, 12, 11.0]), 3).iloc[3]),
    ("02", "練習2", 1.0088, (1 + S([0.02, 0.02, -0.04, 0.01])).prod()),
    (
        "02",
        "練習3 第4天報酬",
        0.0784,
        run_backtest(S([50, 52, 51, 55.0]), S([1, 1, 1, 1.0]), fee_bps=0).returns.iloc[3],
    ),
    ("02", "練習5 最後一個", 22.67, ind.sma(S([20, 22, 21, 23, 24.0]), 3).iloc[-1]),
    ("02", "練習6", 10.8, S([10, 12.0]).ewm(span=4, adjust=False).mean().iloc[-1]),
    ("03", "例題：動能", 0.20, ind.momentum(S([100.0, 110, 120]), 2).iloc[-1]),
    ("03", "例題：索提諾（日）", 0.95, 0.006 / np.sqrt((S([0.02, -0.01, 0.03, 0, -0.01]).clip(upper=0) ** 2).mean())),
    ("03", "例題：夏普（日）", 0.33, S([0.02, -0.01, 0.03, 0, -0.01]).mean() / S([0.02, -0.01, 0.03, 0, -0.01]).std()),
    ("03", "例題：相關係數", 0.8, S([1, 2, 3, 4.0]).corr(S([1, 3, 2, 4.0]))),
    ("03", "練習5 下檔偏差", 0.0115, np.sqrt((S([0.01, -0.02, 0.04]).clip(upper=0) ** 2).mean())),
    ("03", "練習6", -1.0, S([1, 2, 3.0]).corr(S([3, 2, 1.0]))),
    ("04", "例題：試20次", 0.64, 1 - 0.95**20),
    ("04", "例題：20年夏普標準誤差", 0.22, 1 / np.sqrt(20)),
    ("04", "例題：等級相關", -0.4, rank_corr([0.9, 0.7, 0.5, 0.3], [0.1, 0.4, 0.2, 0.3])),
    ("04", "練習1", 0.65, 1 - 0.9**10),
    ("05", "例題：ρ=0 組合波動", 0.141, two_asset_vol(0.5, 0.5, 0.2, 0.2, 0)),
    ("05", "例題：ρ=0.5 組合波動", 0.173, two_asset_vol(0.5, 0.5, 0.2, 0.2, 0.5)),
    ("05", "例題：反波動 股票權重", 1 / 3, inverse_vol_weights([0.2, 0.1])[0]),
    ("05", "例題：再平衡換手率", 1 / 3, drift_turnover([0.5, 0.5], [2.0, 1.0], [0.5, 0.5])),
    ("05", "練習2", 0.212, two_asset_vol(0.5, 0.5, 0.3, 0.3, 0)),
    ("05", "練習3", 0.268, two_asset_vol(0.5, 0.5, 0.3, 0.3, 0.6)),
    ("05", "練習4 第一檔權重", 0.571, inverse_vol_weights([0.1, 0.2, 0.4])[0]),
    ("05", "練習5 換手率", 0.185, drift_turnover([0.6, 0.4], [1.5, 1.0], [0.6, 0.4])),
]


def _close(expected: float, actual: float) -> bool:
    # 講義的答案四捨五入過，所以容許最後一位的誤差。
    digits = max(0, len(f"{abs(expected):.6g}".split(".")[-1])) if "." in f"{expected:.6g}" else 0
    tol = 0.6 * 10 ** (-digits) if digits else 0.5
    return abs(expected - actual) <= max(tol, 1e-9)


def run() -> list[tuple[str, str, float, float, bool]]:
    return [(h, q, e, float(a), _close(e, float(a))) for h, q, e, a in CHECKS]


def main() -> None:
    rows = run()
    for handout, question, expected, actual, ok in rows:
        mark = "✓" if ok else "✗"
        print(f"{mark} 講義{handout}  {question:<22} 手算 {expected:>10.4f}   程式 {actual:>10.4f}")
    bad = [r for r in rows if not r[4]]
    print(f"\n共 {len(rows)} 題，{len(rows) - len(bad)} 題相符。")
    if bad:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
