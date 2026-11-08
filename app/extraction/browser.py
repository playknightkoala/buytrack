"""Playwright 瀏覽器管理（L1 渲染層）。

提供：
- ``render(url)``：渲染頁面後回傳最終 HTML。
- ``page(url)``：給需要操作 DOM 的 adapter 使用的 page context manager。
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from playwright.async_api import Browser, Page, async_playwright

from app.config import settings
from app.extraction.antibot import AntiBot


def uses_full_chromium(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host == "momoshop.com.tw" or host.endswith(".momoshop.com.tw")


class BrowserManager:
    def __init__(self, antibot: AntiBot) -> None:
        self._antibot = antibot
        self._pw = None
        self._browser: Browser | None = None
        self._full_browser: Browser | None = None

    async def start(self, full_chromium: bool = False) -> None:
        if self._pw is None:
            self._pw = await async_playwright().start()
        browser = self._full_browser if full_chromium else self._browser
        if browser is None:
            proxy = self._antibot.pick_proxy()
            launch_kwargs: dict = {"headless": True}
            if full_chromium:
                # 明確使用完整 Chromium，而非獨立的 headless shell。
                # Playwright 1.48 使用執行檔路徑與 new headless 參數。
                launch_kwargs["executable_path"] = self._pw.chromium.executable_path
                launch_kwargs["args"] = ["--headless=new"]
            if proxy:
                launch_kwargs["proxy"] = {"server": proxy}
            browser = await self._pw.chromium.launch(**launch_kwargs)
            if full_chromium:
                self._full_browser = browser
            else:
                self._browser = browser

    async def stop(self) -> None:
        if self._full_browser is not None:
            await self._full_browser.close()
            self._full_browser = None
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._pw is not None:
            await self._pw.stop()
            self._pw = None

    @asynccontextmanager
    async def page(self, url: str, wait_selector: str | None = None) -> AsyncIterator[Page]:
        full_chromium = uses_full_chromium(url)
        await self.start(full_chromium=full_chromium)
        browser = self._full_browser if full_chromium else self._browser
        assert browser is not None
        context = await browser.new_context(
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
