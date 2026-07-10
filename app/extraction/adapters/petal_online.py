"""petal-online.com（PETAL ONLINE，日本服飾）adapter。

頁面無 JSON-LD / OpenGraph，價格在 `.price_box` 內：
`.strike`＝原價、`.special`＝特價（如有）。現售價優先取特價，否則取原價。
"""
from __future__ import annotations

import re

from app.extraction.adapters.base import Availability, BaseAdapter, ExtractionResult
from app.extraction.context import FetchContext

_YEN = re.compile(r"[¥￥]\s*([\d,]+)")


class PetalOnlineAdapter(BaseAdapter):
    domains = ["petal-online.com"]

    async def extract(self, url: str, ctx: FetchContext) -> ExtractionResult:
        async with ctx.page(url, wait_selector=".price_box") as page:
            # 特價優先；沒有特價時用整個價格區塊（會抓到原價）
            el = await page.query_selector(".special")
            if el is None:
                el = await page.query_selector(".price_box")
            price_text = await el.inner_text() if el else ""
            title = await page.title()

        m = _YEN.search(price_text or "")
        if not m:
            return ExtractionResult.unsupported(method="adapter:petal-online")

        price = float(m.group(1).replace(",", ""))
        # 標題格式："<商品名>｜PETAL ONLINE（ペタルオンライン）"
        name = (title.split("｜")[0].strip() or None) if title else None

        return ExtractionResult(
            supported=True,
            price=price,
            currency="JPY",
            title=name,
            availability=Availability.IN_STOCK,
            method="adapter:petal-online",
        )
