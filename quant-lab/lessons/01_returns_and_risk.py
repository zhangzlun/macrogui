"""第一課：報酬與風險

學什麼：
- 簡單報酬 vs 對數報酬
- 年化報酬、年化波動度
- 報酬分布的「肥尾」：極端日子比常態分布預期的多
- 回撤：最貼近真實感受的風險指標

執行：uv run python lessons/01_returns_and_risk.py [代號]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from quantlab import indicators as ind
from quantlab import metrics
from quantlab.cli import OUTPUT_DIR, header, lesson_parser, load_from_args, section
from quantlab.plotting import plot_series


def main() -> None:
    args = lesson_parser("第一課：報酬與風險", ["SPY"]).parse_args()
    header("第一課：報酬與風險")
    prices = load_from_args(args)
    ticker = prices.columns[0]
    p = prices[ticker].dropna()

    section("1. 兩種報酬率")
    simple = ind.simple_returns(p).dropna()
    logr = ind.log_returns(p).dropna()
    print("最近五天：")
    print(
        (simple.tail().to_frame("簡單報酬").join(logr.tail().rename("對數報酬")) * 100)
        .round(3)
        .astype(str)
        .add(" %")
    )
    print("\n兩者在小幅變動時幾乎一樣。差別在於：")
    print("  對數報酬可以直接相加：", f"{logr.sum():.4f}", "→ 換回總報酬", f"{np.expm1(logr.sum()):.2%}")
    print("  簡單報酬要連乘：      ", f"{metrics.total_return(simple):.2%}")

    section("2. 年化")
    years = len(simple) / metrics.TRADING_DAYS
    print(f"期間約 {years:.1f} 年")
    print(f"總報酬     {metrics.total_return(simple):>8.1%}")
    print(f"年化報酬   {metrics.cagr(simple):>8.1%}   ← 每年穩定成長多少，才會得到同樣的總報酬")
    print(f"年化波動度 {metrics.annualized_volatility(simple):>8.1%}   ← 日報酬標準差 × √252")
    print(f"夏普值     {metrics.sharpe_ratio(simple):>8.2f}   ← 年化超額報酬 / 年化波動度（這裡假設無風險利率 0）")

    section("3. 肥尾：極端日子有多常見？")
    z = (simple - simple.mean()) / simple.std()
    big = int((z.abs() > 3).sum())
    expected = len(z) * 0.0027  # 常態分布超過 ±3 個標準差的機率約 0.27%
    print(f"偏態 (skew)   {simple.skew():>6.2f}   ← 負值代表大跌比大漲更常見")
    print(f"峰態 (kurt)   {simple.kurt():>6.2f}   ← 常態分布是 0，越大代表極端值越多")
    print(f"超過 ±3σ 的日子：實際 {big} 天，若是常態分布只該有約 {expected:.0f} 天")
    print("\n最慘的五天：")
    for d, v in simple.nsmallest(5).items():
        print(f"  {d.date()}  {v:+.2%}")
    print("最好的五天：")
    for d, v in simple.nlargest(5).items():
        print(f"  {d.date()}  {v:+.2%}")

    section("4. 回撤")
    equity = (1 + simple).cumprod()
    dd = ind.drawdown(equity)
    trough = dd.idxmin()
    peak = equity.loc[:trough].idxmax()
    recovered = equity.loc[trough:][equity.loc[trough:] >= equity.loc[peak]]
    print(f"最大回撤 {dd.min():.1%}：從 {peak.date()} 的高點跌到 {trough.date()}")
    if len(recovered):
        print(f"直到 {recovered.index[0].date()} 才回到前高，前後共 {(recovered.index[0] - peak).days} 天")
    else:
        print("到資料結束都還沒回到前高")
    print("想像一下：你能不能抱著一個帳面虧損這麼多的部位，撐這麼久？")

    section("5. 波動會群聚")
    vol = ind.rolling_volatility(simple, 21).dropna()
    print(f"一個月滾動波動度：最低 {vol.min():.0%}，最高 {vol.max():.0%}，中位數 {vol.median():.0%}")
    print("大波動之後往往跟著大波動。這是第三課「波動度目標」策略的出發點。")

    chart = plot_series(
        (dd * 100).to_frame(f"{ticker} 回撤 %").join((vol * 100).rename("滾動波動度 %")),
        OUTPUT_DIR / "01_drawdown_volatility.png",
        f"{ticker}：回撤與滾動波動度",
    )
    if chart:
        print(f"\n圖已存到 {chart}")


if __name__ == "__main__":
    main()
