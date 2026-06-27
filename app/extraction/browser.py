"""Playwright 瀏覽器管理（L1 渲染層）。

提供：
- ``render(url)``：渲染頁面後回傳最終 HTML。
- ``page(url)``：給需要操作 DOM 的 adapter 使用的 page context manager。
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from playwright.async_api import Browser, Page, async_playwright

from app.config import settings
from app.extraction.antibot import AntiBot


class BrowserManager:
    def __init__(self, antibot: AntiBot) -> None:
        self._antibot = antibot
        self._pw = None
        self._browser: Browser | None = None

    async def start(self) -> None:
        if self._browser is None:
            self._pw = await async_playwright().start()
            proxy = self._antibot.pick_proxy()
            launch_kwargs: dict = {"headless": True}
            if proxy:
                launch_kwargs["proxy"] = {"server": proxy}
            self._browser = await self._pw.chromium.launch(**launch_kwargs)

    async def stop(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._pw is not None:
            await self._pw.stop()
            self._pw = None

    @asynccontextmanager
    async def page(self, url: str, wait_selector: str | None = None) -> AsyncIterator[Page]:
        await self.start()
        assert self._browser is not None
        context = await self._browser.new_context(
            user_agent=self._antibot.user_agent(),
            locale="zh-TW",
        )
        page = await context.new_page()
        try:
            await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=int(settings.render_timeout_sec * 1000),
            )
            if wait_selector:
                try:
                    await page.wait_for_selector(
                        wait_selector, timeout=int(settings.render_timeout_sec * 1000)
                    )
                except Exception:
                    pass  # 選擇器沒等到也讓 adapter 自行決定
            yield page
        finally:
            await context.close()

    async def render(self, url: str, wait_selector: str | None = None) -> str:
        async with self.page(url, wait_selector=wait_selector) as page:
            return await page.content()
