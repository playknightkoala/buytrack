"""petal-online.com adapter 端到端測試（需網路）。

執行：pytest tests/adapters/test_petal_online.py --run-network -q
"""
from __future__ import annotations

import pytest

from app.extraction.pipeline import extract_price

# 活商品（原測試網址 76331463 已下架，改為下架案例的專屬測試）
URL = "https://petal-online.com/itemdetail?ItemID=76631225"


@pytest.mark.network
async def test_petal_online_extracts_price():
    result = await extract_price(URL)
    assert result.has_price, f"未取得價格：method={result.method}"
    assert result.price and result.price > 0
    assert result.currency == "JPY"
    assert result.method.startswith("adapter:petal-online")


@pytest.mark.network
async def test_petal_online_delisted_detected():
    """下架商品會被導向 /error（頁面仍回 200），須判定為 DELISTED。"""
    from app.extraction.adapters.base import Availability

    result = await extract_price("https://petal-online.com/itemdetail?ItemID=76331463")  # 已下架
    assert result.supported, f"應判定為支援（下架），實際 method={result.method}"
    assert result.availability == Availability.DELISTED
