"""Celery application configuration."""

from celery import Celery

from app.config import settings

celery_app = Celery(
    "agent_hub",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasks.webhook_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,  # 5 minutes max per task
    task_soft_time_limit=270,  # Soft limit for graceful shutdown
    worker_prefetch_multiplier=1,  # Don't prefetch, process one at a time
    task_acks_late=True,  # Acknowledge after completion for reliability
)
