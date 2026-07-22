"""Celery 任務：定時排程 + 單一商品檢查 + 價格 diff / 提醒 / 不支援流程。"""
from __future__ import annotations

import asyncio
import datetime as dt
import html
import logging

from sqlalchemy import and_, func, or_, select

from app.alerts import notify_admins, send_message
from app.celery_app import celery_app
from app.config import settings
from app.db import session_scope
from app.extraction.adapters.base import Availability
from app.extraction.pipeline import extract_price
from app.sites import site_label
from app.models import (
    PriceHistory,
    ProductStatus,
    RequestStatus,
    TrackedProduct,
    UnsupportedRequest,
)

logger = logging.getLogger(__name__)


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


@celery_app.task(name="app.tasks.enqueue_due_checks")
def enqueue_due_checks() -> int:
    """掃描到期的 active 商品，逐一排入 check_product。回傳排入數量。"""
    # 到期條件（依排程模式）：
    #  - 從未檢查過
    #  - interval：距上次檢查超過該商品的間隔秒數
    #  - hourly：進入了新的整點（now 的小時 > 上次檢查的小時；UTC 整點=台北整點）
    # 排程設定在每個商品上
    due = or_(
        TrackedProduct.last_checked_at.is_(None),
        and_(
            TrackedProduct.schedule_mode == "interval",
            func.extract("epoch", func.now() - TrackedProduct.last_checked_at)
            >= TrackedProduct.check_interval_sec,
        ),
        and_(
            TrackedProduct.schedule_mode == "hourly",
            func.date_trunc("hour", func.now())
            > func.date_trunc("hour", TrackedProduct.last_checked_at),
        ),
    )
    with session_scope() as session:
        rows = session.execute(
            select(TrackedProduct.id).where(
                TrackedProduct.status == ProductStatus.ACTIVE, due
            )
        ).all()
        ids = [r[0] for r in rows]
    for product_id in ids:
        check_product.delay(product_id)
    logger.info("排入 %d 個商品檢查", len(ids))
    return len(ids)


def _money(value: float | None, currency: str | None) -> str:
    if value is None:
        return "—"
    cur = currency or ""
    return f"{value:,.0f} {cur}".strip()


def _h(text: str | None) -> str:
    """HTML 跳脫（用於 parse_mode=HTML 的訊息）。"""
    return html.escape(text or "")


@celery_app.task(name="app.tasks.check_product")
def check_product(product_id: int) -> None:
    # 1) 讀取必要欄位（不在抓取期間持有交易）
    with session_scope() as session:
        product = session.get(TrackedProduct, product_id)
        if product is None:
            return
        url = product.url
        domain = product.domain
        chat_id = product.user.telegram_id
        old_price = product.current_price
        old_status = product.status

    # 2) 跑萃取（網路慢，放在交易外）
    try:
        result = asyncio.run(extract_price(url))
        extraction_error = None
    except Exception as exc:  # noqa: BLE001
        result = None
        extraction_error = exc
        logger.exception("萃取例外 product_id=%s", product_id)

    # 3) 依結果更新並發送提醒
    with session_scope() as session:
        product = session.get(TrackedProduct, product_id)
        if product is None:
            return
        product.last_checked_at = _utcnow()

        # 3a) 抓取本身出錯（網路/逾時例外）→ 累計失敗、達門檻則暫停並提醒
        if extraction_error is not None:
            product.consecutive_failures += 1
            if product.consecutive_failures >= settings.max_consecutive_failures:
                product.status = ProductStatus.ERROR
                send_message(
                    chat_id,
                    f"⚠️ 「{_h(product.title or url)}」連續抓取失敗（網路或網站異常），"
                    "已暫停追蹤。可用 /interval 重新啟用。",
                )
            return

        assert result is not None

        # 3b) 三層都拿不到價格
        if not result.supported:
            if old_price is None:
                # 全新、從未成功取得價格 → 此網站尚未支援，請管理員新增
                product.status = ProductStatus.UNSUPPORTED
                _record_unsupported(session, domain, url, chat_id)
                send_message(
                    chat_id,
                    "🛈 此網站目前不支援自動追蹤價格，已通知管理員新增支援：\n"
                    f"{_h(url)}",
                )
                notify_admins(f"🆕 待新增爬蟲網域：<b>{_h(domain)}</b>\n{_h(url)}")
            else:
                # 曾經成功、現在抓不到 → 爬蟲失效；容忍數次（避免一次性誤判）後判定
                product.consecutive_failures += 1
                if product.consecutive_failures >= settings.max_consecutive_failures:
                    product.status = ProductStatus.UNSUPPORTED
                    _record_unsupported(session, domain, url, chat_id)
                    send_message(
                        chat_id,
                        f"⚠️ 「{_h(product.title or url)}」的價格抓取已失效"
                        "（網站可能改版或被擋），已暫停追蹤，並已通知管理員修復。",
                    )
                    notify_admins(
                        f"⚠️ 既有商品抓取失效（疑似網站改版 / adapter 失效）："
                        f"<b>{_h(domain)}</b>\n{_h(url)}"
                    )
            return

        # 成功取得結果（含缺貨/下架）→ 歸零連續失敗計數
        product.consecutive_failures = 0

        # 3c-0) 下架/停售（商品頁 404/410）：通知一次並停止追蹤
        if result.availability == Availability.DELISTED:
            if old_status != ProductStatus.DELISTED:
                _add_history(session, product_id, None, result.availability)
                product.status = ProductStatus.DELISTED
                send_message(
                    chat_id,
                    f"🚫 「{_h(product.title or url)}」已下架或停售，已停止追蹤。\n{_h(url)}",
                )
            return

        # 3c) 缺貨（只在「轉為缺貨」的當下記錄一筆，避免每次檢查重複記）
        if result.availability == Availability.OUT_OF_STOCK:
            if old_status != ProductStatus.OUT_OF_STOCK:
                _add_history(session, product_id, result.price, result.availability)
                product.status = ProductStatus.OUT_OF_STOCK
                send_message(chat_id, f"⚠️ 商品目前缺貨：\n{_h(product.title or url)}")
            return

        # 3d) 正常：記錄、比較、提醒
        product.status = ProductStatus.ACTIVE
        if result.title:
            product.title = result.title
        if result.currency:
            product.currency = result.currency
        new_price = result.price
        # 只在「首次取得價格」「價格變動」或「從缺貨/錯誤等狀態恢復」時記錄一筆
        if old_price is None or new_price != old_price or old_status != ProductStatus.ACTIVE:
            _add_history(session, product_id, new_price, result.availability)

        site = _h(site_label(domain))
        if old_price is None:
            # 首次取得價格
            product.current_price = new_price
            send_message(
                chat_id,
                f"✅ 已開始追蹤（{site}）：\n<b>{_h(product.title or url)}</b>\n"
                f"目前價格：{_money(new_price, product.currency)}",
            )
        elif new_price is not None and new_price != old_price:
            arrow = "🔻 降價" if new_price < old_price else "🔺 漲價"
            product.current_price = new_price
            send_message(
                chat_id,
                f"{arrow}（{site}）\n<b>{_h(product.title or url)}</b>\n"
                f"{_money(old_price, product.currency)} → "
                f"<b>{_money(new_price, product.currency)}</b>\n{_h(url)}",
            )


def _add_history(session, product_id: int, price: float | None, availability) -> None:
    session.add(
        PriceHistory(
            product_id=product_id,
            price=price,
            availability=str(getattr(availability, "value", availability)),
        )
    )


def _record_unsupported(session, domain: str, url: str, chat_id: int | None) -> None:
    existing = session.execute(
        select(UnsupportedRequest.id).where(
            UnsupportedRequest.domain == domain,
            UnsupportedRequest.status == RequestStatus.PENDING,
        )
    ).first()
    if existing:
        return
    session.add(
        UnsupportedRequest(domain=domain, url=url, requested_by=chat_id)
    )
