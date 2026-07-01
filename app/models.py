"""資料模型（SQLAlchemy 2.0 declarative）。"""
from __future__ import annotations

import datetime as dt
import enum

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ProductStatus(str, enum.Enum):
    ACTIVE = "active"
    OUT_OF_STOCK = "out_of_stock"
    DELISTED = "delisted"
    UNSUPPORTED = "unsupported"
    ERROR = "error"


class RequestStatus(str, enum.Enum):
    PENDING = "pending"
    RESOLVED = "resolved"


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), default=None)
    first_name: Mapped[str | None] = mapped_column(String(128), default=None)
    last_name: Mapped[str | None] = mapped_column(String(128), default=None)
    is_admin: Mapped[bool] = mapped_column(default=False)
    is_whitelisted: Mapped[bool] = mapped_column(default=False)  # 動態白名單（可由管理員開通）
    last_manual_refresh_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )  # 手動 /refresh 的冷卻計時
    # 排程設定（套用到該使用者的所有商品）：interval=每 N 秒；hourly=每小時整點
    schedule_mode: Mapped[str] = mapped_column(String(16), default="interval")
    check_interval_sec: Mapped[int] = mapped_column(Integer, default=3600)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    products: Mapped[list["TrackedProduct"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class TrackedProduct(Base):
    __tablename__ = "tracked_products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(Text)
    domain: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str | None] = mapped_column(Text, default=None)
    current_price: Mapped[float | None] = mapped_column(Float, default=None)
    currency: Mapped[str | None] = mapped_column(String(8), default=None)
    status: Mapped[ProductStatus] = mapped_column(
        Enum(ProductStatus, native_enum=False, length=20),
        default=ProductStatus.ACTIVE,
        index=True,
    )
    last_checked_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, index=True
    )
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="products")
    history: Mapped[list["PriceHistory"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )


class PriceHistory(Base):
    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("tracked_products.id", ondelete="CASCADE"), index=True
    )
    price: Mapped[float | None] = mapped_column(Float, default=None)
    availability: Mapped[str] = mapped_column(String(20), default="unknown")
    checked_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    product: Mapped[TrackedProduct] = relationship(back_populates="history")


class AnnouncedVersion(Base):
    """已公告（推播）過的版本，避免重啟時重複推播。"""

    __tablename__ = "announced_versions"

    version: Mapped[str] = mapped_column(String(32), primary_key=True)
    announced_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class UnsupportedRequest(Base):
    """三層自動萃取都失敗的網站 → 管理員待辦清單。"""

    __tablename__ = "unsupported_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain: Mapped[str] = mapped_column(String(255), index=True)
    url: Mapped[str] = mapped_column(Text)
    requested_by: Mapped[int | None] = mapped_column(BigInteger, default=None)
    status: Mapped[RequestStatus] = mapped_column(
        Enum(RequestStatus, native_enum=False, length=20),
        default=RequestStatus.PENDING,
        index=True,
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    resolved_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
