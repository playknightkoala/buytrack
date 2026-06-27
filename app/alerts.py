"""Telegram 提醒發送（從 Celery worker 同步呼叫）。

worker 不需要持有 bot 實例，直接打 Telegram Bot API 即可。
"""
from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_API = "https://api.telegram.org/bot{token}/sendMessage"


def send_message(chat_id: int, text: str) -> None:
    if not settings.telegram_bot_token:
        logger.warning("未設定 TELEGRAM_BOT_TOKEN，略過發送：%s", text)
        return
    try:
        httpx.post(
            _API.format(token=settings.telegram_bot_token),
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10.0,
        )
    except Exception:
        logger.exception("發送 Telegram 訊息失敗 chat_id=%s", chat_id)


def notify_admins(text: str) -> None:
    for admin_id in settings.admin_id_set:
        send_message(admin_id, text)
