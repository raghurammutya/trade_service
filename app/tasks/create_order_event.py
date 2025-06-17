# app/tasks/create_order_event.py

from shared_architecture.db.models.order_model import OrderModel
from shared_architecture.db.models.order_event_model import OrderEventModel
from shared_architecture.enums import OrderEvent
from app.core.celery_config import celery_app
from app.utils.celery_db_helper import get_celery_db_session
from typing import Optional

@celery_app.task
def create_order_event_task(order_id: int, event_type: str, details: Optional[str] = None):
    """
    Celery task to create an order event in the database.
    """
    db = get_celery_db_session()
    
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