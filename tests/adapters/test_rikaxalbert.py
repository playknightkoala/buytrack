"""rikaxalbert.com.tw adapter 端到端測試（需網路）。

執行：pytest tests/adapters/test_rikaxalbert.py --run-network -q

以「已下架商品」為測試對象（下架商品不會復活，比活商品連結穩定）：
驗證 200 空殼頁能被正確判定為 DELISTED，而非誤判爬蟲失效。
"""
from __future__ import annotations

import pytest

from app.extraction.adapters.base import Availability
from app.extraction.pipeline import extract_price

DELISTED_URL = "https://www.rikaxalbert.com.tw/pitem/M00095741"


@pytest.mark.network
async def test_rikaxalbert_delisted_detected():
    result = await extract_price(DELISTED_URL)
    assert result.supported, f"應判定為支援（下架），實際 method={result.method}"
    assert result.availability == Availability.DELISTED
    assert result.method.startswith("adapter:rikaxalbert")
