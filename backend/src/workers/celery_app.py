"""
Celery application factory.
Substitui o processamento síncrono (asyncio.create_task) por fila de tasks distribuída.
"""
from celery import Celery
from ..core.config import get_settings

settings = get_settings()


def create_celery() -> Celery:
    """Cria e configura a instância do Celery."""
    broker = settings.celery_broker_url or settings.redis_url
    backend = settings.celery_result_backend or settings.redis_url

    app = Celery(
        "odontoquiz",
        broker=broker,
        backend=backend,
        include=["backend.src.workers.tasks", "backend.src.workers.decisao_tasks"],
    )

    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_track_started=True,
        task_acks_late=True,  # Re-deliver on worker crash
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,  # One task at a time (OCR-heavy)
        worker_max_tasks_per_child=50,  # Prevent memory leaks
        task_soft_time_limit=settings.ocr_timeout_seconds,
        task_time_limit=settings.ocr_timeout_seconds + 60,
        result_expires=3600,  # 1 hour
    )

    return app


celery_app = create_celery()
