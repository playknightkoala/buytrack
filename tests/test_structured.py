"""通用結構化資料解析器的單元測試（不需網路）。"""
from __future__ import annotations

from app.extraction.adapters.base import Availability
from app.extraction.structured import parse_structured

JSONLD_HTML = """
<html><head>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "測試商品 A",
  "offers": {
    "@type": "Offer",
    "price": "1,299.00",
    "priceCurrency": "TWD",
    "availability": "https://schema.org/InStock"
  }
}
</script>
</head><body></body></html>
"""

OG_HTML = """
<html><head>
<meta property="og:title" content="OG 商品 B" />
<meta property="product:price:amount" content="599" />
<meta property="product:price:currency" content="TWD" />
<meta property="product:availability" content="instock" />
</head><body></body></html>
"""

EMPTY_HTML = "<html><head></head><body><p>no price here</p></body></html>"


def test_jsonld_product():
    r = parse_structured(JSONLD_HTML, "https://example.com/p/1")
    assert r.has_price
    assert r.price == 1299.0
    assert r.currency == "TWD"
    assert r.title == "測試商品 A"
    assert r.availability == Availability.IN_STOCK
    assert r.method.endswith("json-ld")


def test_opengraph_fallback():
    r = parse_structured(OG_HTML, "https://example.com/p/2")
    assert r.has_price
    assert r.price == 599.0
    assert r.currency == "TWD"
    assert r.title == "OG 商品 B"
    assert r.availability == Availability.IN_STOCK


def test_no_structured_data_unsupported():
    r = parse_structured(EMPTY_HTML, "https://example.com/p/3")
    assert not r.supported
    assert r.price is None
