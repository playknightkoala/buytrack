"""目錄快照比對：找出新品與調價（純函式，方便單元測試）。"""
from __future__ import annotations

import dataclasses

from app.catalog.base import CatalogItem


@dataclasses.dataclass
class PriceChange:
    item: CatalogItem
    old_price: float


@dataclasses.dataclass
class CatalogDiff:
    new_items: list[CatalogItem]
    price_changes: list[PriceChange]
    missing_keys: list[str]  # 這次沒出現在目錄上的既有商品（可能下架）

    @property
    def has_changes(self) -> bool:
        return bool(self.new_items or self.price_changes)


def diff_catalog(existing_prices: dict[str, float | None], items: list[CatalogItem]) -> CatalogDiff:
    """existing_prices：DB 中 key -> 上次價格；items：本次爬到的目錄。"""
    new_items: list[CatalogItem] = []
    price_changes: list[PriceChange] = []
    seen: set[str] = set()

    for item in items:
        seen.add(item.key)
        if item.key not in existing_prices:
            new_items.append(item)
            continue
        old = existing_prices[item.key]
        if item.price is not None and old is not None and item.price != old:
            price_changes.append(PriceChange(item=item, old_price=old))

    missing = [k for k in existing_prices if k not in seen]
    return CatalogDiff(new_items=new_items, price_changes=price_changes, missing_keys=missing)
