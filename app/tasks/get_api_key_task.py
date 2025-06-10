# app/tasks/get_api_key_task.py
from app.core.celery_config import celery_app
from shared_architecture.connections.connection_manager import connection_manager
from app.core.config import settings
import requests
import asyncio

@celery_app.task
def get_api_key_task(organization_id: str):
    """
    Celery task to retrieve the API key for a given organization, with caching.
    This task is designed to be called by other Celery tasks.
    """

    async def _get_or_fetch_key():
        redis_conn = connection_manager.get_redis_connection()
        cached_key = await redis_conn.get(f"api_key:{organization_id}")
        if cached_key:
            return cached_key  # decode_responses=True so it's already str

        user_service_url = settings.user_service_url
        try:
            response = requests.get(f"{user_service_url}/api_key/{organization_id}")
            response.raise_for_status()
            api_key = response.json()["api_key"]
            await redis_conn.set(f"api_key:{organization_id}", api_key, ex=3600)
            return api_key
        except Exception as e:
            print(f"Error getting API key for organization {organization_id}: {e}")
            raise e

    return asyncio.run(_get_or_fetch_key())
