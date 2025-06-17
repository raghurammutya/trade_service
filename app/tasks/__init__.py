# app/tasks/__init__.py

# Import all tasks to ensure they are registered with Celery
from .create_order_event import create_order_event_task
from .get_api_key_task import get_api_key_task
from .process_order_task import process_order_task
from .update_order_status import update_order_status_task
from .update_positions_and_holdings_task import update_positions_and_holdings_task

__all__ = [
    'create_order_event_task',
    'get_api_key_task', 
    'process_order_task',
    'update_order_status_task',
    'update_positions_and_holdings_task'
]