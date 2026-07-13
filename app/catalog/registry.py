"""目錄 adapter 探索：專屬網域優先，/collections/ 網址 fallback 到通用 products.json。"""
from __future__ import annotations

import importlib
import pkgutil

from app.catalog.adapters.products_json import (
    ProductsJsonCatalogAdapter,
    parse_collection,
)
from app.catalog.base import CATALOG_REGISTRY, BaseCatalogAdapter
from app.extraction.context import domain_of

_loaded = False
_SKIP = {"products_json", "__init__"}
_generic = ProductsJsonCatalogAdapter()


def load_adapters() -> None:
    global _loaded
    if _loaded:
        return
    import app.catalog.adapters as pkg

    for mod in pkgutil.iter_modules(pkg.__path__):
        if mod.name in _SKIP or mod.name.startswith("_"):
            continue
        importlib.import_module(f"{pkg.__name__}.{mod.name}")
    _loaded = True


def get_catalog_adapter(url: str) -> BaseCatalogAdapter | None:
    """網域專屬 adapter 優先；否則 /collections/ 網址用通用 products.json。"""
    load_adapters()
    host = domain_of(url)
    if host:
        if host in CATALOG_REGISTRY:
            return CATALOG_REGISTRY[host]
        for domain, adapter in CATALOG_REGISTRY.items():
            if host == domain or host.endswith("." + domain):
                return adapter
    if parse_collection(url) is not None:
        return _generic
    return None
