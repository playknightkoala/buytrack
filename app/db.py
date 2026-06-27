"""同步 SQLAlchemy session 管理。

整個專案使用同步 SQLAlchemy：
- Celery worker / beat 本身是同步的，直接用即可。
- 非同步的 Telegram bot 透過 ``asyncio.to_thread`` 呼叫這裡的函式。
"""
from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    """提供交易邊界的 session context manager。"""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
