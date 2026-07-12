"""lily-brw.com adapter 端到端測試（需網路）。

執行：pytest tests/adapters/test_lily_brw.py --run-network -q
"""
from __future__ import annotations

import pytest

from app.extraction.pipeline import extract_price

URL = (
    "https://lily-brw.com/Form/Product/ProductDetail.aspx"
    "?shop=0&pid=LWNT261090&vid=LWNT26109093399&bid=LBW01&cid=&_type=&cat=&swrd="
)


@pytest.mark.network
async def test_lily_brw_extracts_price():
    result = await extract_price(URL)
    assert result.has_price, f"未取得價格：method={result.method}"
    assert result.price and result.price > 0
    assert result.currency == "JPY"
    assert result.method.startswith("adapter:lily-brw")
