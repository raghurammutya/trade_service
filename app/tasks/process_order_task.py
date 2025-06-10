import json
import time
from celery import Celery
from shared_architecture.connections.connection_manager import connection_manager
from shared_architecture.db.models.order_model import OrderModel
from shared_architecture.enums import OrderEvent
from app.core.config import settings
from app.tasks.get_api_key_task import get_api_key_task
from app.tasks.update_order_status import update_order_status_task
from app.tasks.create_order_event import create_order_event_task
from com.dakshata.autotrader.api.AutoTrader import AutoTrader
from shared_architecture.utils.rabbitmq_helper import publish_message
from datetime import datetime
celery_app = Celery("trade_service")
from typing import cast

@celery_app.task(bind=True, max_retries=3, default_retry_delay=5)
def process_order_task(self, order_dict: dict, organization_id: str):
    """
    Celery task to asynchronously process an order (place, cancel, modify, square off).
    Interacts with StocksDeveloper API.
    """
    db = connection_manager.get_sync_timescaledb_session()
    redis_conn = connection_manager.get_redis_connection()

    try:
        order = db.query(OrderModel).filter_by(id=order_dict['id']).first()
        if not order:
            raise ValueError(f"Order with ID {order_dict['id']} not found in DB for processing.")

        api_key = get_api_key_task(organization_id)
        stocksdeveloper_conn = AutoTrader.create_instance(api_key, AutoTrader.SERVER_URL)

        order_status_result = {}

        if settings.mock_order_execution:
            time.sleep(0.1)
            order_status_result = {
                "status": "COMPLETE",
                "average_price": order.price or 0.0,
                "filled_quantity": order.quantity or 0,
                "order_id": str(order.id),
                "exchange_order_id": "MOCK_" + str(order.id),
                "message": "Mock order executed successfully"
            }
        else:
            response = None
            variety = str(order.variety)

            if variety == "REGULAR":
                response = stocksdeveloper_conn.place_regular_order(
                    pseudo_account=order.pseudo_account, exchange=order.exchange, symbol=order.symbol,
                    tradeType=order.trade_type, orderType=order.order_type, productType=order.product_type,
                    quantity=order.quantity, price=order.price, triggerPrice=order.trigger_price
                )
            elif variety == "CO":
                response = stocksdeveloper_conn.place_cover_order(
                    pseudo_account=order.pseudo_account, exchange=order.exchange, symbol=order.symbol,
                    tradeType=order.trade_type, orderType=order.order_type, quantity=order.quantity,
                    price=order.price, triggerPrice=order.trigger_price
                )
            elif variety == "BO":
                response = stocksdeveloper_conn.place_bracket_order(
                    pseudo_account=order.pseudo_account, exchange=order.exchange, symbol=order.symbol,
                    tradeType=order.trade_type, orderType=order.order_type, quantity=order.quantity,
                    price=order.price, triggerPrice=order.trigger_price, target=order.target,
                    stoploss=order.stoploss, trailingStoploss=order.trailing_stoploss
                )
            elif variety == "AMO":
                response = stocksdeveloper_conn.place_advanced_order(
                    variety=order.variety, pseudo_account=order.pseudo_account, exchange=order.exchange,
                    symbol=order.symbol, tradeType=order.trade_type, orderType=order.order_type,
                    productType=order.product_type, quantity=order.quantity, price=order.price,
                    triggerPrice=order.trigger_price, target=order.target, stoploss=order.stoploss,
                    trailingStoploss=order.trailing_stoploss, disclosedQuantity=order.disclosed_quantity,
                    validity=order.validity, amo=order.amo, strategyId=order.strategy_id,
                    comments=order.comments, publisherId=order.publisher_id
                )
            elif variety == "CANCEL":
                response = stocksdeveloper_conn.cancel_order_by_platform_id(
                    pseudo_account=order.pseudo_account, platform_id=order.platform
                )
            elif variety == "CANCEL_CHILD":
                response = stocksdeveloper_conn.cancel_child_orders_by_platform_id(
                    pseudo_account=order.pseudo_account, platform_id=order.platform
                )
            elif variety == "MODIFY":
                response = stocksdeveloper_conn.modify_order_by_platform_id(
                    pseudo_account=order.pseudo_account, platform_id=order.platform,
                    order_type=order.order_type, quantity=order.quantity,
                    price=order.price, trigger_price=order.trigger_price
                )
            elif variety == "SQUARE_OFF_POSITION":
                response = stocksdeveloper_conn.square_off_position(
                    pseudo_account=order.pseudo_account, position_category=order.position_category,
                    position_type=order.position_type, exchange=order.exchange, symbol=order.symbol
                )
            elif variety == "SQUARE_OFF_PORTFOLIO":
                response = stocksdeveloper_conn.square_off_portfolio(
                    pseudo_account=order.pseudo_account, position_category=order.position_category
                )
            elif variety == "CANCEL_ALL_ORDERS":
                response = stocksdeveloper_conn.cancel_all_orders(
                    pseudo_account=order.pseudo_account
                )
            else:
                raise ValueError(f"Unsupported order variety for API call: {order.variety}")

            if response and response.success():
                order_status_result = response.result
                if 'order_id' not in order_status_result and variety in ["REGULAR", "CO", "BO", "AMO"]:
                    order_status_result['order_id'] = str(order.id)
                if 'status' not in order_status_result:
                    order_status_result['status'] = "UNKNOWN"
            else:
                raise Exception(response.message if response else "StocksDeveloper API call failed with no response object.")

            rabbitmq_url = settings.RABBITMQ_URL  # Construct or pull full AMQP URL from config
            queue_name = "order_status_events"
            payload = {
                "order_id": order.id,
                "status": order.status,
                "timestamp": datetime.utcnow().isoformat()
            }
            publish_message(rabbitmq_url, queue_name, payload)

                # Cast to int to help Pylance recognize it's not Column[int]
        update_order_status_task(cast(int, order.id), order_status_result)

    except Exception as exc:
        print(f"Celery Task {self.request.id} failed for Order {order_dict.get('id')}: {exc}")
        order_from_db = db.query(OrderModel).filter_by(id=order_dict['id']).first()
        if order_from_db:
            order_from_db.status = "REJECTED"  # type: ignore[attr-defined]
            order_from_db.status_message = str(exc)  # type: ignore[attr-defined]
            db.commit()
            create_order_event_task(cast(int,order_from_db.id), OrderEvent.ORDER_REJECTED.value, str(exc) or "Unknown error")
        db.rollback()
        raise self.retry(exc=exc)
