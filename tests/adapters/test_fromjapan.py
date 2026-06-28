"""fromjapan.co.jp adapter 端到端測試（需網路）。

執行：pytest tests/adapters/test_fromjapan.py --run-network -q
"""
from __future__ import annotations

import pytest

from app.extraction.pipeline import extract_price

# One Map by FROM JAPAN 的商品確認頁（內含 grail.bz 商品）
URL = (
    "https://www.fromjapan.co.jp/japan/tw/special/order/confirm/"
    "https%3A%2F%2Fwww.grail.bz%2Fitem%2Ffu1861519%2F/N_1/lgk-fjpopup_grl"
)


@pytest.mark.network
async def test_fromjapan_extracts_price():
    result = await extract_price(URL)
    assert result.has_price, f"未取得價格：method={result.method}"
    assert result.price and result.price > 0
    assert result.currency == "JPY"
    assert result.method.startswith("adapter:fromjapan")
