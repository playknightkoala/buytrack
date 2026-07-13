"""目錄報告 PDF：新增商品區 / 調價商品區 / 商品區 三段式。

以 HTML 模板組版，直接用 worker 內建的 Playwright/Chromium 產 PDF
（映像已安裝 Noto CJK 字型，中日文正常顯示）。
"""
from __future__ import annotations

import asyncio
import base64
import datetime as dt
import html
import io
import logging
from zoneinfo import ZoneInfo

import httpx
from playwright.async_api import async_playwright

from app.catalog.base import CatalogItem
from app.catalog.differ import CatalogDiff

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Asia/Taipei")

_CSS = """
body{font-family:'Noto Sans CJK TC','Noto Sans CJK JP',sans-serif;font-size:11px;color:#222;margin:24px}
h1{font-size:18px;margin:0 0 2px}
.sub{color:#888;font-size:11px;margin-bottom:16px}
h2{font-size:14px;border-left:4px solid #1ab6b6;padding-left:8px;margin:22px 0 8px}
table{width:100%;border-collapse:collapse}
th{background:#f5f5f5;text-align:left;font-size:10px;color:#666}
td,th{border-bottom:1px solid #e3e3e3;padding:5px 6px;vertical-align:middle}
img{width:150px;height:150px;object-fit:cover;border-radius:6px}
a{color:#1a73e8;text-decoration:none;word-break:break-all}
.price{white-space:nowrap;font-weight:bold}
.old{color:#999;text-decoration:line-through;font-weight:normal}
.up{color:#c0392b}.down{color:#27ae60}
.empty{color:#999;padding:8px 2px}
.badge{display:inline-block;background:#fdecea;color:#c0392b;font-size:9px;border-radius:3px;padding:1px 4px;margin-left:4px}
"""


async def fetch_image_data(
    urls: list[str | None], max_px: int = 320, quality: int = 80, concurrency: int = 8
) -> dict[str, str]:
    """下載商品圖並縮到顯示尺寸、壓成 JPEG data URI。

    直接讓 Chromium 嵌原圖會產生巨大 PDF（原圖以近無損方式嵌入）；
    先縮圖再內嵌可把整份報告控制在幾 MB 內，且不必等遠端圖片載入。
    失敗的圖片略過（HTML 端 fallback 回原網址）。
    """
    from PIL import Image  # 由 matplotlib 相依提供

    out: dict[str, str] = {}
    sem = asyncio.Semaphore(concurrency)
    unique = [u for u in dict.fromkeys(urls) if u]

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        async def one(url: str) -> None:
            async with sem:
                try:
                    r = await client.get(url)
                    r.raise_for_status()
                    im = Image.open(io.BytesIO(r.content)).convert("RGB")
                    im.thumbnail((max_px, max_px))
                    buf = io.BytesIO()
                    im.save(buf, "JPEG", quality=quality)
                    out[url] = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
                except Exception:
                    logger.info("縮圖失敗，改用原網址：%s", url)

        await asyncio.gather(*(one(u) for u in unique))
    return out


def _money(value: float | None) -> str:
    return f"{value:,.0f}" if value is not None else "—"


# build_report_html 期間使用的圖片對應（url -> data URI）
_IMAGE_DATA: dict[str, str] = {}


def _img(item: CatalogItem) -> str:
    if not item.image_url:
        return ""
    src = _IMAGE_DATA.get(item.image_url, item.image_url)
    return f'<img src="{html.escape(src, quote=True)}">'


def _link(item: CatalogItem) -> str:
    url = html.escape(item.product_url, quote=True)
    return f'<a href="{url}">{url}</a>'


def _sale_badge(item: CatalogItem) -> str:
    if item.compare_at_price and item.price and item.compare_at_price > item.price:
        return '<span class="badge">特價中</span>'
    return ""


def _rows_basic(items: list[CatalogItem]) -> str:
    rows = []
    for it in items:
        rows.append(
            f"<tr><td>{_img(it)}</td>"
            f"<td>{html.escape(it.title)}{_sale_badge(it)}<br>{_link(it)}</td>"
            f'<td class="price">{_money(it.price)}</td></tr>'
        )
    return "".join(rows)


def _section(title: str, inner: str, empty_text: str) -> str:
    body = inner or f'<div class="empty">{empty_text}</div>'
    return f"<h2>{title}</h2>" + (f"<table><tr><th>圖片</th><th>商品</th><th>價格</th></tr>{body}</table>" if inner else body)


def build_report_html(
    label: str,
    site: str,
    diff: CatalogDiff,
    all_items: list[CatalogItem],
    baseline: bool = False,
    image_data: dict[str, str] | None = None,
) -> str:
    global _IMAGE_DATA
    _IMAGE_DATA = image_data or {}
    now = dt.datetime.now(_TZ).strftime("%Y-%m-%d %H:%M")
    parts = [f"<style>{_CSS}</style>"]
    parts.append(f"<h1>📦 {html.escape(label)}</h1>")
    summary = f"{site}｜{now}｜共 {len(all_items)} 件"
    if not baseline:
        summary += f"｜🆕 新增 {len(diff.new_items)}｜💰 調價 {len(diff.price_changes)}"
    parts.append(f'<div class="sub">{html.escape(site and summary)}</div>')

    if baseline:
        parts.append(
            '<div class="sub">（首次建立基準快照：以下為目前完整目錄，之後的新增與調價將列於前兩區）</div>'
        )
    else:
        parts.append(_section("🆕 新增商品區", _rows_basic(diff.new_items), "本次沒有新增商品"))

        rows = []
        for ch in diff.price_changes:
            it = ch.item
            klass = "up" if (it.price or 0) > ch.old_price else "down"
            arrow = "▲" if klass == "up" else "▼"
            rows.append(
                f"<tr><td>{_img(it)}</td>"
                f"<td>{html.escape(it.title)}{_sale_badge(it)}<br>{_link(it)}</td>"
                f'<td class="price"><span class="old">{_money(ch.old_price)}</span> → '
                f'<span class="{klass}">{_money(it.price)} {arrow}</span></td></tr>'
            )
        inner = "".join(rows)
        body = inner or '<div class="empty">本次沒有價格調整</div>'
        parts.append(
            "<h2>💰 調價商品區</h2>"
            + (f"<table><tr><th>圖片</th><th>商品</th><th>價格變化</th></tr>{inner}</table>" if inner else body)
        )

    parts.append(_section("📦 商品區（完整目錄）", _rows_basic(all_items), "目錄目前沒有商品"))
    return "".join(parts)


async def html_to_pdf(html_content: str) -> bytes:
    """以 Chromium 將 HTML 轉為 A4 PDF（圖片已內嵌 data URI，無需等遠端載入）。"""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(html_content, wait_until="load", timeout=60_000)
            await page.wait_for_timeout(300)
            return await page.pdf(
                format="A4",
                print_background=True,
                margin={"top": "12mm", "bottom": "12mm", "left": "10mm", "right": "10mm"},
            )
        finally:
            await browser.close()


async def render_report(
    label: str,
    site: str,
    diff: CatalogDiff,
    all_items: list[CatalogItem],
    baseline: bool = False,
) -> bytes:
    """一站式：縮圖內嵌 → 組 HTML → 產 PDF。"""
    image_data = await fetch_image_data([i.image_url for i in all_items])
    html_content = build_report_html(
        label, site, diff, all_items, baseline=baseline, image_data=image_data
    )
    return await html_to_pdf(html_content)
