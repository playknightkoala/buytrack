"""結構化資料解析（L0 / L1 的共用解析器）。

從 HTML 解析 JSON-LD（schema.org Product/Offer）、microdata、Open Graph、RDFa，
取出價格 / 幣別 / 標題 / 上下架。多數電商為了 SEO / Google 購物都會內嵌這些資料，
因此一支通用解析器即可涵蓋大部分網站，零專屬程式碼。
"""
from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import extruct

from app.extraction.adapters.base import Availability, ExtractionResult

_PRICE_RE = re.compile(r"[-+]?\d[\d,]*\.?\d*")


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = _PRICE_RE.search(str(value).replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _norm_currency(value: Any) -> str | None:
    if not value:
        return None
    s = str(value).strip().upper()
    mapping = {"NT$": "TWD", "NTD": "TWD", "$": "TWD", "US$": "USD"}
    if s in mapping:
        return mapping[s]
    return s[:8] or None


def _norm_availability(value: Any) -> Availability:
    if not value:
        return Availability.UNKNOWN
    s = str(value).lower()
    if "outofstock" in s.replace(" ", "") or "soldout" in s.replace(" ", "") or "out_of_stock" in s:
        return Availability.OUT_OF_STOCK
    if "instock" in s.replace(" ", "") or "in_stock" in s or "available" in s:
        return Availability.IN_STOCK
    return Availability.UNKNOWN


def _types(obj: dict) -> list[str]:
    t = obj.get("@type")
    if isinstance(t, list):
        return [str(x) for x in t]
    if t:
        return [str(t)]
    return []


def _aslist(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _walk(node: Any) -> Iterator[dict]:
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def _offer_price(offer: dict) -> tuple[float | None, str | None, Availability]:
    spec = offer.get("priceSpecification")
    spec = spec[0] if isinstance(spec, list) and spec else spec
    spec = spec if isinstance(spec, dict) else {}
    price = _to_float(
        offer.get("price")
        or offer.get("lowPrice")
        or offer.get("highPrice")
        or spec.get("price")
    )
    currency = _norm_currency(offer.get("priceCurrency") or spec.get("priceCurrency"))
    avail = _norm_availability(offer.get("availability"))
    return price, currency, avail


def _segments(obj: dict) -> list[str]:
    return [t.split("/")[-1] for t in _types(obj)]


def _clean_name(obj: dict) -> str | None:
    name = obj.get("name")
    return name.strip() if isinstance(name, str) and name.strip() else None


def _from_jsonld_like(items: list, method: str) -> ExtractionResult | None:
    objects = [obj for item in items for obj in _walk(item)]

    # 標題優先序：ProductGroup 名稱 > 一般 Product 名稱。
    # （momo 等站把商品拆成多個「變體 Product」，其 name 是顏色/規格如「黑色」，
    #   真正的商品名在沒有價格的 ProductGroup 上。）
    group_name: str | None = None
    product_name: str | None = None
    for obj in objects:
        segs = _segments(obj)
        name = _clean_name(obj)
        if not name:
            continue
        if "ProductGroup" in segs and group_name is None:
            group_name = name
        elif "Product" in segs and product_name is None:
            product_name = name

    # 找第一個帶價格的 Product / ProductGroup
    for obj in objects:
        if not any(s in ("Product", "ProductGroup") for s in _segments(obj)):
            continue
        for offer in _aslist(obj.get("offers")):
            if not isinstance(offer, dict):
                continue
            price, currency, avail = _offer_price(offer)
            if price is not None:
                title = group_name or _clean_name(obj) or product_name
                return ExtractionResult(
                    supported=True,
                    price=price,
                    currency=currency,
                    title=title,
                    availability=avail,
                    method=method,
                )

    # 退而求其次：任何 Offer / AggregateOffer 物件
    for obj in objects:
        if any(s in ("Offer", "AggregateOffer") for s in _segments(obj)):
            price, currency, avail = _offer_price(obj)
            if price is not None:
                return ExtractionResult(
                    supported=True,
                    price=price,
                    currency=currency,
                    title=group_name or product_name,
                    availability=avail,
                    method=method,
                )
    return None


def _og_pairs(block: dict):
    """同時支援 uniform 後的扁平 dict 與舊版 properties 清單兩種格式。"""
    if "properties" in block and isinstance(block["properties"], list):
        for pair in block["properties"]:
            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                yield pair[0], pair[1]
        return
    for key, value in block.items():
        if key == "@context":
            continue
        yield key, value


def _from_opengraph(items: list, method: str) -> ExtractionResult | None:
    price = currency = title = None
    avail = Availability.UNKNOWN
    for block in items:
        if not isinstance(block, dict):
            continue
        for name, value in _og_pairs(block):
            n = str(name).lower()
            if n in ("product:price:amount", "og:price:amount", "product:sale_price:amount"):
                price = _to_float(value) if price is None else price
            elif n in ("product:price:currency", "og:price:currency"):
                currency = _norm_currency(value) if currency is None else currency
            elif n == "og:title" and not title:
                title = str(value).strip()
            elif n in ("product:availability", "og:availability"):
                avail = _norm_availability(value)
    if price is not None:
        return ExtractionResult(
            supported=True,
            price=price,
            currency=currency,
            title=title,
            availability=avail,
            method=method,
        )
    return None


def parse_structured(html: str, url: str, method_prefix: str = "structured") -> ExtractionResult:
    """從 HTML 解析結構化資料；找不到價格回傳 ``unsupported``。"""
    try:
        data = extruct.extract(
            html,
            base_url=url,
            syntaxes=["json-ld", "microdata", "opengraph", "rdfa"],
            uniform=True,
        )
    except Exception:
        return ExtractionResult.unsupported(method=f"{method_prefix}:parse-error")

    # JSON-LD 與 microdata（uniform 後結構相近）優先，再 OpenGraph、RDFa
    for syntax in ("json-ld", "microdata", "rdfa"):
        result = _from_jsonld_like(data.get(syntax, []), method=f"{method_prefix}:{syntax}")
        if result is not None:
            return result

    og = _from_opengraph(data.get("opengraph", []), method=f"{method_prefix}:opengraph")
    if og is not None:
        return og

    return ExtractionResult.unsupported(method=f"{method_prefix}:none")
