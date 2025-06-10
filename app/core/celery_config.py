# trade_service/app/core/celery_config.py
from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "trade_service",
    broker=f"redis://{settings.redis_url.split('redis://')[1].split('/')[0]}/{settings.redis_url.split('/')[-1]}",  # Correctly parse host/port/db from REDIS_URL
    backend=f"redis://{settings.redis_url.split('redis://')[1].split('/')[0]}/{settings.redis_url.split('/')[-1]}", # Correctly parse host/port/db from REDIS_URL
)

celery_app.conf.update(
    task_serializer="pickle",
    result_serializer="pickle",
    accept_content=["pickle", "json"],
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # New: Set a default retry delay for tasks if not specified per task
    task_default_retry_delay=5, # seconds
    task_max_retries=3, # default max retries for tasks
)

# New: Auto-discover tasks from the 'app.tasks' module
celery_app.autodiscover_tasks(['app.tasks'], related_name='trade_tasks')