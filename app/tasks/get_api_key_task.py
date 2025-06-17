# app/tasks/get_api_key_task.py
from app.core.celery_config import celery_app
from shared_architecture.connections.connection_manager import connection_manager
from app.core.config import settings
import requests
import asyncio

@celery_app.task
def get_api_key_task(organization_id: str):
    """
    Celery task to retrieve the API key for a given organization.
    Simplified to avoid async/sync mixing issues.
    """
    try:
        # For now, just return the API key from settings
        # TODO: Add Redis caching when Redis sync client is available
        from app.core.config import settings
        api_key = settings.stocksdeveloper_api_key
        if not api_key:
            raise ValueError("StocksDeveloper API key not found in settings")
        return api_key
    except Exception as e:
        print(f"Error getting API key for organization {organization_id}: {e}")
        raise e
