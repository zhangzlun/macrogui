"""取得價格資料。

三種來源：
- yfinance：從 Yahoo Finance 下載還原股價（需要網路）
- csv：讀你自己的檔案，第一欄是日期，其餘每欄一檔標的的收盤價
- synthetic：用隨機模型產生的模擬價格，不需網路，適合練習與測試

source="auto" 會先試 yfinance，失敗就改用模擬資料並提醒你。
回傳的一律是 DataFrame：索引是日期，每欄一檔標的的收盤價。
"""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pandas as pd

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"


def synthetic_prices(
    tickers: Sequence[str] = ("SYN",),
    start: str = "2010-01-01",
    end: str | None = None,
    n_days: int | None = None,
    seed: int = 42,
) -> pd.DataFrame:
    """產生模擬的每日收盤價。

    模型分兩層，讓模擬資料有一點真實市場的樣子：
    1. 大盤在「多頭」和「空頭」兩種狀態間隨機切換（馬可夫鏈）。
       多頭時報酬略正、波動小；空頭時報酬為負、波動大。
    2. 每檔標的 = beta × 大盤報酬 + 自己的雜訊（第一檔的 beta 固定為 1）。
       beta 不同，標的之間的相關性就不同，投資組合的課程會用到。

    同一個 seed 每次產生的資料都一樣，方便重現結果。
    """
    if n_days is None:
        end_ts = pd.Timestamp(end) if end else pd.Timestamp.today().normalize()
        dates = pd.bdate_range(start, end_ts)
    else:
        dates = pd.bdate_range(start, periods=n_days)
    n = len(dates)
    if n < 2:
        raise ValueError("模擬資料至少需要兩個交易日")

    rng = np.random.default_rng(seed)

    # 狀態 0 = 多頭、1 = 空頭。每天有小機率切換。
    stay = {0: 0.997, 1: 0.985}
    regime = np.empty(n, dtype=int)
    regime[0] = 0
    for t in range(1, n):
        prev = regime[t - 1]
        regime[t] = prev if rng.random() < stay[prev] else 1 - prev

    daily_mu = np.where(regime == 0, 0.14 / 252, -0.20 / 252)
    daily_sigma = np.where(regime == 0, 0.13 / np.sqrt(252), 0.28 / np.sqrt(252))
    market = rng.normal(daily_mu, daily_sigma)

    columns = {}
    for i, ticker in enumerate(tickers):
        # 第一檔當成「大盤」（beta = 1），其他檔的 beta 隨機，有的甚至跟大盤反向。
        beta = 1.0 if i == 0 else rng.uniform(-0.3, 1.3)
        idio_sigma = (0.03 if i == 0 else rng.uniform(0.05, 0.20)) / np.sqrt(252)
        drift = rng.uniform(0.0, 0.03) / 252
        log_ret = beta * market + rng.normal(drift, idio_sigma, n)
        log_ret[0] = 0.0
        columns[ticker] = 100.0 * np.exp(np.cumsum(log_ret))

    prices = pd.DataFrame(columns, index=dates)
    prices.index.name = "Date"
    return prices


def load_csv(path: str | Path) -> pd.DataFrame:
    """讀取價格 CSV：第一欄日期，其餘欄位是各標的收盤價。"""
    prices = pd.read_csv(path, index_col=0, parse_dates=True).sort_index()
    prices.index.name = "Date"
    return prices.astype(float)


def download_yfinance(
    tickers: Sequence[str],
    start: str,
    end: str | None = None,
    use_cache: bool = True,
) -> pd.DataFrame:
    """用 yfinance 下載還原收盤價（已調整股利與分割）。

    下載過的資料會存在 data/cache/，同樣的查詢第二次就不用再連網。
    """
    key = f"{'_'.join(tickers)}_{start}_{end or 'latest'}.csv"
    cache_file = CACHE_DIR / key
    if use_cache and end and cache_file.exists():
        return load_csv(cache_file)

    import yfinance as yf

    raw = yf.download(
        list(tickers), start=start, end=end, auto_adjust=True, progress=False
    )
    if raw is None or raw.empty:
        raise RuntimeError(f"yfinance 沒有回傳資料：{list(tickers)}")

    close = raw["Close"]
    if isinstance(close, pd.Series):
        close = close.to_frame(name=tickers[0])
    close = close.reindex(columns=list(tickers)).dropna(how="all")
    missing = [t for t in tickers if close[t].isna().all()]
    if missing:
        raise RuntimeError(f"這些代號下載不到資料：{missing}")

    close.index = pd.DatetimeIndex(close.index).tz_localize(None)
    close.index.name = "Date"
    if use_cache and end:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        close.to_csv(cache_file)
    return close


def load_prices(
    tickers: str | Sequence[str],
    start: str = "2010-01-01",
    end: str | None = None,
    source: str = "auto",
    csv_path: str | Path | None = None,
    seed: int = 42,
) -> pd.DataFrame:
    """取得價格的單一入口。

    source：
      "auto"       先試 yfinance，失敗就改用模擬資料（會發出警告）
      "yfinance"   只用 yfinance，失敗就報錯
      "csv"        讀 csv_path
      "synthetic"  模擬資料
    """
    if isinstance(tickers, str):
        tickers = [tickers]
    tickers = list(tickers)

    if source == "csv":
        if csv_path is None:
            raise ValueError('source="csv" 需要提供 csv_path')
        prices = load_csv(csv_path)
        return prices.loc[start:end] if end else prices.loc[start:]
    if source == "synthetic":
        return synthetic_prices(tickers, start=start, end=end, seed=seed)
    if source == "yfinance":
        return download_yfinance(tickers, start=start, end=end)
    if source == "auto":
        try:
            return download_yfinance(tickers, start=start, end=end)
        except Exception as exc:  # 網路不通、代號錯誤、沒裝 yfinance 等
            warnings.warn(
                f"下載真實資料失敗（{exc.__class__.__name__}: {exc}），"
                "改用模擬資料。結果不代表任何真實市場。",
                stacklevel=2,
            )
            return synthetic_prices(tickers, start=start, end=end, seed=seed)
    raise ValueError(f"未知的資料來源：{source}")
