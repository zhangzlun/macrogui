"""課程腳本共用的命令列參數。"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from quantlab.data import load_prices

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
DISCLAIMER = "※ 本專案僅供學習量化分析方法，所有結果皆為歷史或模擬回測，不構成任何投資建議。"


def lesson_parser(description: str, default_tickers: list[str]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "tickers", nargs="*", default=default_tickers, help=f"代號，預設 {default_tickers}"
    )
    parser.add_argument("--start", default="2005-01-01", help="開始日期")
    parser.add_argument("--end", default=None, help="結束日期，預設到最新")
    parser.add_argument(
        "--source",
        default="auto",
        choices=["auto", "yfinance", "synthetic", "csv"],
        help="資料來源：auto 先試 yfinance，失敗改用模擬資料",
    )
    parser.add_argument("--csv", default=None, help="source=csv 時的檔案路徑")
    parser.add_argument("--fee-bps", type=float, default=10.0, help="單邊交易成本（bp）")
    return parser


def load_from_args(args: argparse.Namespace) -> pd.DataFrame:
    prices = load_prices(
        args.tickers, start=args.start, end=args.end, source=args.source, csv_path=args.csv
    )
    first, last = prices.index[0].date(), prices.index[-1].date()
    print(f"資料：{', '.join(map(str, prices.columns))}，{first} ~ {last}，共 {len(prices)} 個交易日")
    return prices


def header(title: str, handout: str | None = None) -> None:
    print("=" * 64)
    print(title)
    print(DISCLAIMER)
    if handout:
        print(f"數學講義：math/{handout}（數字怎麼算出來的，看這份）")
    print("=" * 64)


def section(title: str) -> None:
    print(f"\n── {title} " + "─" * max(0, 58 - len(title) * 2))
