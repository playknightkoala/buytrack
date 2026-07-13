"""目錄爬取任務（走獨立的 catalog queue，不與單品檢查搶 worker）。

- ``enqueue_catalog_crawls``：每日排程掃描所有 active 訂閱，逐一排入爬取。
- ``crawl_collection``：爬整個目錄 → diff → 更新快照 → 產 PDF 並通知訂閱者。
"""
from __future__ import annotations

import asyncio
import datetime as dt
import html as _html
import logging

from app.alerts import notify_admins, send_document, send_message
from app.catalog.base import CatalogItem
from app.catalog.differ import CatalogDiff, diff_catalog
from app.catalog.registry import get_catalog_adapter
from app.catalog.report import render_report
from app.celery_app import celery_app
from app.config import settings
from app.db import session_scope
from app.extraction.context import build_context
from app.models import CatalogChange, CatalogProduct, WatchedCollection

logger = logging.getLogger(__name__)

_MAX_FAILURES = 3  # 目錄爬取連續失敗達此數 → 標記 error 並通知


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


@celery_app.task(name="app.catalog.tasks.enqueue_catalog_crawls")
def enqueue_catalog_crawls() -> int:
    with session_scope() as s:
        ids = [
            w.id
            for w in s.query(WatchedCollection)
            .filter(WatchedCollection.status == "active")
            .all()
        ]
    for wid in ids:
        crawl_collection.delay(wid)
    logger.info("排入 %d 個目錄爬取", len(ids))
    return len(ids)


async def _fetch_items(url: str) -> list[CatalogItem]:
    adapter = get_catalog_adapter(url)
    if adapter is None:
        raise ValueError(f"沒有適用的目錄 adapter：{url}")
    async with build_context() as ctx:
        return await adapter.fetch_all(url, ctx)


@celery_app.task(name="app.catalog.tasks.crawl_collection")
def crawl_collection(watch_id: int) -> None:
    # 1) 讀取訂閱
    with session_scope() as s:
        watch = s.get(WatchedCollection, watch_id)
        if watch is None or watch.status not in ("active",):
            return
        url, label, domain = watch.url, watch.label or watch.domain, watch.domain
        chat_id = watch.user.telegram_id

    # 2) 爬目錄（網路操作在交易外）
    try:
        items = asyncio.run(_fetch_items(url))
    except Exception:
        logger.exception("目錄爬取失敗 watch_id=%s", watch_id)
        _record_failure(watch_id, chat_id, label)
        return

    if not items:
        # 空目錄視為異常（避免站方改版導致誤判全部下架）
        logger.warning("目錄回傳 0 筆，視為失敗 watch_id=%s", watch_id)
        _record_failure(watch_id, chat_id, label)
        return

    # 3) diff + 更新快照
    with session_scope() as s:
        watch = s.get(WatchedCollection, watch_id)
        if watch is None:
            return
        existing = {p.key: p for p in watch.products}
        baseline = not existing
        diff = diff_catalog({k: p.price for k, p in existing.items()}, items)

        now = _utcnow()
        for item in items:
            row = existing.get(item.key)
            if row is None:
                s.add(
                    CatalogProduct(
                        collection_id=watch_id,
                        key=item.key,
                        title=item.title,
                        price=item.price,
                        compare_at_price=item.compare_at_price,
                        image_url=item.image_url,
                        product_url=item.product_url,
                        available=item.available,
                        is_active=True,
                    )
                )
            else:
                row.title = item.title
                row.price = item.price
                row.compare_at_price = item.compare_at_price
                row.image_url = item.image_url
                row.product_url = item.product_url
                row.available = item.available
                row.is_active = True
                row.last_seen_at = now
        for key in diff.missing_keys:
            existing[key].is_active = False

        if not baseline:
            for it in diff.new_items:
                s.add(CatalogChange(collection_id=watch_id, key=it.key,
                                    change_type="new", title=it.title, new_price=it.price))
            for ch in diff.price_changes:
                s.add(CatalogChange(collection_id=watch_id, key=ch.item.key,
                                    change_type="price", title=ch.item.title,
                                    old_price=ch.old_price, new_price=ch.item.price))

        watch.consecutive_failures = 0
        watch.last_crawled_at = now

    # 4) 通知：首次=基準報告；之後只在有變化時發
    if baseline:
        _send_report(chat_id, label, domain, diff, items, baseline=True)
    elif diff.has_changes:
        _send_report(chat_id, label, domain, diff, items, baseline=False)
    else:
        logger.info("目錄無變化 watch_id=%s（%d 件）", watch_id, len(items))


def _send_report(
    chat_id: int,
    label: str,
    domain: str,
    diff: CatalogDiff,
    items: list[CatalogItem],
    baseline: bool,
) -> None:
    try:
        pdf = asyncio.run(render_report(label, domain, diff, items, baseline=baseline))
    except Exception:
        logger.exception("PDF 產出失敗（改發文字摘要） label=%s", label)
        send_message(chat_id, _caption(label, diff, items, baseline) + "\n（報告產出失敗，已記錄）")
        return
    filename = f"catalog_{domain}_{dt.datetime.now(dt.timezone.utc):%Y%m%d}.pdf"
    send_document(chat_id, pdf, filename, caption=_caption(label, diff, items, baseline))


def _caption(label: str, diff: CatalogDiff, items: list[CatalogItem], baseline: bool) -> str:
    name = _html.escape(label)
    if baseline:
        return f"📦 已開始追蹤目錄「<b>{name}</b>」，目前共 {len(items)} 件商品。詳見附件報告。"
    return (
        f"📦 目錄「<b>{name}</b>」有更新：🆕 新增 {len(diff.new_items)} 件、"
        f"💰 調價 {len(diff.price_changes)} 件（共 {len(items)} 件）。詳見附件報告。"
    )


def _record_failure(watch_id: int, chat_id: int, label: str) -> None:
    with session_scope() as s:
        watch = s.get(WatchedCollection, watch_id)
        if watch is None:
            return
        watch.consecutive_failures += 1
        watch.last_crawled_at = _utcnow()
        if watch.consecutive_failures >= _MAX_FAILURES:
            watch.status = "error"
            send_message(
                chat_id,
                f"⚠️ 目錄「{_html.escape(label)}」連續 {watch.consecutive_failures} 次爬取失敗，"
                "已暫停追蹤並通知管理員。",
            )
            notify_admins(f"⚠️ 目錄爬取失效：<b>{_html.escape(label)}</b>\n{_html.escape(watch.url)}")
