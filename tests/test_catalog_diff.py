"""目錄 diff 純函式單元測試（不需網路）。"""
from __future__ import annotations

from app.catalog.base import CatalogItem
from app.catalog.differ import diff_catalog


def _item(key: str, price: float | None) -> CatalogItem:
    return CatalogItem(key=key, title=f"item{key}", product_url=f"https://x.com{key}", price=price)


def test_first_crawl_all_new():
    diff = diff_catalog({}, [_item("/p/1", 100), _item("/p/2", 200)])
    assert len(diff.new_items) == 2
    assert not diff.price_changes and not diff.missing_keys


def test_price_change_detected():
    existing = {"/p/1": 100.0, "/p/2": 200.0}
    diff = diff_catalog(existing, [_item("/p/1", 90), _item("/p/2", 200)])
    assert not diff.new_items
    assert len(diff.price_changes) == 1
    assert diff.price_changes[0].item.key == "/p/1"
    assert diff.price_changes[0].old_price == 100.0


def test_new_and_missing():
    existing = {"/p/1": 100.0}
    diff = diff_catalog(existing, [_item("/p/2", 300)])
    assert [i.key for i in diff.new_items] == ["/p/2"]
    assert diff.missing_keys == ["/p/1"]


def test_none_prices_do_not_trigger_change():
    existing = {"/p/1": None, "/p/2": 200.0}
    diff = diff_catalog(existing, [_item("/p/1", 100), _item("/p/2", None)])
    assert not diff.price_changes  # 任一邊無價格 → 不視為調價
