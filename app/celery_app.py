"""Celery 應用程式與排程設定。"""
from __future__ import annotations

from celery import Celery

from app.config import settings

celery_app = Celery(
    "buytrack",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Taipei",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "enqueue-due-checks": {
            "task": "app.tasks.enqueue_due_checks",
            "schedule": float(settings.enqueue_period_sec),
        },
    },
)
