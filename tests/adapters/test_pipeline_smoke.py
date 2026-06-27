"""端到端煙霧測試（需網路）。

也是新增 adapter 測試時的非同步寫法範例。

用法：
  BUYTRACK_TEST_URL="<真實商品網址>" pytest tests/adapters/test_pipeline_smoke.py --run-network -q
"""
from __future__ import annotations

import os

import pytest

from app.extraction.pipeline import extract_price


@pytest.mark.network
@pytest.mark.skipif(
    not os.getenv("BUYTRACK_TEST_URL"),
    reason="設定 BUYTRACK_TEST_URL 才執行",
)
async def test_extract_price_smoke():
    url = os.environ["BUYTRACK_TEST_URL"]
    result = await extract_price(url)
    assert result.has_price, f"未取得價格：method={result.method}"
    assert result.price and result.price > 0
