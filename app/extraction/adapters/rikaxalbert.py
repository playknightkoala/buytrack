"""rikaxalbert.com.tw（Rika & Albert，台灣代購連線）adapter。

此站為 SPA：商品資料由內部 AjaxPro API ``GetProductById`` 載入。
- 活商品：渲染後頁面有 JSON-LD → 直接重用通用 ``parse_structured`` 取價。
- 下架商品：頁面回 200 空殼（非 404），但 API 回應中 ``"ProductHTML":null``
  → 判定為下架（Availability.DELISTED），避免被誤判成爬蟲失效。
"""
from __future__ import annotations

from app.extraction.adapters.base import Availability, BaseAdapter, ExtractionResult
from app.extraction.context import FetchContext
from app.extraction.structured import parse_structured


class RikaxAlbertAdapter(BaseAdapter):
    domains = ["rikaxalbert.com.tw"]

    async def extract(self, url: str, ctx: FetchContext) -> ExtractionResult:
        api_bodies: list[str] = []

        async with ctx.page(url) as page:
            async def on_response(resp) -> None:
                if "GetProductById" in resp.url:
                    try:
                        api_bodies.append(await resp.text())
                    except Exception:
                        pass

            page.on("response", on_response)
            # 等 API 回應（最多 ~10 秒），拿到後再給前端一點渲染時間
            for _ in range(10):
                await page.wait_for_timeout(1000)
                if api_bodies:
                    await page.wait_for_timeout(2000)
                    break
            html = await page.content()

        if api_bodies and all('"ProductHTML":null' in b for b in api_bodies):
            return ExtractionResult(
                supported=True,
                availability=Availability.DELISTED,
                method="adapter:rikaxalbert:delisted",
            )

        # 活商品：頁面渲染後有 JSON-LD，重用通用解析器
        return parse_structured(html, url, method_prefix="adapter:rikaxalbert")
