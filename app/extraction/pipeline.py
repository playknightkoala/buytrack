"""分層萃取管線：extract_price(url)。

依序嘗試，前一層失敗才往下：
  L_adapter  專屬 adapter（若該網域有註冊）
  L0         靜態抓取 + 結構化資料解析
  L1         Playwright 渲染後 + 結構化資料解析
全部失敗回傳 supported=False（執行時不呼叫任何 LLM）。
"""
from __future__ import annotations

import logging

import httpx

from app.extraction.adapters.base import Availability, ExtractionResult
from app.extraction.adapters.registry import get_adapter
from app.extraction.context import build_context
from app.extraction.structured import parse_structured

logger = logging.getLogger(__name__)


async def extract_price(url: str) -> ExtractionResult:
    async with build_context() as ctx:
        # L_adapter：專屬 adapter 優先
        adapter = get_adapter(url)
        if adapter is not None:
            try:
                result = await adapter.extract(url, ctx)
                if result.has_price:
                    return result
                logger.info("adapter 未取得價格，往下層 fallback: %s", url)
            except Exception:
                logger.exception("adapter 例外，往下層 fallback: %s", url)

        # L0：靜態 HTML + 結構化資料
        try:
            html = await ctx.fetch_static_html(url)
            result = parse_structured(html, url, method_prefix="static")
            if result.has_price:
                return result
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code in (404, 410):
                # 商品頁不存在 → 下架/停售（與「爬蟲失效」區分）
                return ExtractionResult(
                    supported=True,
                    availability=Availability.DELISTED,
                    method=f"http:{code}",
                )
            logger.info("L0 靜態抓取失敗，改用渲染層: %s (HTTP %s)", url, code)
        except Exception as exc:
            # L0 失敗（如逾時）屬正常情形，會自動往下走 L1；只記一行摘要
            logger.info("L0 靜態抓取失敗，改用渲染層: %s (%s)", url, exc)

        # L1：Playwright 渲染後 + 結構化資料
        try:
            html = await ctx.fetch_rendered(url)
            result = parse_structured(html, url, method_prefix="rendered")
            if result.has_price:
                return result
        except Exception as exc:
            logger.info("L1 渲染抓取失敗: %s (%s)", url, exc)

        # 全部失敗：標記不支援，交由管理員透過 /add-scraper 新增 adapter
        return ExtractionResult.unsupported(method="exhausted")
