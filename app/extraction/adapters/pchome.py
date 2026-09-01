"""24h.pchome.com.tw（PChome 24h 購物）adapter。

網頁端對自動化請求會回 429（連靜態頁也可能被擋），且價格是 JS 注入後才有
JSON-LD，因此改走官方公開 API（純 JSON、輕量、穩定）：

- 售價/庫存（即時）：``/ecshop/prodapi/v2/prod/button&id=<PID>&fields=Id,Price,Qty``
  回傳各變體陣列，``Price.P``＝售價、``Price.M``＝市價、``Qty``＝庫存。
- 商品名稱（CDN 快取）：``/cdn/ecshop/prodapi/v2/prod/<PID>&fields=Id,Name,Price&_callback=cb``
  為 JSONP，需剝除外層回呼。

商品不存在時 API 仍回 200，但變體不含 ``Price`` 欄位 → 判定為下架。
"""
from __future__ import annotations

import json
import re

from app.extraction.adapters.base import Availability, BaseAdapter, ExtractionResult
from app.extraction.context import FetchContext

_ECAPI = "https://ecapi.pchome.com.tw"
_PID_RE = re.compile(r"/prod/([A-Za-z0-9]+-[A-Za-z0-9]+)")
_JSONP_RE = re.compile(r"cb\((.*?)\)\s*;?\s*\}?\s*catch", re.S)


def _parse_pid(url: str) -> str | None:
    m = _PID_RE.search(url)
    return m.group(1) if m else None


def _to_float(value) -> float | None:
    if value in (None, "", 0):
        return float(value) if value == 0 else None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class PChomeAdapter(BaseAdapter):
    domains = ["pchome.com.tw"]

    async def extract(self, url: str, ctx: FetchContext) -> ExtractionResult:
        pid = _parse_pid(url)
        if pid is None:
            return ExtractionResult.unsupported(method="adapter:pchome:bad-url")

        # 1) 即時售價與庫存
        resp = await ctx.fetch_static(
            f"{_ECAPI}/ecshop/prodapi/v2/prod/button&id={pid}&fields=Id,Price,Qty"
        )
        resp.raise_for_status()
        try:
            variants = json.loads(resp.text) if resp.text.strip() else []
        except ValueError:
            variants = []
        if not isinstance(variants, list):
            variants = []

        priced = [v for v in variants if isinstance(v, dict) and isinstance(v.get("Price"), dict)]
        if not priced:
            # API 回應不含價格 → 商品已下架/不存在
            return ExtractionResult(
                supported=True,
                availability=Availability.DELISTED,
                method="adapter:pchome:delisted",
            )

        price = _to_float(priced[0]["Price"].get("P"))
        qty = sum(v.get("Qty") or 0 for v in priced)

        # 2) 商品名稱（CDN JSONP；失敗不影響取價，沿用既有標題）
        title: str | None = None
        try:
            cdn = await ctx.fetch_static(
                f"{_ECAPI}/cdn/ecshop/prodapi/v2/prod/{pid}"
                f"&fields=Id,Name,Price&_callback=cb"
            )
            m = _JSONP_RE.search(cdn.text)
            if m:
                for entry in json.loads(m.group(1)).values():
                    name = (entry or {}).get("Name")
                    if isinstance(name, str) and name.strip():
                        title = name.strip()
                        break
        except Exception:
            pass

        if price is None:
            return ExtractionResult.unsupported(method="adapter:pchome:no-price")

        return ExtractionResult(
            supported=True,
            price=price,
            currency="TWD",
            title=title,
            availability=Availability.IN_STOCK if qty > 0 else Availability.OUT_OF_STOCK,
            method="adapter:pchome",
        )
