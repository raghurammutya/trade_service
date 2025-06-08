# trade_service/app/core/celery_config.py
from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "trade_service",
    broker=f"redis://{settings.redis_host}:{settings.redis_port}/0",  # Redis as broker
    backend=f"redis://{settings.redis_host}:{settings.redis_port}/0",  # Redis as backend (for results)
)

celery_app.conf.update(
    task_serializer="pickle",
    result_serializer="pickle",
    accept_content=["pickle", "json"],
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)