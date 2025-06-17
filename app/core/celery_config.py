# trade_service/app/core/celery_config.py
from celery import Celery
import os
import sys

# Add parent directory to path to import shared_architecture
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

try:
    from shared_architecture.connections.service_discovery import service_discovery, ServiceType
    USE_SERVICE_DISCOVERY = True
except ImportError:
    USE_SERVICE_DISCOVERY = False
    print("⚠️ Service discovery not available, using fallback configuration")

# Determine the correct service hosts based on environment
environment = os.getenv("ENVIRONMENT", "local").lower()

if os.getenv("TESTING") == "true" or environment == "test":
    # Use localhost for testing
    redis_host = "localhost"
    redis_broker_url = f"redis://{redis_host}:6379/0"
    redis_backend_url = f"redis://{redis_host}:6379/0"
elif environment == "production":
    # Production: Check for Redis cluster
    redis_cluster_hosts = os.getenv("REDIS_CLUSTER_HOSTS", "")
    if redis_cluster_hosts:
        # Use first cluster node for Celery broker (Celery doesn't support cluster mode directly)
        first_host = redis_cluster_hosts.split(',')[0].strip()
        redis_broker_url = f"redis://{first_host}/0"
        redis_backend_url = f"redis://{first_host}/0"
    else:
        # Use service discovery if available
        redis_host_config = os.getenv("REDIS_HOST", "redis")
        if USE_SERVICE_DISCOVERY:
            redis_host = service_discovery.resolve_service_host(redis_host_config, ServiceType.REDIS)
            print(f"✅ Celery using service discovery: Redis host resolved to {redis_host}")
        else:
            redis_host = redis_host_config
        
        redis_port = int(os.getenv("REDIS_PORT", "6379"))
        redis_broker_url = f"redis://{redis_host}:{redis_port}/0"
        redis_backend_url = f"redis://{redis_host}:{redis_port}/0"
else:
    # Development/local: Use service discovery if available
    redis_host_config = os.getenv("REDIS_HOST", "redis")
    if USE_SERVICE_DISCOVERY:
        redis_host = service_discovery.resolve_service_host(redis_host_config, ServiceType.REDIS)
        print(f"✅ Celery using service discovery: Redis host resolved to {redis_host}")
    else:
        # Fallback: use localhost for local development
        redis_host = "localhost" if environment == "local" else redis_host_config
    
    redis_port = int(os.getenv("REDIS_PORT", "6379"))
    redis_broker_url = f"redis://{redis_host}:{redis_port}/0"
    redis_backend_url = f"redis://{redis_host}:{redis_port}/0"

# Create Celery app with Redis broker
celery_app = Celery(
    "trade_service",
    broker=redis_broker_url,
    backend=redis_backend_url,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json", 
    accept_content=["json"],
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_retry_delay=5,  # seconds
    task_max_retries=3,  # default max retries for tasks
    # Add these for better reliability
    task_reject_on_worker_lost=True,
    task_ignore_result=False,
    result_expires=3600,  # Results expire after 1 hour
    timezone='UTC',
    enable_utc=True,
)

# Configure periodic tasks
from celery.schedules import crontab

celery_app.conf.beat_schedule = {
    'comprehensive-sync-all-accounts': {
        'task': 'app.tasks.comprehensive_sync_task.sync_all_accounts_comprehensive',
        'schedule': 300.0,  # Run every 5 minutes
        'options': {'queue': 'periodic'}
    },
    'midnight-connection-reset': {
        'task': 'app.tasks.connection_pool_management.midnight_connection_reset',
        'schedule': crontab(hour=0, minute=0),  # Daily at midnight UTC
        'options': {'queue': 'maintenance'}
    },
    'cleanup-stale-connections': {
        'task': 'app.tasks.connection_pool_management.cleanup_stale_connections',
        'schedule': crontab(minute=0, hour='*/4'),  # Every 4 hours
        'options': {'queue': 'maintenance'}
    },
    'connection-pool-health-check': {
        'task': 'app.tasks.connection_pool_management.get_connection_pool_health',
        'schedule': 600.0,  # Every 10 minutes
        'options': {'queue': 'monitoring'}
    },
    'daily-consistency-monitoring': {
        'task': 'app.tasks.consistency_monitoring_task.monitor_all_accounts_consistency',
        'schedule': crontab(hour=1, minute=0),  # Daily at 1 AM UTC
        'options': {'queue': 'monitoring'}
    },
    'weekly-consistency-report': {
        'task': 'app.tasks.consistency_monitoring_task.generate_consistency_report',
        'schedule': crontab(hour=2, minute=0, day_of_week=1),  # Weekly on Monday at 2 AM UTC
        'options': {'queue': 'reporting'}
    },
}

# Auto-discover tasks from the 'app.tasks' module
celery_app.autodiscover_tasks(['app.tasks'])

print(f"✅ Celery config loaded successfully")
print(f"   Redis broker URL: {redis_broker_url}")
print(f"   Redis backend URL: {redis_backend_url}")
print(f"   Environment: {environment}")
