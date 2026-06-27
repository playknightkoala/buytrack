"""分層萃取管線：extract_price(url)。

依序嘗試，前一層失敗才往下：
  L_adapter  專屬 adapter（若該網域有註冊）
  L0         靜態抓取 + 結構化資料解析
  L1         Playwright 渲染後 + 結構化資料解析
全部失敗回傳 supported=False（執行時不呼叫任何 LLM）。
"""
from __future__ import annotations

import logging

from app.extraction.adapters.base import ExtractionResult
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
        except Exception:
            logger.info("L0 靜態抓取失敗: %s", url, exc_info=True)

        # L1：Playwright 渲染後 + 結構化資料
        try:
            html = await ctx.fetch_rendered(url)
            result = parse_structured(html, url, method_prefix="rendered")
            if result.has_price:
                return result
        except Exception:
            logger.info("L1 渲染抓取失敗: %s", url, exc_info=True)

        # 全部失敗：標記不支援，交由管理員透過 /add-scraper 新增 adapter
        return ExtractionResult.unsupported(method="exhausted")
