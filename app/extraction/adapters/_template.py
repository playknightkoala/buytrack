"""專屬 adapter 樣板 —— 複製這支來新增一個網站的爬蟲。

使用步驟（也可由 Claude Code 的 /add-scraper skill 自動完成）：
1. 複製本檔為 ``app/extraction/adapters/<domain>.py``（例如 ``shopee_tw.py``）。
2. 把類別改名、填入 ``domains``。
3. 在 ``extract()`` 內取得頁面並回傳 ``ExtractionResult``。
4. 在 ``tests/adapters/test_<domain>.py`` 寫一個用真實網址驗證的測試。

注意事項（界線）：
- 不要呼叫任何外部 LLM API；萃取必須是純解析邏輯。
- 透過 ``ctx`` 取得頁面（已內建反爬限流），不要自己另開連線繞過限流。
- 一定要回傳 ``ExtractionResult``；拿不到價格就回傳 ``ExtractionResult.unsupported()``。

本檔 ``domains`` 為空，因此不會被註冊。
"""
from __future__ import annotations

from app.extraction.adapters.base import Availability, BaseAdapter, ExtractionResult
from app.extraction.context import FetchContext

# 也可重用通用結構化資料解析器：
# from app.extraction.structured import parse_structured


class TemplateAdapter(BaseAdapter):
    # TODO: 填入此 adapter 負責的網域（留空代表不註冊）
    domains: list[str] = []

    async def extract(self, url: str, ctx: FetchContext) -> ExtractionResult:
        # 範例 A：頁面其實有結構化資料，渲染後直接重用通用解析器
        # html = await ctx.fetch_rendered(url, wait_selector="...")
        # return parse_structured(html, url, method_prefix="adapter:template")

        # 範例 B：用 Playwright 操作 DOM 取價
        # async with ctx.page(url, wait_selector=".price") as page:
        #     price_text = await page.inner_text(".price")
        #     title = await page.inner_text("h1")
        #     ...

        # TODO: 實作真正的萃取邏輯
        raise NotImplementedError

        # 取得資料後回傳：
        # return ExtractionResult(
        #     supported=True,
        #     price=...,
        #     currency="TWD",
        #     title=...,
        #     availability=Availability.IN_STOCK,
        #     method="adapter:template",
        # )
