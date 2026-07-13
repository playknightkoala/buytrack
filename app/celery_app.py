"""Celery 應用程式與排程設定。"""
from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery_app = Celery(
    "buytrack",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks", "app.catalog.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Taipei",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # 目錄爬取走獨立 queue（catalog-worker 消化），避免長時間爬取卡住單品檢查
    task_routes={
        "app.catalog.tasks.*": {"queue": "catalog"},
    },
    beat_schedule={
        "enqueue-due-checks": {
            "task": "app.tasks.enqueue_due_checks",
            "schedule": float(settings.enqueue_period_sec),
        },
        # 每日 08:00（台北）爬所有訂閱目錄
        "catalog-daily-crawl": {
            "task": "app.catalog.tasks.enqueue_catalog_crawls",
            "schedule": crontab(hour=8, minute=0),
        },
    },
)
