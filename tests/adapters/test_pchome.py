"""24h.pchome.com.tw adapter 端到端測試（需網路）。

執行：pytest tests/adapters/test_pchome.py --run-network -q
"""
from __future__ import annotations

import pytest

from app.extraction.pipeline import extract_price

URL = "https://24h.pchome.com.tw/prod/DIBKVL-A900ICUI6"


@pytest.mark.network
async def test_pchome_extracts_price():
    result = await extract_price(URL)
    assert result.has_price, f"未取得價格：method={result.method}"
    assert result.price and result.price > 0
    assert result.currency == "TWD"
    assert result.method.startswith("adapter:pchome")
