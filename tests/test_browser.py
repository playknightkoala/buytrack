from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.extraction.browser import BrowserManager, uses_full_chromium


@pytest.mark.parametrize("url, expected", [
    ("https://www.momoshop.com.tw/goods/GoodsDetail.jsp?i_code=1", True),
    ("https://momoshop.com.tw/product/1", True),
    ("https://m.momoshop.com.tw/", True),
    ("https://momoshop.com.tw.example.org/", False),
    ("https://24h.pchome.com.tw/prod/1", False),
])
def test_full_chromium_domain(url, expected):
    assert uses_full_chromium(url) is expected


async def test_separate_browser_launches_and_cleanup():
    antibot = MagicMock()
    antibot.pick_proxy.return_value = "http://proxy.example:8080"
    pw = MagicMock()
    pw.chromium.executable_path = "/chromium/chrome"
    regular, full = AsyncMock(), AsyncMock()
    pw.chromium.launch = AsyncMock(side_effect=[regular, full])
    pw.stop = AsyncMock()
    starter = MagicMock()
    starter.start = AsyncMock(return_value=pw)
    with patch("app.extraction.browser.async_playwright", return_value=starter):
        manager = BrowserManager(antibot)
        await manager.start()
        await manager.start(full_chromium=True)
        await manager.start(full_chromium=True)
        assert pw.chromium.launch.await_count == 2
        normal_args = pw.chromium.launch.call_args_list[0].kwargs
        full_args = pw.chromium.launch.call_args_list[1].kwargs
        assert "executable_path" not in normal_args
        assert full_args["executable_path"] == "/chromium/chrome"
        assert full_args["args"] == ["--headless=new"]
        assert full_args["proxy"] == {"server": "http://proxy.example:8080"}
        await manager.stop()
        full.close.assert_awaited_once()
        regular.close.assert_awaited_once()
        pw.stop.assert_awaited_once()
