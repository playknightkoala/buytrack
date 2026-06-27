"""價格歷史走勢圖（matplotlib，輸出 PNG bytes）。

圖內文字只用數字/日期，避免 matplotlib 預設字型缺中文造成亂碼；
商品名稱等中文放在 Telegram 的 caption。
"""
from __future__ import annotations

import datetime as dt
from io import BytesIO

import matplotlib

matplotlib.use("Agg")  # 無頭環境
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

_ACCENT = "#1ab6b6"
_HI = "#e15759"
_LO = "#59a14f"


def render_price_history(points: list[tuple[dt.datetime, float]], currency: str | None) -> bytes:
    """points 需為時間升冪的 (checked_at, price)。回傳 PNG bytes。"""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    hi, lo = max(ys), min(ys)

    fig, ax = plt.subplots(figsize=(8, 4), dpi=120)
    ax.step(xs, ys, where="post", color=_ACCENT, linewidth=2)
    ax.fill_between(xs, ys, step="post", alpha=0.15, color=_ACCENT)

    ax.axhline(hi, color=_HI, linestyle="--", linewidth=0.8)
    ax.axhline(lo, color=_LO, linestyle="--", linewidth=0.8)
    ax.annotate(f"high {hi:,.0f}", xy=(xs[0], hi), color=_HI, fontsize=8,
                va="bottom", ha="left")
    ax.annotate(f"low {lo:,.0f}", xy=(xs[0], lo), color=_LO, fontsize=8,
                va="top", ha="left")

    cur = currency or ""
    ax.set_ylabel(f"price ({cur})" if cur else "price")
    ax.set_title("Price history")
    ax.grid(True, alpha=0.2)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    fig.autofmt_xdate()
    fig.tight_layout()

    buf = BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()
