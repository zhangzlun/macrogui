"""第四課：過度擬合——最貴的一課

學什麼：
- 參數最佳化：試遍所有組合，挑歷史上最好的
- 樣本內 vs 樣本外：挑出來的冠軍，在沒看過的資料上還是冠軍嗎？
- 滾動前進驗證：比較誠實的評估方式
- 為什麼「試越多次，越容易找到假的好策略」

數學講義：math/04_overfitting.md

執行：uv run python lessons/04_overfitting.py [代號]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from quantlab import metrics, run_backtest
from quantlab import strategies as st
from quantlab.cli import OUTPUT_DIR, header, lesson_parser, load_from_args, section
from quantlab.plotting import plot_series
from quantlab.validation import train_test_compare, walk_forward

GRID = {"fast": [5, 10, 20, 30, 50, 80], "slow": [60, 100, 150, 200, 250]}


def main() -> None:
    args = lesson_parser("第四課：過度擬合", ["SPY"]).parse_args()
    header("第四課：過度擬合——最貴的一課", "04_overfitting.md")
    prices = load_from_args(args)
    p = prices.iloc[:, 0].dropna()

    split = p.index[int(len(p) * 0.6)]
    section("1. 樣本內挑冠軍，樣本外看真相")
    print(f"前 60%（到 {split.date()}）當訓練期挑參數，後 40% 當測試期。")
    print(f"共試 {len(GRID['fast']) * len(GRID['slow'])} 組均線參數（fast < slow 才算有效）。\n")
    table = train_test_compare(p, st.sma_crossover, GRID, split, fee_bps=args.fee_bps)
    show = table.head(8).copy()
    show["train_sharpe"] = show["train_sharpe"].round(2)
    show["test_sharpe"] = show["test_sharpe"].round(2)
    show["test_rank"] = show["test_rank"].astype("Int64")
    print(show.rename(
        columns={"train_sharpe": "訓練夏普", "test_sharpe": "測試夏普", "train_rank": "訓練名次", "test_rank": "測試名次"}
    ).to_string(index=False))
    champ = table.iloc[0]
    print(f"\n訓練期冠軍 fast={int(champ['fast'])} slow={int(champ['slow'])}：")
    rank = "—" if pd.isna(champ["test_rank"]) else int(champ["test_rank"])
    print(f"  訓練夏普 {champ['train_sharpe']:.2f} → 測試夏普 {champ['test_sharpe']:.2f}，測試期排第 {rank} / {len(table)}")
    rho = table["train_sharpe"].rank().corr(table["test_sharpe"].rank())
    print(f"訓練名次和測試名次的相關係數：{rho:.2f}")
    print("  接近 1：訓練期好的參數，測試期也好（穩定）")
    print("  接近 0：挑參數跟擲骰子差不多")
    print("  負數：  訓練期越好的，測試期反而越差（典型的過度擬合）")

    section("2. 滾動前進驗證")
    windows, oos = walk_forward(p, st.sma_crossover, GRID, train_years=3, test_years=1, fee_bps=args.fee_bps)
    view = windows[["test_start", "test_end", "fast", "slow", "train_sharpe", "test_sharpe"]].copy()
    view["train_sharpe"] = view["train_sharpe"].round(2)
    view["test_sharpe"] = view["test_sharpe"].map(lambda v: "整年空手" if pd.isna(v) else f"{v:.2f}")
    print("每一輪用前三年挑參數，在下一年實測：")
    print(view.rename(columns={"test_start": "測試開始", "test_end": "測試結束", "train_sharpe": "訓練夏普", "test_sharpe": "測試夏普"}).to_string(index=False))
    print("（整年空手：策略那一年一直沒進場，報酬全是 0，算不出夏普值，平均時略過）")
    gap = windows["train_sharpe"].mean() - windows["test_sharpe"].mean()
    print(f"\n訓練期平均夏普 {windows['train_sharpe'].mean():.2f}，測試期平均 {windows['test_sharpe'].mean():.2f}，落差 {gap:.2f}")
    print(f"把所有測試期接起來的樣本外夏普值：{metrics.sharpe_ratio(oos):.2f}")
    print("這個樣本外數字，才比較接近你真的照這套流程操作會得到的結果。")

    section("3. 隨機策略也能「找到」好結果")
    rng = np.random.default_rng(0)
    trials = 200
    sharpes = []
    for _ in range(trials):
        # 每天擲硬幣決定持有或空手，但持續 20 天才換一次，模仿一個「策略」
        coin = rng.integers(0, 2, size=len(p) // 20 + 1).repeat(20)[: len(p)]
        sig = pd.Series(coin.astype(float), index=p.index)
        sharpes.append(run_backtest(p, sig, fee_bps=args.fee_bps).summary()["sharpe"])
    sharpes = np.array(sharpes)
    bh = run_backtest(p, st.buy_and_hold(p), fee_bps=args.fee_bps).summary()["sharpe"]
    print(f"{trials} 個完全隨機的「策略」：")
    print(f"  夏普值中位數 {np.median(sharpes):.2f}，最好的一個 {sharpes.max():.2f}")
    print(f"  買進持有的夏普值 {bh:.2f}")
    print(f"  有 {(sharpes > bh).mean():.0%} 的隨機策略「打敗」買進持有")
    print("如果你試了 200 個點子，挑出最好的那個拿來炫耀，它很可能只是這裡的「最好的隨機策略」。")
    print("對策：事先決定好要測什麼、參數越少越好、一定要留一段完全沒碰過的資料做最後檢驗。")

    chart = plot_series(
        pd.DataFrame({"樣本外（滾動前進）": (1 + oos).cumprod()}),
        OUTPUT_DIR / "04_walk_forward.png",
        "滾動前進：接起來的樣本外淨值",
        "淨值",
    )
    if chart:
        print(f"\n圖已存到 {chart}")


if __name__ == "__main__":
    main()
