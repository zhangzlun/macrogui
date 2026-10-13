"""第五課：投資組合與分散

學什麼：
- 相關性：資產之間是不是一起漲跌
- 等權重 vs 反波動度加權
- 再平衡頻率的影響
- 分散為什麼被稱為「唯一的免費午餐」

執行：uv run python lessons/05_portfolio.py [代號1 代號2 ...]
預設：SPY（美股）、TLT（長天期美債）、GLD（黃金）、VNQ（不動產）
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quantlab import indicators as ind
from quantlab import portfolio as pf
from quantlab import run_backtest, summary_table
from quantlab.cli import OUTPUT_DIR, header, lesson_parser, load_from_args, section
from quantlab.plotting import plot_equity


def main() -> None:
    args = lesson_parser("第五課：投資組合與分散", ["SPY", "TLT", "GLD", "VNQ"]).parse_args()
    header("第五課：投資組合與分散")
    prices = load_from_args(args).dropna()
    if prices.shape[1] < 2:
        raise SystemExit("投資組合至少需要兩檔標的")
    returns = ind.simple_returns(prices).dropna()

    section("1. 相關性")
    print(returns.corr().round(2).to_string())
    print("\n1 代表完全同步、0 代表沒關係、負數代表常常反方向。")
    print("相關性越低，放在一起越能互相抵銷波動。")

    section("2. 個別資產 vs 組合")
    results = {t: run_backtest(prices, pf.single_asset(prices, t), fee_bps=args.fee_bps) for t in prices.columns}
    results["等權重（月再平衡）"] = run_backtest(prices, pf.equal_weight(prices, "ME"), fee_bps=args.fee_bps)
    results["反波動度（月再平衡）"] = run_backtest(prices, pf.inverse_volatility(prices, 60, "ME"), fee_bps=args.fee_bps)
    print(summary_table(results).to_string())
    print("\n常見結果：組合的報酬落在個別資產中間，但波動和回撤比大部分單一資產都小。")
    print("夏普值往往比任何一檔單獨持有都高——這就是分散的價值。")

    section("3. 反波動度的權重長什麼樣子")
    w = pf.inverse_volatility(prices, 60, "ME").dropna(how="all")
    latest = w.iloc[-1]
    print(f"最近一次再平衡（{w.index[-1].date()}）的目標權重：")
    for t, v in latest.items():
        print(f"  {t:<6} {v:6.1%}  {'█' * int(v * 40)}")
    print("波動小的資產（通常是債券）分到比較多。好處是比較穩，風險是太集中在某一類資產。")

    section("4. 再平衡頻率")
    for label, freq in (("每週", "W-FRI"), ("每月", "ME"), ("每季", "QE"), ("每年", "YE")):
        r = run_backtest(prices, pf.inverse_volatility(prices, 60, freq), fee_bps=args.fee_bps)
        s = r.summary()
        print(f"  {label}：年化報酬 {s['cagr']:6.1%}，夏普 {s['sharpe']:.2f}，累計成本 {s['total_costs']:.2%}")
    print("再平衡越頻繁，權重越貼近目標，但成本越高。實務上每月或每季很常見。")

    chart = plot_equity(results, OUTPUT_DIR / "05_portfolio.png", "個別資產 vs 投資組合")
    if chart:
        print(f"\n圖已存到 {chart}")


if __name__ == "__main__":
    main()
