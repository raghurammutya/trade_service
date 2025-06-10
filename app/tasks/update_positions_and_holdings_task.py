from shared_architecture.connections.connection_manager import connection_manager
from app.models.order_model import OrderModel
from app.core.celery_config import celery_app
import asyncio

@celery_app.task
def update_positions_and_holdings_task(order_id: int):
    """
    Celery task to update positions and holdings in the database based on a filled order.
    """
    db = connection_manager.get_sync_timescaledb_session()
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
