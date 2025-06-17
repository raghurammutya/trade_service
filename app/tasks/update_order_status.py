from celery import shared_task
from shared_architecture.db.models.order_model import OrderModel
from shared_architecture.enums import OrderEvent
from app.core.celery_config import celery_app
from app.utils.celery_db_helper import get_celery_db_session

@shared_task(name="update_order_status_task")
def update_order_status_task(order_id: int, order_status: dict):
    """
    Celery task to update the order status in the database and trigger position/holding updates.
    """
    db = get_celery_db_session()

    try:
        event_args = [] 
        order = db.query(OrderModel).filter_by(id=order_id).first()
        if order:
            old_status = order.status
            order.status = order_status.get("status", "UNKNOWN")  # type: ignore
            order.average_price = order_status.get("average_price")  # type: ignore
            order.filled_quantity = order_status.get("filled_quantity")  # type: ignore
            order.status_message = order_status.get("message", order_status.get("status_message"))  # type: ignore
            order.exchange_order_id = order_status.get("order_id", order_status.get("exchange_order_id"))  # type: ignore

            db.commit()

            if order.status != old_status:
                if order.status == "COMPLETE":
                    event_args = [order.id, OrderEvent.ORDER_FILLED.value]
                elif order.status == "PARTIALLY_FILLED":
                    event_args = [order.id, OrderEvent.ORDER_PARTIALLY_FILLED.value]
                elif order.status == "CANCELLED":
                    event_args = [order.id, OrderEvent.ORDER_CANCELLED.value]
                elif order.status == "REJECTED":
                    event_args = [order.id, OrderEvent.ORDER_REJECTED.value, order.status_message or "Unknown rejection"]
                elif order.status == "MODIFIED":
                    event_args = [order.id, OrderEvent.ORDER_MODIFIED.value]
                elif order.status == "NEW":
                    event_args = [order.id, OrderEvent.ORDER_PLACED.value]
                elif order.status == "PENDING":
                    event_args = [order.id, OrderEvent.ORDER_ACCEPTED.value]
                else:
                    event_args = [order.id, f"ORDER_STATUS_CHANGED_TO_{order.status}"]
                
                # Use celery_app.send_task instead of importing and calling .delay()
                celery_app.send_task('create_order_event_task', args=event_args)

            if order.status in ["COMPLETE", "PARTIALLY_FILLED"]:
                # Use celery_app.send_task instead of importing and calling .delay()
                celery_app.send_task('update_positions_and_holdings_task', args=[order.id])
        else:
            print(f"⚠️ Order with ID {order_id} not found in DB for status update.")
    except Exception as e:
        print(f"❌ Error updating order status for Order {order_id}: {e}")
        db.rollback()
    finally:
        db.close()