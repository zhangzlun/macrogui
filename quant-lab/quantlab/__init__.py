"""quantlab：量化分析學習用的小型程式庫。

僅供學習，非投資建議。每個模組都刻意寫得短、註解多，
方便你一邊讀程式一邊理解概念：

- data        取得價格：yfinance、CSV，或離線用的模擬資料
- indicators  報酬率、移動平均、RSI、波動度、回撤等指標
- strategies  把指標變成「要持有多少部位」的訊號
- backtest    把訊號套到歷史價格上，算出淨值曲線（含手續費）
- metrics     年化報酬、夏普值、最大回撤等績效指標
- validation  參數最佳化、樣本內外測試、滾動前進驗證
- portfolio   多資產的權重配置與再平衡
- plotting    淨值與回撤圖
"""

from quantlab.backtest import BacktestResult, run_backtest
from quantlab.data import load_prices, synthetic_prices
from quantlab.metrics import summarize, summary_table

__all__ = [
    "BacktestResult",
    "load_prices",
    "run_backtest",
    "summarize",
    "summary_table",
    "synthetic_prices",
]
