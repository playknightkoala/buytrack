"""目錄爬取的共用型別與 adapter 介面。

與價格 adapter（app/extraction/adapters）採同一套模式：
繼承 :class:`BaseCatalogAdapter`、設定 ``domains``、實作 ``fetch_all()``，
定義即自動註冊；``registry.py`` 掃描 adapters 套件觸發註冊。
"""
from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.extraction.context import FetchContext


@dataclasses.dataclass
class CatalogItem:
    """目錄中的單一商品（列表頁層級資料，不需進商品頁）。"""

    key: str                # 唯一鍵（商品相對網址，如 /products/xxx）
    title: str
    product_url: str        # 完整網址
    price: float | None = None
    compare_at_price: float | None = None  # 原價（有值且 > price 代表特價中）
    image_url: str | None = None
    available: bool | None = None


# domain（小寫）-> adapter 實例
CATALOG_REGISTRY: dict[str, "BaseCatalogAdapter"] = {}


class BaseCatalogAdapter:
    """目錄 adapter 基底。子類別定義時自動註冊（需設定 domains）。"""

    #: 此 adapter 負責的網域；留空則不註冊（通用 adapter 由 registry 特別處理）
    domains: list[str] = []

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if cls.domains:
            instance = cls()
            for domain in cls.domains:
                CATALOG_REGISTRY[domain.lower().lstrip(".")] = instance

    async def fetch_all(self, collection_url: str, ctx: "FetchContext") -> list[CatalogItem]:
        """抓取整個目錄（含翻頁），回傳所有商品。失敗時拋出例外。"""
        raise NotImplementedError
