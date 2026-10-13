# quant-lab：量化分析學習專案

> **僅供學習，非投資建議。** 這裡所有的數字都來自歷史或模擬資料的回測。
> 回測好看不代表未來會賺錢，請不要直接拿來下單。

一個從零開始、一步一步學量化分析的小專案。程式刻意寫得短、註解多，
建議一邊跑課程、一邊打開 `quantlab/` 裡對應的檔案讀。

**不知道從哪開始？先看 [ROADMAP.md](ROADMAP.md)**：從小白到自己的量化內核與本機 AI 助手的完整路線。

## 安裝

需要 [uv](https://docs.astral.sh/uv/)。在這個資料夾執行：

```bash
cd quant-lab
uv sync
```

## 課程

依序執行，每一課會印出說明與數字，並把圖存到 `output/`。
每一課都有一份 **[數學講義](math/README.md)**：公式、白話解釋、手算例題、練習題與解答。
建議先跑課程，再讀講義，最後自己做練習題。

| 課程 | 學什麼 | 指令 |
| --- | --- | --- |
| 1. 報酬與風險 | 簡單／對數報酬、年化、肥尾、回撤、波動群聚 | `uv run python lessons/01_returns_and_risk.py` |
| 2. 第一個回測 | 訊號 → 部位 → 淨值、交易成本、前視偏誤 | `uv run python lessons/02_first_backtest.py` |
| 3. 策略比較 | 趨勢、動能、均值回歸、波動度目標的取捨 | `uv run python lessons/03_compare_strategies.py` |
| 4. 過度擬合 | 樣本內外、滾動前進驗證、隨機策略也能「贏」 | `uv run python lessons/04_overfitting.py` |
| 5. 投資組合 | 相關性、等權重、反波動度、再平衡頻率 | `uv run python lessons/05_portfolio.py` |

### 換標的、換期間

```bash
uv run python lessons/02_first_backtest.py QQQ --start 2010-01-01
uv run python lessons/02_first_backtest.py 2330.TW          # 台積電
uv run python lessons/05_portfolio.py 0050.TW 00679B.TW GLD  # 台股、美債 ETF、黃金
uv run python lessons/03_compare_strategies.py --fee-bps 30  # 調高交易成本
```

### 資料來源

| `--source` | 說明 |
| --- | --- |
| `auto`（預設） | 先用 yfinance 下載，失敗就改用模擬資料並提醒你 |
| `yfinance` | 只用 yfinance，失敗就報錯 |
| `synthetic` | 隨機模型產生的模擬價格，不需要網路，每次結果一樣 |
| `csv` | 讀自己的檔案：`--source csv --csv 我的資料.csv`，第一欄日期，其餘每欄一檔收盤價 |

用模擬資料時，數字跟真實市場無關，只拿來練習流程。

## 程式庫結構

```
quantlab/
  data.py         取得價格：yfinance、CSV、模擬資料
  indicators.py   報酬率、SMA、EMA、RSI、波動度、布林通道、回撤
  strategies.py   買進持有、均線交叉、動能、RSI 均值回歸、波動度目標
  backtest.py     向量化回測引擎（含交易成本與執行延遲）
  metrics.py      年化報酬、夏普值、索提諾值、最大回撤、卡瑪值等
  validation.py   參數最佳化、樣本內外比較、滾動前進驗證
  portfolio.py    等權重、反波動度加權、再平衡
  plotting.py     淨值與回撤圖
```

## 自己動手試

在 Python 裡直接用：

```python
from quantlab import load_prices, run_backtest, summary_table
from quantlab import strategies as st

p = load_prices("SPY", start="2010-01-01")["SPY"]
results = {
    "買進持有": run_backtest(p, st.buy_and_hold(p)),
    "均線 20/100": run_backtest(p, st.sma_crossover(p, 20, 100)),
}
print(summary_table(results))
```

寫一個自己的策略只要一個函式：輸入價格，回傳每天想持有的部位（0 到 1）。
訊號只能用當天以前的資料；回測引擎會自動延後一天才持有。

```python
def my_strategy(prices):
    return (prices > prices.rolling(100).mean()).astype(float)
```

## 練習題

1. 第二課把交易成本調到 50 bp，均線交叉還贏得了買進持有嗎？
2. 第三課換成一檔波動很大的個股，哪個策略的排名變最多？
3. 第四課把參數網格加大到 100 組以上，訓練期和測試期的落差變大還是變小？
4. 寫一個「雙動能」策略：過去 12 個月報酬 > 0 才持有，並和動能 126 日比較。
5. 第五課拿掉債券，只留股票類資產，分散的效果還在嗎？

## 回測的限制

這個專案為了好懂做了很多簡化，真實交易要考慮更多：

- 用收盤價成交、沒有滑價、可以買零股
- 多資產組合每天都拉回目標權重，成本只算目標改變的部分
- yfinance 的資料只有「現在還存在」的標的，會有倖存者偏差
- 沒有稅、沒有融資成本、沒有下市或停牌處理

## 測試

```bash
uv run pytest
```
