"""fromjapan.co.jp（One Map by FROM JAPAN，日本代購）adapter。

頁面為 Vue 動態渲染，無 JSON-LD / OpenGraph，且價格元素只用 Tailwind/Vuesax
utility class（如 `text-sm text-grey`），無語意化選擇器可用。
因此改以「在 DOM 中找出『直接文字』符合 `數字 + 日元/日圓` 的元素」來取價，
比對整份 HTML（含大量 script）更穩定、不會誤抓到腳本內的數字。
"""
from __future__ import annotations

from app.extraction.adapters.base import Availability, BaseAdapter, ExtractionResult
from app.extraction.context import FetchContext

# 走訪 DOM，回傳第一個「自身直接文字」含「數字 日元/日圓」的數字字串（如 "1,299"）。
_PRICE_JS = r"""
() => {
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
  while (walker.nextNode()) {
    const el = walker.currentNode;
    const own = Array.from(el.childNodes)
      .filter(n => n.nodeType === 3)
      .map(n => n.textContent)
      .join('');
    const m = own.match(/([\d,]+)\s*日[元圓]/);
    if (m) return m[1];
  }
  return null;
}
"""


class FromJapanAdapter(BaseAdapter):
    domains = ["fromjapan.co.jp"]

    async def extract(self, url: str, ctx: FetchContext) -> ExtractionResult:
        async with ctx.page(url) as page:
            # Vue 應用需要時間渲染價格，最多等約 8 秒
            price_str = None
            for _ in range(10):
                price_str = await page.evaluate(_PRICE_JS)
                if price_str:
                    break
                await page.wait_for_timeout(800)
            title = await page.title()

        if not price_str:
            return ExtractionResult.unsupported(method="adapter:fromjapan")

        try:
            price = float(price_str.replace(",", ""))
        except ValueError:
            return ExtractionResult.unsupported(method="adapter:fromjapan")

        # 標題格式："<商品名> 商品細節 | GRL | One Map by FROM JAPAN"
        name = (title.split("|")[0].replace("商品細節", "").strip()) or None

        return ExtractionResult(
            supported=True,
            price=price,
            currency="JPY",
            title=name,
            availability=Availability.IN_STOCK,
            method="adapter:fromjapan",
        )
