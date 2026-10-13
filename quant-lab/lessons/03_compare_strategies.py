"""第三課：比較不同類型的策略

學什麼：
- 趨勢追蹤（均線、動能）vs 均值回歸（RSI）vs 風險控管（波動度目標）
- 用同一套指標公平比較
- 沒有「最好」的策略，只有不同的取捨

執行：uv run python lessons/03_compare_strategies.py [代號]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from quantlab import metrics, run_backtest, summary_table
from quantlab import strategies as st
from quantlab.cli import OUTPUT_DIR, header, lesson_parser, load_from_args, section
from quantlab.plotting import plot_equity


def main() -> None:
    args = lesson_parser("第三課：比較不同類型的策略", ["SPY"]).parse_args()
    header("第三課：比較不同類型的策略")
    prices = load_from_args(args)
    p = prices.iloc[:, 0].dropna()

    results = {name: run_backtest(p, fn(p), fee_bps=args.fee_bps) for name, fn in st.STRATEGIES.items()}

    section("1. 比較表")
    print(summary_table(results).to_string())

    section("2. 怎麼讀這張表")
    best_sharpe = max(results, key=lambda k: results[k].summary()["sharpe"])
    best_dd = max(results, key=lambda k: results[k].summary()["max_drawdown"])
    best_cagr = max(results, key=lambda k: results[k].summary()["cagr"])
    print(f"年化報酬最高：{best_cagr}")
    print(f"夏普值最高：  {best_sharpe}")
    print(f"回撤最淺：    {best_dd}")
    print("三個第一名常常不是同一個策略。這就是取捨：要報酬、要穩定、還是要睡得著？")
    print("也看一下交易次數：波動度目標幾乎每天都微調部位，實務上會設門檻，變動夠大才調整。")

    section("3. 分年度看")
    yearly = {
        name: res.returns.groupby(res.returns.index.year).apply(metrics.total_return)
        for name, res in results.items()
    }
    table = pd.DataFrame(yearly)
    print((table * 100).round(1).astype(str).add("%").tail(12).to_string())
    print("\n注意那些大跌的年份：趨勢與波動度策略通常損失較少，但在急跌急漲的年份可能兩邊挨打。")

    section("4. 策略之間的相關性")
    corr = pd.DataFrame({k: v.returns for k, v in results.items()}).corr().round(2)
    print(corr.to_string())
    print("\n相關性低的策略組合在一起，可以降低整體波動。第五課會用在資產配置上。")

    chart = plot_equity(results, OUTPUT_DIR / "03_compare_strategies.png", "策略比較")
    if chart:
        print(f"\n圖已存到 {chart}")


if __name__ == "__main__":
    main()
