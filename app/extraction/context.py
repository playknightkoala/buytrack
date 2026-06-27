"""FetchContext：傳給每個 adapter 的共用工具集。

adapter 不必自己管理 httpx / Playwright / 反爬，只要透過 ctx 取得內容：
- ``await ctx.fetch_static(url)``       -> 靜態 HTML
- ``await ctx.fetch_rendered(url)``     -> Playwright 渲染後 HTML
- ``async with ctx.page(url) as page``  -> 直接操作 DOM
"""
from __future__ import annotations

import dataclasses
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import httpx
from playwright.async_api import Page

from app.config import settings
from app.extraction.antibot import AntiBot
from app.extraction.browser import BrowserManager


def domain_of(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


@dataclasses.dataclass
class FetchContext:
    http: httpx.AsyncClient
    antibot: AntiBot
    browser: BrowserManager

    async def fetch_static(self, url: str, wait: bool = True) -> httpx.Response:
        if wait:
            await self.antibot.throttle(domain_of(url))
        return await self.http.get(url, headers=self.antibot.headers())

    async def fetch_static_html(self, url: str, wait: bool = True) -> str:
        resp = await self.fetch_static(url, wait=wait)
        resp.raise_for_status()
        return resp.text

    async def fetch_rendered(self, url: str, wait_selector: str | None = None) -> str:
        await self.antibot.throttle(domain_of(url))
        return await self.browser.render(url, wait_selector=wait_selector)

    @asynccontextmanager
    async def page(self, url: str, wait_selector: str | None = None) -> AsyncIterator[Page]:
        await self.antibot.throttle(domain_of(url))
        async with self.browser.page(url, wait_selector=wait_selector) as p:
            yield p


@asynccontextmanager
async def build_context() -> AsyncIterator[FetchContext]:
    """建立並在使用後清理整條萃取所需的資源。"""
    antibot = AntiBot()
    browser = BrowserManager(antibot)
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=settings.request_timeout_sec,
        proxy=antibot.pick_proxy(),
    ) as http:
        ctx = FetchContext(http=http, antibot=antibot, browser=browser)
        try:
            yield ctx
        finally:
            await browser.stop()
            await antibot.aclose()
