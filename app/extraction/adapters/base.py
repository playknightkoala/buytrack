"""Adapter 介面與共用型別 —— 管理員新增網站爬蟲的標準擴充點。

新增一個網站支援只要：
1. 在 ``app/extraction/adapters/`` 下新增一個模組。
2. 定義一個繼承 :class:`BaseAdapter` 的類別，設定 ``domains`` 並實作 ``extract()``。

類別一旦被定義（模組被 import）就會自動註冊到 :data:`ADAPTER_REGISTRY`，
``registry.py`` 會在啟動時 import 整個 adapters 套件來觸發註冊。
"""
from __future__ import annotations

import dataclasses
import enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 避免 runtime 循環 import
    from app.extraction.context import FetchContext


class Availability(str, enum.Enum):
    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"
    DELISTED = "delisted"  # 商品頁不存在（404/410），已下架/停售
    UNKNOWN = "unknown"


@dataclasses.dataclass
class ExtractionResult:
    """萃取結果。``supported=False`` 代表所有層都拿不到價格。"""

    supported: bool
    price: float | None = None
    currency: str | None = None
    title: str | None = None
    availability: Availability = Availability.UNKNOWN
    method: str = ""  # 哪一層產生的（adapter:<name> / structured:json-ld / rendered:og ...）
    raw: dict = dataclasses.field(default_factory=dict)

    @classmethod
    def unsupported(cls, method: str = "none") -> "ExtractionResult":
        return cls(supported=False, method=method)

    @property
    def has_price(self) -> bool:
        return self.supported and self.price is not None


# domain（小寫）-> adapter 實例
ADAPTER_REGISTRY: dict[str, "BaseAdapter"] = {}


class BaseAdapter:
    """所有專屬 adapter 的基底類別。

    子類別被定義時自動註冊（前提是有設定 ``domains``）。
    """

    #: 此 adapter 負責的網域，例如 ["shopee.tw", "shopee.com"]
    domains: list[str] = []

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if cls.domains:
            instance = cls()
            for domain in cls.domains:
                ADAPTER_REGISTRY[domain.lower().lstrip(".")] = instance

    async def extract(self, url: str, ctx: "FetchContext") -> ExtractionResult:
        raise NotImplementedError
