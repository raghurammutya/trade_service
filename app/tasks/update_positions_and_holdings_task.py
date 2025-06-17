from shared_architecture.db.models.order_model import OrderModel
from app.core.celery_config import celery_app
from app.utils.celery_db_helper import get_celery_db_session
import asyncio

@celery_app.task
def update_positions_and_holdings_task(order_id: int):
    """
    Celery task to update positions and holdings in the database based on a filled order.
    """
    db = get_celery_db_session()
    
    try:
        order = db.query(OrderModel).filter_by(id=order_id).first()
        if order:
            from app.services.trade_service import TradeService as LocalTradeService
            trade_service_instance = LocalTradeService(db)
            asyncio.run(trade_service_instance._update_positions_and_holdings(order))
            db.commit()
        else:
            print(f"Order with ID {order_id} not found for position/holding update.")
    except Exception as e:
        print(f"Error updating positions and holdings for Order {order_id}: {e}")
        db.rollback()
    finally:
        db.close()