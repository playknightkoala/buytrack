"""通用目錄 adapter：Cyberbiz / Shopify 的 ``/collections/<handle>`` JSON 端點。

兩段策略：
1. **Cyberbiz** ``search_products.json?page=N&per=100``（如 jimiskateshop.com）：
   有 ``total_count/total_pages`` 正規翻頁，欄位含最低價、特價、庫存、主圖。
2. **Shopify** ``products.json?limit=250&page=N``：page 遞增到空頁；
   另設「重複頁」保護（部分站對超界 page 回同一頁）。

適用大量 Shopify / Cyberbiz 建站的網站；其他平台可另寫網域專屬 adapter。
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from app.catalog.base import BaseCatalogAdapter, CatalogItem

_COLLECTION_RE = re.compile(r"^(?:/[a-z]{2}(?:-[A-Za-z]{2,4})?)?/collections/([^/?#]+)")
_MAX_PAGES = 100  # 安全上限


def parse_collection(url: str) -> tuple[str, str] | None:
    """從目錄網址取出 (base, handle)；支援語系前綴（/zh-TW/collections/...）。"""
    parts = urlsplit(url)
    m = _COLLECTION_RE.match(parts.path)
    if not m or not parts.hostname:
        return None
    return f"{parts.scheme}://{parts.netloc}", m.group(1)


def _to_float(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def _abs_url(base: str, url: str | None) -> str | None:
    if not url:
        return None
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return base + url
    return url


# ---------- Cyberbiz search_products.json ----------

def _cyberbiz_item(p: dict, base: str) -> CatalogItem | None:
    handle = p.get("handle")
    title = (p.get("title") or "").strip()
    if not handle or not title:
        return None
    image = None
    feat = p.get("featured_image")
    if isinstance(feat, dict):
        image = feat.get("grande") or feat.get("original") or next(iter(feat.values()), None)
    elif isinstance(feat, str):
        image = feat
    return CatalogItem(
        key=f"/products/{handle}",
        title=title,
        product_url=f"{base}/products/{handle}",
        price=_to_float(p.get("cheapest_variant_price")),
        compare_at_price=_to_float(p.get("cheapest_variant_compare_at_price")),
        image_url=_abs_url(base, image),
        available=p.get("in_stock") if isinstance(p.get("in_stock"), bool) else None,
    )


async def _fetch_cyberbiz(base: str, handle: str, ctx) -> list[CatalogItem] | None:
    """成功回傳商品清單；端點不存在/非 JSON 回傳 None（交給 Shopify fallback）。"""
    items: list[CatalogItem] = []
    seen: set[str] = set()
    total_pages = 1
    page = 1
    while page <= min(total_pages, _MAX_PAGES):
        resp = await ctx.fetch_static(
            f"{base}/collections/{handle}/search_products.json?page={page}&per=100"
        )
        if resp.status_code != 200:
            return None if page == 1 else items
        try:
            data = resp.json()
        except ValueError:
            return None if page == 1 else items
        if not isinstance(data, dict) or "products" not in data:
            return None if page == 1 else items
        total_pages = int(data.get("total_pages") or 1)
        for p in data["products"]:
            item = _cyberbiz_item(p, base)
            if item is not None and item.key not in seen:
                seen.add(item.key)
                items.append(item)
        page += 1
    return items


# ---------- Shopify products.json ----------

def _shopify_item(p: dict, base: str) -> CatalogItem | None:
    url_path = p.get("url") or (f"/products/{p['handle']}" if p.get("handle") else None)
    title = (p.get("title") or "").strip()
    if not url_path or not title:
        return None

    variants = p.get("variants") or []
    v0 = variants[0] if variants else {}
    price = _to_float(p.get("price"))
    if price is None:
        price = _to_float(v0.get("price"))
    compare_at = _to_float(p.get("compare_at_price"))
    if compare_at is None:
        compare_at = _to_float(v0.get("compare_at_price"))

    image = p.get("photo")
    if not image:
        images = p.get("images") or []
        if images and isinstance(images[0], dict):
            image = images[0].get("src")

    available: bool | None = None
    flags = [v.get("available") for v in variants if isinstance(v.get("available"), bool)]
    if flags:
        available = any(flags)
    else:
        qtys = [v.get("inventory_quantity") for v in variants
                if isinstance(v.get("inventory_quantity"), (int, float))]
        if qtys:
            available = sum(qtys) > 0

    return CatalogItem(
        key=url_path,
        title=title,
        product_url=base + url_path,
        price=price,
        compare_at_price=compare_at,
        image_url=_abs_url(base, image),
        available=available,
    )


async def _fetch_shopify(base: str, handle: str, ctx) -> list[CatalogItem]:
    items: list[CatalogItem] = []
    seen: set[str] = set()
    for page in range(1, _MAX_PAGES + 1):
        resp = await ctx.fetch_static(
            f"{base}/collections/{handle}/products.json?limit=250&page={page}"
        )
        resp.raise_for_status()
        data = resp.json()
        products = data if isinstance(data, list) else data.get("products", [])
        if not products:
            break
        new_in_page = 0
        for p in products:
            item = _shopify_item(p, base)
            if item is not None and item.key not in seen:
                seen.add(item.key)
                items.append(item)
                new_in_page += 1
        if new_in_page == 0:  # 重複頁（站方忽略 page 參數）→ 停止
            break
    return items


class ProductsJsonCatalogAdapter(BaseCatalogAdapter):
    """通用 adapter：domains 留空、不進 registry；由 registry 對 /collections/ 網址 fallback。"""

    domains: list[str] = []

    async def fetch_all(self, collection_url: str, ctx) -> list[CatalogItem]:
        parsed = parse_collection(collection_url)
        if parsed is None:
            raise ValueError(f"不是 /collections/ 目錄網址：{collection_url}")
        base, handle = parsed

        items = await _fetch_cyberbiz(base, handle, ctx)
        if items:  # None（端點不存在）或空清單都改走 Shopify
            return items
        return await _fetch_shopify(base, handle, ctx)
