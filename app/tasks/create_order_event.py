# app/tasks/create_order_event.py

from celery import Celery
from shared_architecture.connections.connection_manager import connection_manager
from shared_architecture.db.models import OrderModel, OrderEventModel
from shared_architecture.enums import OrderEvent  # Ensure OrderEvent enum is imported correctly
from app.core.celery_config import celery_app
from typing import Optional

@celery_app.task
def create_order_event_task(order_id: int, event_type: str, details: Optional[str] = None):

    """
    Celery task to create an order event in the database.
    """
    db = connection_manager.get_sync_timescaledb_session()
    try:
        order = db.query(OrderModel).filter_by(id=order_id).first()
        if order:
            event = OrderEventModel(
                order_id=order.id,
                event_type=OrderEvent(event_type),
                details=details
            )
            db.add(event)
            db.commit()
        else:
            print(f"[OrderEventTask] Order with ID {order_id} not found for event type {event_type}")
    except Exception as e:
        print(f"[OrderEventTask] Error creating event for Order {order_id}: {e}")
        db.rollback()
    finally:
        db.close()
