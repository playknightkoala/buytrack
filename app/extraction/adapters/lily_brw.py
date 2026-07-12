"""lily-brw.com（LILY BROWN 日本官方通販）adapter。

頁面為 ASP.NET + JS 渲染，無 JSON-LD / OpenGraph。
主商品區塊在 `.block-title`（含 `h1.ttl` 商品名與 `.price` 價格）；
頁面上另有相關商品（`.block-related .salePrice`）與最近瀏覽（`#sliderRecent`）
的價格，必須以 `.block-title` 範圍排除。

價格文字格式：
  無特價：¥13,970税込
  有特價：¥13,970税込 →¥8,382税込40%OFF
取「最後一個 ¥金額」即為現售價。
"""
from __future__ import annotations

import re

from app.extraction.adapters.base import Availability, BaseAdapter, ExtractionResult
from app.extraction.context import FetchContext

_YEN_ALL = re.compile(r"[¥￥]\s*([\d,]+)")


class LilyBrownAdapter(BaseAdapter):
    domains = ["lily-brw.com"]

    async def extract(self, url: str, ctx: FetchContext) -> ExtractionResult:
        async with ctx.page(url, wait_selector=".block-title .price") as page:
            price_el = await page.query_selector(".block-title .price")
            price_text = await price_el.inner_text() if price_el else ""
            title_el = await page.query_selector(".block-title h1.ttl")
            title = (await title_el.inner_text()).strip() if title_el else None

        amounts = _YEN_ALL.findall(price_text or "")
        if not amounts:
            return ExtractionResult.unsupported(method="adapter:lily-brw")

        price = float(amounts[-1].replace(",", ""))  # 最後一個金額＝現售價（特價優先）

        return ExtractionResult(
            supported=True,
            price=price,
            currency="JPY",
            title=title or None,
            availability=Availability.IN_STOCK,
            method="adapter:lily-brw",
        )
