"""訊息顯示共用工具：購物網名稱對應、縮短網址連結。"""
from __future__ import annotations

import html

# key 用可比對的網域字尾；子網域自動對應
SITE_NAMES = {
    "momoshop.com.tw": "momo購物網",
    "pchome.com.tw": "PChome",
    "books.com.tw": "博客來",
    "shopee.tw": "蝦皮購物",
    "ruten.com.tw": "露天市集",
    "yahoo.com.tw": "Yahoo購物",
    "coupang.com": "Coupang 酷澎",
    "fromjapan.co.jp": "FROM JAPAN",
    "grail.bz": "GRL",
    "amazon.co.jp": "Amazon JP",
    "amazon.com": "Amazon",
}


def short_link(url: str, max_len: int = 45) -> str:
    """回傳 HTML 超連結：顯示文字超過 max_len 會截短加 …，點擊仍連到完整網址。

    使用端訊息需以 parse_mode="HTML" 發送。
    """
    display = url if len(url) <= max_len else url[: max_len - 1] + "…"
    return f'<a href="{html.escape(url, quote=True)}">{html.escape(display)}</a>'


def site_label(domain: str | None) -> str:
    """由網域對應好讀的購物網名稱；未知則直接顯示網域。"""
    if not domain:
        return "未知網站"
    d = domain.lower()
    for suffix, name in SITE_NAMES.items():
        if d == suffix or d.endswith("." + suffix):
            return name
    return domain
