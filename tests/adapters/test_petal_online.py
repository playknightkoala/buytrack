"""petal-online.com adapter 端到端測試（需網路）。

執行：pytest tests/adapters/test_petal_online.py --run-network -q
"""
from __future__ import annotations

import pytest

from app.extraction.pipeline import extract_price

URL = "https://petal-online.com/itemdetail?ItemID=76331463"


@pytest.mark.network
async def test_petal_online_extracts_price():
    result = await extract_price(URL)
    assert result.has_price, f"未取得價格：method={result.method}"
    assert result.price and result.price > 0
    assert result.currency == "JPY"
    assert result.method.startswith("adapter:petal-online")
