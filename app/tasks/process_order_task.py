import json
import time
from shared_architecture.db.models.order_model import OrderModel
from shared_architecture.enums import OrderEvent
from app.core.config import settings
from app.tasks.get_api_key_task import get_api_key_task
from app.core.celery_config import celery_app
from app.utils.celery_db_helper import get_celery_db_session
from datetime import datetime
from typing import cast, Any, Union

# Import AutoTrader with fallback and proper typing
try:
    from com.dakshata.autotrader.api.AutoTrader import AutoTrader as RealAutoTrader
    AUTOTRADER_AVAILABLE = True
except ImportError:
    AUTOTRADER_AVAILABLE = False
    RealAutoTrader = None  # type: ignore

# Mock AutoTrader classes for when the real one isn't available
class AutoTraderResponse:
    def __init__(self, success=False, result=None, message="Mock response"):
        self._success = success
        self.result = result or {}
        self.message = message
    
    def success(self):
        return self._success

class AutoTraderMock:
    @staticmethod
    def create_instance(api_key: str, server_url: str) -> 'AutoTraderMock':
        return AutoTraderMock()
    
    SERVER_URL = "mock_url"
    
    def place_regular_order(self, **kwargs: Any) -> AutoTraderResponse:
        return AutoTraderResponse(success=True, result={"order_id": "MOCK_12345", "status": "COMPLETE"})
    
    def place_cover_order(self, **kwargs: Any) -> AutoTraderResponse:
        return AutoTraderResponse(success=True, result={"order_id": "MOCK_12345", "status": "COMPLETE"})
    
    def place_bracket_order(self, **kwargs: Any) -> AutoTraderResponse:
        return AutoTraderResponse(success=True, result={"order_id": "MOCK_12345", "status": "COMPLETE"})
    
    def place_advanced_order(self, **kwargs: Any) -> AutoTraderResponse:
        return AutoTraderResponse(success=True, result={"order_id": "MOCK_12345", "status": "COMPLETE"})
    
    def cancel_order_by_platform_id(self, **kwargs: Any) -> AutoTraderResponse:
        return AutoTraderResponse(success=True, result={"status": "CANCELLED"})
    
    def cancel_child_orders_by_platform_id(self, **kwargs: Any) -> AutoTraderResponse:
        return AutoTraderResponse(success=True, result={"status": "CANCELLED"})
    
    def modify_order_by_platform_id(self, **kwargs: Any) -> AutoTraderResponse:
        return AutoTraderResponse(success=True, result={"status": "MODIFIED"})
    
    def square_off_position(self, **kwargs: Any) -> AutoTraderResponse:
        return AutoTraderResponse(success=True, result={"status": "SQUARED_OFF"})
    
    def square_off_portfolio(self, **kwargs: Any) -> AutoTraderResponse:
        return AutoTraderResponse(success=True, result={"status": "SQUARED_OFF"})
    
    def cancel_all_orders(self, **kwargs: Any) -> AutoTraderResponse:
        return AutoTraderResponse(success=True, result={"status": "CANCELLED"})

# Create a function to get the appropriate AutoTrader
def get_autotrader_instance(api_key: str, server_url: str) -> Union[Any, AutoTraderMock]:
    if AUTOTRADER_AVAILABLE and RealAutoTrader:
        return RealAutoTrader.create_instance(api_key, server_url)
    else:
        return AutoTraderMock.create_instance(api_key, server_url)
@celery_app.task(bind=True, max_retries=3, default_retry_delay=5)
def process_order_task(self, order_dict: dict, organization_id: str):
    """
    Celery task to asynchronously process an order (place, cancel, modify, square off).
    Interacts with StocksDeveloper API.
    """
    db = get_celery_db_session()

    try:
        order = db.query(OrderModel).filter_by(id=order_dict['id']).first()
        if not order:
            raise ValueError(f"Order with ID {order_dict['id']} not found in DB for processing.")

        api_key = get_api_key_task(organization_id)
        stocksdeveloper_conn = get_autotrader_instance(api_key, "https://api.stocksdeveloper.in")

        order_status_result = {}

        if getattr(settings, 'mock_order_execution', True):  # Default to True for safety
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

        # Publish to RabbitMQ if available
        try:
            from shared_architecture.utils.rabbitmq_helper import publish_message
            rabbitmq_url = getattr(settings, 'RABBITMQ_URL', None)
            if rabbitmq_url:
                queue_name = "order_status_events"
                payload = {
                    "order_id": order.id,
                    "status": order.status,
                    "timestamp": datetime.utcnow().isoformat()
                }
                publish_message(rabbitmq_url, queue_name, payload)
        except Exception as e:
            print(f"Failed to publish to RabbitMQ: {e}")

        # Send the update task using celery_app.send_task
        celery_app.send_task('update_order_status_task', args=[cast(int, order.id), order_status_result])

    except Exception as exc:
        print(f"Celery Task {self.request.id} failed for Order {order_dict.get('id')}: {exc}")
        try:
            order_from_db = db.query(OrderModel).filter_by(id=order_dict['id']).first()
            if order_from_db:
                order_from_db.status = "REJECTED"  # type: ignore
                order_from_db.status_message = str(exc)  # type: ignore
                db.commit()
                # Use celery_app.send_task to create order event
                celery_app.send_task('create_order_event_task', args=[
                    cast(int, order_from_db.id), 
                    OrderEvent.ORDER_REJECTED.value, 
                    str(exc) or "Unknown error"
                ])
        except Exception as db_error:
            print(f"Failed to update order status in database: {db_error}")
            db.rollback()
        
        raise self.retry(exc=exc)
    finally:
        db.close()