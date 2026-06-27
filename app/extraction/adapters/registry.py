"""Adapter 自動探索與查詢。

啟動時 import ``app.extraction.adapters`` 底下所有模組，觸發 :class:`BaseAdapter`
子類別的自動註冊；再以網域（含子網域）對應到 adapter。
"""
from __future__ import annotations

import importlib
import pkgutil

from app.extraction.adapters.base import ADAPTER_REGISTRY, BaseAdapter
from app.extraction.context import domain_of

_loaded = False

# 不視為 adapter 的模組
_SKIP = {"base", "registry", "_template", "__init__"}


def load_adapters() -> None:
    global _loaded
    if _loaded:
        return
    import app.extraction.adapters as pkg

    for mod in pkgutil.iter_modules(pkg.__path__):
        if mod.name in _SKIP or mod.name.startswith("_"):
            continue
        importlib.import_module(f"{pkg.__name__}.{mod.name}")
    _loaded = True


def get_adapter(url: str) -> BaseAdapter | None:
    """以網域比對 adapter，支援子網域（host 結尾為註冊網域）。"""
    load_adapters()
    host = domain_of(url)
    if not host:
        return None
    if host in ADAPTER_REGISTRY:
        return ADAPTER_REGISTRY[host]
    for domain, adapter in ADAPTER_REGISTRY.items():
        if host == domain or host.endswith("." + domain):
            return adapter
    return None


def registered_domains() -> list[str]:
    load_adapters()
    return sorted(ADAPTER_REGISTRY.keys())
