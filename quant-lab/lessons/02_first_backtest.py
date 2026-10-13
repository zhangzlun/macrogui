"""第二課：你的第一個回測

學什麼：
- 回測在做什麼：訊號 → 部位 → 每日損益 → 淨值
- 均線交叉策略 vs 買進持有
- 交易成本的影響
- 前視偏誤：最常見、也最致命的回測錯誤

執行：uv run python lessons/02_first_backtest.py [代號]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quantlab import run_backtest, summary_table
from quantlab import strategies as st
from quantlab.cli import OUTPUT_DIR, header, lesson_parser, load_from_args, section
from quantlab.plotting import plot_equity


def main() -> None:
    args = lesson_parser("第二課：你的第一個回測", ["SPY"]).parse_args()
    header("第二課：你的第一個回測")
    prices = load_from_args(args)
    p = prices.iloc[:, 0].dropna()

    section("1. 訊號長什麼樣子")
    signal = st.sma_crossover(p, fast=50, slow=200)
    changes = signal[signal.diff().fillna(0) != 0]
    print("均線交叉：50 日均線 > 200 日均線就持有（1），否則空手（0）")
    print(f"整段期間訊號切換了 {len(changes)} 次，最近幾次：")
    for d, v in changes.tail(5).items():
        print(f"  {d.date()}  {'買進' if v == 1 else '賣出'}")

    section("2. 回測：跟買進持有比")
    results = {
        "買進持有": run_backtest(p, st.buy_and_hold(p), fee_bps=args.fee_bps),
        "均線交叉": run_backtest(p, signal, fee_bps=args.fee_bps),
    }
    print(summary_table(results).to_string())
    print("\n常見結果：均線交叉的報酬不一定贏，但回撤通常比較淺，因為大跌時會先出場。")
    print("「報酬較低但回撤較小」算不算比較好？要看你能承受多少下跌。")

    section("3. 交易成本")
    for bps in (0, 10, 50):
        r = run_backtest(p, signal, fee_bps=bps)
        s = r.summary()
        print(f"單邊成本 {bps:>3} bp：年化報酬 {s['cagr']:>6.1%}，累計成本吃掉 {s['total_costs']:.1%}")
    print("交易越頻繁，成本越重要。很多回測上很漂亮的短線策略，扣完成本就不賺了。")

    section("4. 前視偏誤示範")
    cheat = run_backtest(p, signal, fee_bps=args.fee_bps, execution_lag=0)
    honest = results["均線交叉"]
    print("execution_lag=0：用今天收盤才知道的訊號，去賺今天的漲跌（不可能做到）")
    print(f"  正確（lag=1）年化報酬 {honest.summary()['cagr']:.1%}，夏普值 {honest.summary()['sharpe']:.2f}")
    print(f"  作弊（lag=0）年化報酬 {cheat.summary()['cagr']:.1%}，夏普值 {cheat.summary()['sharpe']:.2f}")
    print("慢速策略差距不大；但如果訊號跟當天漲跌高度相關，作弊版會好看得離譜：")
    peek = (p.pct_change() > 0).astype(float)  # 「今天漲就持有今天」—— 只有作弊才做得到
    print(f"  「今天漲就持有」作弊版年化報酬 {run_backtest(p, peek, fee_bps=0, execution_lag=0).summary()['cagr']:.0%}")
    print(f"  同一個訊號延後一天（實際可行）  {run_backtest(p, peek, fee_bps=0).summary()['cagr']:.1%}")
    print("看到好得不真實的回測，第一件事就是檢查有沒有偷看未來。")

    chart = plot_equity(results, OUTPUT_DIR / "02_first_backtest.png", "均線交叉 vs 買進持有")
    if chart:
        print(f"\n圖已存到 {chart}")


if __name__ == "__main__":
    main()
