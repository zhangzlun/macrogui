"""畫淨值與回撤圖，存成 PNG。

沒裝 matplotlib 時不會報錯，只會提示並跳過。
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd

from quantlab.backtest import BacktestResult
from quantlab.indicators import drawdown


CJK_FONTS = (
    "PingFang TC",
    "Heiti TC",
    "Microsoft JhengHei",
    "Noto Sans CJK TC",
    "Noto Sans TC",
    "Noto Sans CJK JP",
    "Arial Unicode MS",
)
_warned_font = False


def _pyplot():
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("（沒有安裝 matplotlib，略過畫圖）")
        return None
    # 盡量找一個能顯示中文的字型；找不到就用預設字型，圖例可能變方框。
    from matplotlib import font_manager

    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in CJK_FONTS:
        if name in available:
            plt.rcParams["font.sans-serif"] = [name]
            break
    else:
        global _warned_font
        if not _warned_font:
            print("（找不到中文字型，圖上的中文可能顯示成方框；數字不受影響）")
            _warned_font = True
        warnings.filterwarnings("ignore", message="Glyph .* missing from font")
    plt.rcParams["axes.unicode_minus"] = False
    return plt


def plot_equity(
    results: dict[str, BacktestResult], path: str | Path, title: str = "淨值曲線"
) -> Path | None:
    """上半部畫淨值（對數座標），下半部畫回撤。"""
    plt = _pyplot()
    if plt is None:
        return None
    fig, (ax_eq, ax_dd) = plt.subplots(
        2, 1, figsize=(11, 7), sharex=True, gridspec_kw={"height_ratios": [3, 1.3]}
    )
    for name, res in results.items():
        ax_eq.plot(res.equity.index, res.equity.values, label=name, linewidth=1.3)
        dd = drawdown(res.equity)
        ax_dd.plot(dd.index, dd.values * 100, linewidth=1.0)
    ax_eq.set_yscale("log")
    from matplotlib.ticker import FuncFormatter

    plain = FuncFormatter(lambda y, _: f"{y:g}")
    ax_eq.yaxis.set_major_formatter(plain)
    ax_eq.yaxis.set_minor_formatter(plain)
    ax_eq.set_title(title)
    ax_eq.set_ylabel("淨值（起始 = 1）")
    ax_eq.legend(loc="upper left", fontsize=9)
    ax_eq.grid(alpha=0.3)
    ax_dd.set_ylabel("回撤 %")
    ax_dd.grid(alpha=0.3)
    fig.tight_layout()
    return _save(fig, plt, path)


def plot_series(
    data: pd.DataFrame, path: str | Path, title: str, ylabel: str = ""
) -> Path | None:
    """把 DataFrame 的每一欄畫成一條線。"""
    plt = _pyplot()
    if plt is None:
        return None
    fig, ax = plt.subplots(figsize=(11, 5))
    for col in data.columns:
        ax.plot(data.index, data[col].values, label=str(col), linewidth=1.2)
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    return _save(fig, plt, path)


def _save(fig, plt, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path
