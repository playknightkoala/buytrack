"""版本改版資訊推播。

bot 啟動時呼叫 broadcast_if_new()：若目前版本尚未公告過，
讀取 CHANGELOG.md 對應段落，推播給「已開通使用者」，並記錄到 DB 避免重複。
"""
from __future__ import annotations

import logging
import pathlib

from app.alerts import send_message
from app.config import settings
from app.db import session_scope
from app.models import AnnouncedVersion, User
from app.version import __version__

logger = logging.getLogger(__name__)

_CHANGELOG = pathlib.Path(__file__).resolve().parent.parent / "CHANGELOG.md"


def changelog_for(version: str) -> str | None:
    """取出 CHANGELOG.md 中該版本標題（## ...）底下到下一個 ## 之前的內容。"""
    try:
        text = _CHANGELOG.read_text(encoding="utf-8")
    except OSError:
        return None
    body: list[str] = []
    capturing = False
    for line in text.splitlines():
        if line.startswith("## "):
            if capturing:
                break
            capturing = version in line  # 比對如 "## [1.0.0] - ..."
            continue
        if capturing:
            body.append(line)
    notes = "\n".join(body).strip()
    return notes or None


def _recipients() -> set[int]:
    """已開通使用者 = env 管理員/白名單 ∪ DB 動態白名單。"""
    ids: set[int] = set(settings.authorized_id_set)
    with session_scope() as s:
        for (tid,) in (
            s.query(User.telegram_id).filter(User.is_whitelisted.is_(True)).all()
        ):
            ids.add(tid)
    return ids


def broadcast_if_new() -> None:
    version = __version__
    with session_scope() as s:
        if s.get(AnnouncedVersion, version) is not None:
            logger.info("版本 v%s 已公告過，略過推播。", version)
            return

    notes = changelog_for(version) or "（無詳細改版說明）"
    message = f"🆕 已更新到 v{version}\n\n{notes}"

    recipients = _recipients()
    for uid in recipients:
        send_message(uid, message)  # send_message 內已自行處理錯誤

    with session_scope() as s:
        if s.get(AnnouncedVersion, version) is None:
            s.add(AnnouncedVersion(version=version))
    logger.info("版本 v%s 已推播給 %d 位已開通使用者。", version, len(recipients))
