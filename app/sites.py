"""購物網站網域 → 好讀名稱對應（bot 顯示與提醒共用）。"""
from __future__ import annotations

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


def site_label(domain: str | None) -> str:
    """由網域對應好讀的購物網名稱；未知則直接顯示網域。"""
    if not domain:
        return "未知網站"
    d = domain.lower()
    for suffix, name in SITE_NAMES.items():
        if d == suffix or d.endswith("." + suffix):
            return name
    return domain
