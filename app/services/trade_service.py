# trade_service/app/services/trade_service.py
import httpx
import json
from shared_architecture.utils.service_helpers import connection_manager
from shared_architecture.models.broker import Broker
from sqlalchemy.orm import Session
from app.core.config import settings
from com.dakshata.autotrader.api.AutoTrader import AutoTrader, PlatformHolding
import requests
from datetime import datetime
from app.models.margin_model import MarginModel
from app.models.position_model import PositionModel
from app.models.holding_model import HoldingModel
from app.models.order_model import OrderModel, OrderTransitionType
from app.models.order_event_model import OrderEventModel
from app.utils.rate_limiter import RateLimiter
from fastapi import HTTPException, BackgroundTasks
from app.schemas.margin_schema import MarginSchema
from app.schemas.position_schema import PositionSchema
from app.schemas.holding_schema import HoldingSchema
from app.schemas.order_schema import OrderSchema
import pickle
from app.core.celery_config import celery_app
from app.core.enums import OrderEvent

# Define the Celery task
@celery_app.task(bind=True, max_retries=3)
def process_order_task(self, order_dict: dict, organization_id: str):
    """
    Celery task to asynchronously process an order.
    """
    db = connection_manager.get_timescaledb_session()
    try:
        order = OrderModel(**order_dict)  # Recreate OrderModel from dict
        api_key = celery_app.control.apply(get_api_key_task.name, (organization_id,))
        stocksdeveloper_conn = AutoTrader.create_instance(api_key, AutoTrader.SERVER_URL)

        if settings.mock_order_execution:
            # Mock order execution for development/testing
            order_status = {
                "status": "COMPLETE",
                "average_price": order.price,
                "filled_quantity": order.quantity,
                "order_id": str(order.id),  # Use local order ID
                "exchange_order_id": "MOCK_" + str(order.id),
            }
        else:
            # Real order execution
            if order.variety == "REGULAR":
                response = stocksdeveloper_conn.place_regular_order(
                    pseudo_account=order.pseudo_account,
                    exchange=order.exchange,
                    symbol=order.symbol,
                    tradeType=order.trade_type,
                    orderType=order.order_type,
                    productType=order.product_type,
                    quantity=order.quantity,
                    price=order.price,
                    triggerPrice=order.trigger_price
                )
            elif order.variety == "CO":
                response = stocksdeveloper_conn.place_cover_order(
                    pseudo_account=order.pseudo_account,
                    exchange=order.exchange,
                    symbol=order.symbol,
                    tradeType=order.trade_type,
                    orderType=order.order_type,
                    quantity=order.quantity,
                    price=order.price,
                    triggerPrice=order.trigger_price
                )
            elif order.variety == "BO":
                response = stocksdeveloper_conn.place_bracket_order(
                    pseudo_account=order.pseudo_account,
                    exchange=order.exchange,
                    symbol=order.symbol,
                    tradeType=order.trade_type,
                    orderType=order.order_type,
                    quantity=order.quantity,
                    price=order.price,
                    triggerPrice=order.trigger_price,
                    target=order.target,
                    stoploss=order.stoploss,
                    trailingStoploss=order.trailingStoploss
                )
            elif order.variety == "AMO":
                response = stocksdeveloper_conn.place_advanced_order(
                    variety=order.variety,
                    pseudo_account=order.pseudo_account,
                    exchange=order.exchange,
                    symbol=order.symbol,
                    tradeType=order.trade_type,
                    orderType=order.order_type,
                    productType=order.product_type,
                    quantity=order.quantity,
                    price=order.price,
                    triggerPrice=order.trigger_price,
                    target=order.target,
                    stoploss=order.stoploss,
                    trailingStoploss=order.trailingStoploss,
                    disclosedQuantity=order.disclosed_quantity,
                    validity=order.validity,
                    amo=order.amo,
                    strategyId=order.strategy_id,
                    comments=order.comments,
                    publisherId=order.publisher_id
                )
            elif order.variety == "CANCEL":
                response = stocksdeveloper_conn.cancel_order_by_platform_id(
                    pseudo_account=order.pseudo_account,
                    platform_id=order.platform
                )
            elif order.variety == "CANCEL_CHILD":
                response = stocksdeveloper_conn.cancel_child_orders_by_platform_id(
                    pseudo_account=order.pseudo_account,
                    platform_id=order.platform
                )
            elif order.variety == "MODIFY":
                response = stocksdeveloper_conn.modify_order_by_platform_id(
                    pseudo_account=order.pseudo_account,
                    platform_id=order.platform,
                    order_type=order.order_type,
                    quantity=order.quantity,
                    price=order.price,
                    trigger_price=order.trigger_price
                )
            elif order.variety == "SQUARE_OFF_POSITION":
                response = stocksdeveloper_conn.square_off_position(
                    pseudo_account=order.pseudo_account,
                    position_category=order.position_category,
                    position_type=order.position_type,
                    exchange=order.exchange,
                    symbol=order.symbol
                )
            elif order.variety == "SQUARE_OFF_PORTFOLIO":
                response = stocksdeveloper_conn.square_off_portfolio(
                    pseudo_account=order.pseudo_account,
                    position_category=order.position_category
                )
            elif order.variety == "CANCEL_ALL_ORDERS":
                response = stocksdeveloper_conn.cancel_all_orders(
                    pseudo_account=order.pseudo_account
                )
            else:
                raise ValueError(f"Invalid order variety: {order.variety}")

            if response.success():
                order_status = response.result
            else:
                raise Exception(response.message)

            celery_app.control.apply(update_order_status_task.name, (order.id, order_status))

        except Exception as exc:
            print(f"Task {self.request.id} failed: {exc}")
            order.status = "REJECTED"  # Or another appropriate status
            order.status_message = str(exc)  # Store the error message
            celery_app.control.apply(create_order_event_task.name, (order.id, OrderEvent.ORDER_REJECTED.value, str(exc)))
            db.rollback()
            raise self.retry(exc=exc, countdown=2 ** self.request.retries)
        finally:
            db.close()

@celery_app.task
def update_order_status_task(order_id: int, order_status: dict):
    """
    Celery task to update the order status in the database.
    """
    db = connection_manager.get_timescaledb_session()
    try:
        order = db.query(OrderModel).get(order_id)
        if order:
            old_status = order.status
            order.status = order_status["status"]
            order.average_price = order_status.get("average_price")
            order.filled_quantity = order_status.get("filled_quantity")
            order.status_message = order_status.get("status_message")
            order.exchange_order_id = order_status.get("exchange_order_id")
            db.commit()

            # Create Order Events
            if order.status != old_status:
                if order.status == "COMPLETE":
                    celery_app.control.apply(create_order_event_task.name, (order.id, OrderEvent.ORDER_FILLED.value))
                elif order.status == "PARTIALLY_FILLED":
                    celery_app.control.apply(create_order_event_task.name, (order.id, OrderEvent.ORDER_PARTIALLY_FILLED.value))
                elif order.status == "CANCELLED":
                    celery_app.control.apply(create_order_event_task.name, (order.id, OrderEvent.ORDER_CANCELLED.value))
                elif order.status == "REJECTED":
                    celery_app.control.apply(create_order_event_task.name, (order.id, OrderEvent.ORDER_REJECTED.value, order.status_message))
                elif order.status == "MODIFIED":
                    celery_app.control.apply(create_order_event_task.name, (order.id, OrderEvent.ORDER_MODIFIED.value))
                elif order.status == "ACCEPTED":
                    celery_app.control.apply(create_order_event_task.name, (order.id, OrderEvent.ORDER_ACCEPTED.value))
                else:
                    celery_app.control.apply(create_order_event_task.name, (order.id, OrderEvent.ORDER_PLACED.value))

            if order.status in ["COMPLETE", "PARTIALLY_FILLED"]:
                celery_app.control.apply(update_positions_and_holdings_task.name, (order,))
        else:
            print(f"Order with ID {order_id} not found in the database.")
    except Exception as e:
        print(f"Error updating order status: {e}")
        db.rollback()
    finally:
        db.close()

@celery_app.task
def create_order_event_task(order_id: int, event_type: str, details: str = None):
    """
    Celery task to create an order event.
    """
    db = connection_manager.get_timescaledb_session()
    try:
        order = db.query(OrderModel).get(order_id)
        if order:
            event = OrderEventModel(order_id=order.id, event_type=event_type, details=details)
            db.add(event)
            db.commit()
        else:
            print(f"Order with ID {order_id} not found in the database.")
    except Exception as e:
        print(f"Error creating order event: {e}")
        db.rollback()
    finally:
        db.close()

@celery_app.task
def update_positions_and_holdings_task(order: OrderModel):
    """
    Celery task to update positions and holdings.
    """
    db = connection_manager.get_timescaledb_session()
    try:
        trade_service = TradeService(db)
        trade_service._update_positions_and_holdings(order)
        db.commit()
    except Exception as e:
        print(f"Error updating positions and holdings: {e}")
        db.rollback()
    finally:
        db.close()

@celery_app.task
def get_api_key_task(organization_id: str):
    """
    Celery task to retrieve the API key for a given organization, with caching.
    """
    redis_conn = connection_manager.get_redis_connection()
    cached_key = redis_conn.get(f"api_key:{organization_id}")
    if cached_key:
        return cached_key.decode("utf-8")

    # Call user service to get the API key
    user_service_url = settings.user_service_url
    try:
        response = requests.get(f"{user_service_url}/api_key/{organization_id}")
        response.raise_for_status()
        api_key = response.json()["api_key"]
        redis_conn.set(f"api_key:{organization_id}", api_key.encode("utf-8"), ex=3600)
        return api_key
    except Exception as e:
        print(f"Error getting API key: {e}")
        raise e
    finally:
        redis_conn.close()

class TradeService:
    def __init__(self, db: Session):
        self.db = db
        self.rabbitmq_conn = connection_manager.get_rabbitmq_connection()
        self.timescaledb_conn = connection_manager.get_timescaledb_session()
        self.redis_conn = connection_manager.get_redis_connection()
        self.rate_limiter = RateLimiter(self.redis_conn)

    async def execute_trade_order(
        self,
        trade_order: TradeOrder,
        organization_id: str,
        background_tasks: BackgroundTasks = None,
    ):
        if not self.rate_limiter.user_rate_limit(trade_order.user_id, organization_id) or not self.rate_limiter.account_rate_limit(trade_order.user_id, organization_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        instrument_key = f"{trade_order.symbol}@@@"  # Construct instrument_key (adjust as needed)
        # Create a dummy OrderModel for asynchronous processing
        order_entry = OrderModel(
            pseudo_account=trade_order.user_id,
            symbol=trade_order.symbol,
            quantity=trade_order.quantity,
            price=trade_order.price,
            trade_type=trade_order.side,
            variety="REGULAR",
            instrument_key=instrument_key
        )
        self.db.add(order_entry)
        self.db.commit()

        await self._create_order_event(order_entry, OrderEvent.ORDER_PLACED)

        # Enqueue the task
        process_order_task.delay(order_entry.__dict__, organization_id)

        return {"message": "Order processing started"}

    async def get_trade_status(self, order_id: str, organization_id: str):
        if not self.rate_limiter.user_rate_limit(order_id, organization_id) or not self.rate_limiter.account_rate_limit(order_id, organization_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        # StocksDeveloper API call to get order status
        cached_status = self.redis_conn.get(f"name:{pseudo_account}:order_status:{order_id}")
        if cached_status:
            return pickle.loads(cached_status)

        api_key = await self._get_api_key(organization_id)
        stocksdeveloper_conn = AutoTrader.create_instance(api_key, AutoTrader.SERVER_URL)
        order_status = stocksdeveloper_conn.get_order_status(order_id=order_id)

        self.redis_conn.set(f"name:{pseudo_account}:order_status:{order_id}", pickle.dumps(order_status), ex=300)

        return order_status

    async def fetch_and_store_data(self, pseudo_acc: str, organization_id: str):
        if not self.rate_limiter.account_rate_limit(pseudo_acc, organization_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        api_key = await self._get_api_key(organization_id)
        stocksdeveloper_conn = AutoTrader.create_instance(api_key, AutoTrader.SERVER_URL)

        # Fetch and store margins
        margins = stocksdeveloper_conn.read_platform_margins(pseudo_account=pseudo_acc)
        for margin in margins:
            instrument_key = f"{margin.get('exchange', '')}@{margin.get('symbol', '')}@@@"  # Construct instrument_key
            margin_entry = MarginModel(**margin, pseudo_account=pseudo_acc, margin_date=datetime.utcnow(), instrument_key=instrument_key)
            self.db.add(margin_entry)
            self.redis_conn.set(f"name:{pseudo_acc}:margin:{margin['category']}", pickle.dumps(MarginSchema.from_orm(margin_entry)), ex=300)

        # Fetch and store positions
        positions = stocksdeveloper_conn.read_platform_positions(pseudo_account=pseudo_acc)
        for position in positions:
            instrument_key = f"{position.get('exchange', '')}@{position.get('symbol', '')}@@@"  # Construct instrument_key
            position_entry = PositionModel(**position, pseudo_account=pseudo_acc, instrument_key=instrument_key)
            self.db.add(position_entry)
            self.redis_conn.set(f"name:{pseudo_acc}:position:{position['symbol']}", pickle.dumps(PositionSchema.from_orm(position_entry)), ex=300)

        # Fetch and store holdings
        holdings = stocksdeveloper_conn.read_platform_holdings(pseudo_account=pseudo_acc)
        for holding in holdings:
            instrument_key = f"{holding.get('exchange', '')}@{holding.get('symbol', '')}@@@"  # Construct instrument_key
            holding_entry = HoldingModel(**holding, pseudo_account=pseudo_acc, instrument_key=instrument_key)
            self.db.add(holding_entry)
            self.redis_conn.set(f"name:{pseudo_acc}:holding:{holding['symbol']}", pickle.dumps(HoldingSchema.from_orm(holding_entry)), ex=300)

        # Fetch and store orders
        orders = stocksdeveloper_conn.read_platform_orders(pseudo_account=pseudo_acc)
        for order in orders:
            instrument_key = f"{order.get('exchange', '')}@{order.get('symbol', '')}@@@"  # Construct instrument_key
            order_entry = OrderModel(**order, pseudo_account=pseudo_acc, instrument_key=instrument_key)
            self.db.add(order_entry)
            self.redis_conn.set(f"name:{pseudo_acc}:order:{order['id']}", pickle.dumps(OrderSchema.from_orm(order_entry)), ex=300)

        self.db.commit()

    async def fetch_all_trading_accounts(self, organization_id: str):
        if not self.rate_limiter.account_rate_limit("fetchAllTradingAccounts", organization_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        api_key = await self._get_api_key(organization_id)
        headers = {"api-key": api_key}
        url = "https://apix.stocksdeveloper.in/account/fetchAllTradingAccounts"
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            trading_accounts_data = response.json()
            return trading_accounts_data
        except requests.exceptions.RequestException as e:
            raise HTTPException(status_code=500, detail=str(e))
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=500, detail=str(e))

    async def _check_for_conflicting_orders(self, pseudo_account: str, instrument_key: str, trade_type: str, strategy_id: str):
        """
        Checks for conflicting orders/positions/holdings on the same instrument.
        """
        existing_positions = self.db.query(PositionModel).filter_by(pseudo_account=pseudo_account, instrument_key=instrument_key).all()
        existing_orders = self.db.query(OrderModel).filter_by(pseudo_account=pseudo_account, instrument_key=instrument_key).filter(OrderModel.status.in_(['PENDING', 'PARTIALLY_FILLED'])).all()
        existing_holdings = self.db.query(HoldingModel).filter_by(pseudo_account=pseudo_account, instrument_key=instrument_key).all()

        for position in existing_positions:
            if position.strategy_id != strategy_id:
                if trade_type == "BUY" and position.direction == "SELL":
                    raise HTTPException(status_code=409, detail=f"Conflict: Cannot place BUY order when SELL position exists from another strategy ({position.strategy_id})")
                elif trade_type == "SELL" and position.direction == "BUY":
                    raise HTTPException(status_code=409, detail=f"Conflict: Cannot place SELL order when BUY position exists from another strategy ({position.strategy_id})")

        for order in existing_orders:
            if order.strategy_id != strategy_id:
                if trade_type == "BUY" and order.trade_type == "SELL":
                    raise HTTPException(status_code=409, detail=f"Conflict: Cannot place BUY order when SELL order exists from another strategy ({order.strategy_id})")
                elif trade_type == "SELL" and order.trade_type == "BUY":
                    raise HTTPException(status_code=409, detail=f"Conflict: Cannot place SELL order when BUY order exists from another strategy ({order.strategy_id})")

        for holding in existing_holdings:
            if holding.strategy_id != strategy_id:
                if trade_type == "BUY" and holding.quantity < 0:
                    raise HTTPException(status_code=409, detail=f"Conflict: Cannot place BUY order when SELL holding exists from another strategy ({holding.strategy_id})")
                elif trade_type == "SELL" and holding.quantity > 0:
                    raise HTTPException(status_code=409, detail=f"Conflict: Cannot place SELL order when BUY holding exists from another strategy ({holding.strategy_id})")

    async def _handle_holding_to_position_transition(
        self,
        pseudo_account: str,
        instrument_key: str,
        quantity: int,
        strategy_id: str,
    ):
        """
        Handles the transition of holdings to positions when a sell order is placed.
        """
        existing_holding = self.db.query(HoldingModel).filter_by(
            pseudo_account=pseudo_account,
            instrument_key=instrument_key,
            strategy_id=strategy_id
        ).first()

        if not existing_holding:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient holdings for {instrument_key} for strategy {strategy_id}",
            )

        if existing_holding.quantity < quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient holdings for {instrument_key} for strategy {strategy_id}",
            )

        existing_holding.quantity -= quantity
        new_position = PositionModel(
            pseudo_account=pseudo_account,
            instrument_key=instrument_key,
            strategy_id=strategy_id,
            source_strategy_id=strategy_id,
            net_quantity=-quantity,
            sell_quantity=quantity,
            direction="SELL"
        )
        self.db.add(new_position)
        self.db.commit()

    async def _update_positions_and_holdings(self, order: OrderModel):
        """
        Updates positions and holdings based on order execution.
        This is the most complex logic.
        """

        if order.status not in ["COMPLETE", "PARTIALLY_FILLED"]:
            return  # Only update on completed/partially filled orders

        quantity_filled = order.filled_quantity if order.filled_quantity else order.quantity

        if quantity_filled == 0:
            return

        instrument_key = order.instrument_key
        pseudo_account = order.pseudo_account
        strategy_id = order.strategy_id
        trade_type = order.trade_type

        # 1. Update/Create Position
        existing_position = self.db.query(PositionModel).filter_by(
            pseudo_account=pseudo_account,
            instrument_key=instrument_key,
            strategy_id=strategy_id
        ).first()

        if existing_position:
            if trade_type == "BUY":
                existing_position.net_quantity += quantity_filled
                existing_position.buy_quantity += quantity_filled
                existing_position.buy_value += order.price * quantity_filled
                existing_position.buy_avg_price = existing_position.buy_value / existing_position.buy_quantity if existing_position.buy_quantity else 0
                existing_position.direction = "BUY"
            elif trade_type == "SELL":
                existing_position.net_quantity -= quantity_filled
                existing_position.sell_quantity += quantity_filled
                existing_position.sell_value += order.price * quantity_filled
                existing_position.sell_avg_price = existing_position.sell_value / existing_position.sell_quantity if existing_position.sell_quantity else 0
                existing_position.direction = "SELL"
        else:
            if trade_type == "BUY":
                new_position = PositionModel(
                    pseudo_account=pseudo_account,
                    instrument_key=instrument_key,
                    strategy_id=strategy_id,
                    net_quantity=quantity_filled,
                    buy_quantity=quantity_filled,
                    buy_value=order.price * quantity_filled,
                    buy_avg_price=order.price,
                    direction="BUY"
                )
            elif trade_type == "SELL":
                new_position = PositionModel(
                    pseudo_account=pseudo_account,
                    instrument_key=instrument_key,
                    strategy_id=strategy_id,
                    net_quantity=-quantity_filled,
                    sell_quantity=quantity_filled,
                    sell_value=order.price * quantity_filled,
                    sell_avg_price=order.price,
                    direction="SELL"
                )
            self.db.add(new_position)

        # 2. Handle Position to Holding Transition
        if order.product_type not in ["OPTIONS", "FUTURES"]:  # Equity logic
            if datetime.now().hour >= 15:  # After market close (adjust as needed)
                existing_holding = self.db.query(HoldingModel).filter_by(
                    pseudo_account=pseudo_account,
                    instrument_key=instrument_key,
                    strategy_id=strategy_id
                ).first()

                if existing_holding:
                    existing_holding.quantity += existing_position.net_quantity
                else:
                    new_holding = HoldingModel(
                        pseudo_account=pseudo_account,
                        instrument_key=instrument_key,
                        strategy_id=strategy_id,
                        quantity=existing_position.net_quantity,
                        product=order.product_type
                    )
                    self.db.add(new_holding)

                self.db.delete(existing_position)  # delete the position record
                order.transition_type = OrderTransitionType.POSITION_TO_HOLDING

        self.db.commit()

    async def get_organization_id_from_name(self, organization_name: str) -> str:
        """
        Retrieves the organization ID from the organization name.
        This is a placeholder - replace with your actual logic to fetch this from the user service or wherever you store organization data.
        """
        # Placeholder logic - replace with your actual implementation
        # For example, you might call the user service:
        user_service_url = settings.user_service_url
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{user_service_url}/organizations/{organization_name}")
            response.raise_for_status()
            organization_data = response.json()
            return organization_data["id"]
        # Or you might have a local mapping:
        # organization_mapping = {"Org A": "org_a_id", "Org B": "org_b_id"}
        # return organization_mapping.get(organization_name)
        # If not found, raise an exception:
        # raise ValueError(f"Organization not found: {organization_name}")
        pass

    async def get_orders_by_organization_and_user(self, user_id: str) -> List[OrderSchema]:
        try:
            organization_name = await self._get_organization_name_for_user(user_id)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

        if not self.rate_limiter.account_rate_limit(user_id, organization_name):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        orders = self.db.query(OrderModel).filter_by(pseudo_account=user_id).all()
        return [OrderSchema.from_orm(order) for order in orders]

    async def get_positions_by_organization_and_user(self, user_id: str) -> List[PositionSchema]:
        try:
            organization_name = await self._get_organization_name_for_user(user_id)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

        if not self.rate_limiter.account_rate_limit(user_id, organization_name):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        positions = self.db.query(PositionModel).filter_by(pseudo_account=user_id).all()
        return [PositionSchema.from_orm(position) for position in positions]

    async def get_holdings_by_organization_and_user(self, user_id: str) -> List[HoldingSchema]:
        try:
            organization_name = await self._get_organization_name_for_user(user_id)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

        if not self.rate_limiter.account_rate_limit(user_id, organization_name):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        holdings = self.db.query(HoldingModel).filter_by(pseudo_account=user_id).all()
        return [HoldingSchema.from_orm(holding) for holding in holdings]

    async def get_margins_by_organization_and_user(self, user_id: str) -> List[MarginSchema]:
        try:
            organization_name = await self._get_organization_name_for_user(user_id)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

        if not self.rate_limiter.account_rate_limit(user_id, organization_name):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        margins = self.db.query(MarginModel).filter_by(pseudo_account=user_id).all()
        return [MarginSchema.from_orm(margin) for margin in margins]

    async def get_orders_by_strategy(self, strategy_name: str) -> List[OrderSchema]:
        orders = self.db.query(OrderModel).filter_by(strategy_id=strategy_name).all()
        return [OrderSchema.from_orm(order) for order in orders]

    async def get_positions_by_strategy(self, strategy_name: str) -> List[PositionSchema]:
        positions = self.db.query(PositionModel).filter_by(strategy_id=strategy_name).all()
        return [PositionSchema.from_orm(position) for position in positions]

    async def get_holdings_by_strategy(self, strategy_name: str) -> List[HoldingSchema]:
        holdings = self.db.query(HoldingModel).filter_by(strategy_id=strategy_name).all()
        return [HoldingSchema.from_orm(holding) for holding in holdings]

    async def get_api_key(self, organization_id: str) -> str:
        """
        Celery task to retrieve the API key for a given organization, with caching.
        """
        redis_conn = connection_manager.get_redis_connection()
        cached_key = redis_conn.get(f"api_key:{organization_id}")
        if cached_key:
            return cached_key.decode("utf-8")

        # Call user service to get the API key
        user_service_url = settings.user_service_url
        try:
            response = requests.get(f"{user_service_url}/api_key/{organization_id}")
            response.raise_for_status()
            api_key = response.json()["api_key"]
            redis_conn.set(f"api_key:{organization_id}", api_key.encode("utf-8"), ex=3600)
            return api_key
        except Exception as e:
            print(f"Error getting API key: {e}")
            raise e
        finally:
            redis_conn.close()

async def place_regular_order(
        self,
        pseudo_account: str,
        exchange: str,
        symbol: str,
        tradeType: str,
        orderType: str,
        productType: str,
        quantity: int,
        price: float,
        triggerPrice: float = 0.0,
        strategy_id: str = None,
        organization_id: str = None,
        background_tasks: BackgroundTasks = None,
    ):
        if not self.rate_limiter.user_rate_limit(pseudo_account, organization_id) or not self.rate_limiter.account_rate_limit(pseudo_account, organization_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        instrument_key = f"{exchange}@{symbol}@{productType}@@@"
        await self._check_for_conflicting_orders(pseudo_account, instrument_key, tradeType, strategy_id)

        if tradeType == "SELL":
            await self._handle_holding_to_position_transition(pseudo_account, instrument_key, quantity, strategy_id)

        # Create the OrderModel (without interacting with StocksDeveloper yet)
        order_entry = OrderModel(
            pseudo_account=pseudo_account,
            exchange=exchange,
            symbol=symbol,
            trade_type=tradeType,
            order_type=orderType,
            product_type=productType,
            quantity=quantity,
            price=price,
            trigger_price=triggerPrice,
            strategy_id=strategy_id,
            instrument_key=instrument_key,
            transition_type=OrderTransitionType.HOLDING_TO_POSITION if tradeType == "SELL" else OrderTransitionType.NONE,
            variety="REGULAR"
        )
        self.db.add(order_entry)
        self.db.commit()

        await self._create_order_event(order_entry, OrderEvent.ORDER_PLACED)

        # Enqueue the task
        process_order_task.delay(order_entry.__dict__, organization_id)

        return {"message": "Order processing started"}

    async def place_cover_order(
        self,
        pseudo_account: str,
        exchange: str,
        symbol: str,
        tradeType: str,
        orderType: str,
        quantity: int,
        price: float,
        triggerPrice: float,
        strategy_id: str = None,
        organization_id: str = None,
        background_tasks: BackgroundTasks = None,
    ):
        if not self.rate_limiter.user_rate_limit(pseudo_account, organization_id) or not self.rate_limiter.account_rate_limit(pseudo_account, organization_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        instrument_key = f"{exchange}@{symbol}@@@"
        await self._check_for_conflicting_orders(pseudo_account, instrument_key, tradeType, strategy_id)

        if tradeType == "SELL":
            await self._handle_holding_to_position_transition(pseudo_account, instrument_key, quantity, strategy_id)

        # Create the OrderModel (without interacting with StocksDeveloper yet)
        order_entry = OrderModel(
            pseudo_account=pseudo_account,
            exchange=exchange,
            symbol=symbol,
            trade_type=tradeType,
            order_type=orderType,
            product_type="CO",  # Hardcoded for Cover Order
            quantity=quantity,
            price=price,
            trigger_price=triggerPrice,
            strategy_id=strategy_id,
            instrument_key=instrument_key,
            transition_type=OrderTransitionType.HOLDING_TO_POSITION if tradeType == "SELL" else OrderTransitionType.NONE,
            variety="CO"
        )
        self.db.add(order_entry)
        self.db.commit()

        await self._create_order_event(order_entry, OrderEvent.ORDER_PLACED)

        # Enqueue the task
        process_order_task.delay(order_entry.__dict__, organization_id)

        return {"message": "Cover Order processing started"}

    async def place_bracket_order(
        self,
        pseudo_account: str,
        exchange: str,
        symbol: str,
        tradeType: str,
        orderType: str,
        quantity: int,
        price: float,
        triggerPrice: float,
        target: float,
        stoploss: float,
        trailingStoploss: float = 0.0,
        strategy_id: str = None,
        organization_id: str = None,
        background_tasks: BackgroundTasks = None,
    ):
        if not self.rate_limiter.user_rate_limit(pseudo_account, organization_id) or not self.rate_limiter.account_rate_limit(pseudo_account, organization_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        instrument_key = f"{exchange}@{symbol}@@@"
        await self._check_for_conflicting_orders(pseudo_account, instrument_key, tradeType, strategy_id)

        if tradeType == "SELL":
            await self._handle_holding_to_position_transition(pseudo_account, instrument_key, quantity, strategy_id)

        # Create the OrderModel (without interacting with StocksDeveloper yet)
        order_entry = OrderModel(
            pseudo_account=pseudo_account,
            exchange=exchange,
            symbol=symbol,
            trade_type=tradeType,
            order_type=orderType,
            product_type="BO",  # Hardcoded for Bracket Order
            quantity=quantity,
            price=price,
            trigger_price=triggerPrice,
            strategy_id=strategy_id,
            instrument_key=instrument_key,
            transition_type=OrderTransitionType.HOLDING_TO_POSITION if tradeType == "SELL" else OrderTransitionType.NONE,
            variety="BO"
        )
        order_entry.target = target
        order_entry.stoploss = stoploss
        order_entry.trailingStoploss = trailingStoploss
        self.db.add(order_entry)
        self.db.commit()

        await self._create_order_event(order_entry, OrderEvent.ORDER_PLACED)

        # Enqueue the task
        process_order_task.delay(order_entry.__dict__, organization_id)

        return {"message": "Bracket Order processing started"}

    async def place_advanced_order(
        self,
        variety: str,
        pseudo_account: str,
        exchange: str,
        symbol: str,
        tradeType: str,
        orderType: str,
        productType: str,
        quantity: int,
        price: float,
        triggerPrice: float,
        target: float,
        stoploss: float,
        trailingStoploss: float,
        disclosedQuantity: int,
        validity: str,
        amo: bool,
        strategyId: str,
        comments: str,
        publisherId: str,
        organization_id: str,
        background_tasks: BackgroundTasks = None,
    ):
        if not self.rate_limiter.user_rate_limit(pseudo_account, organization_id) or not self.rate_limiter.account_rate_limit(pseudo_account, organization_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        instrument_key = f"{exchange}@{symbol}@{productType}@@@"
        await self._check_for_conflicting_orders(pseudo_account, instrument_key, tradeType, strategyId)

        if tradeType == "SELL":
            await self._handle_holding_to_position_transition(pseudo_account, instrument_key, quantity, strategyId)

        # Create the OrderModel (without interacting with StocksDeveloper yet)
        order_entry = OrderModel(
            variety=variety,
            pseudo_account=pseudo_account,
            exchange=exchange,
            symbol=symbol,
            trade_type=tradeType,
            order_type=orderType,
            product_type=productType,
            quantity=quantity,
            price=price,
            trigger_price=triggerPrice,
            target=target,
            stoploss=stoploss,
            trailingStoploss=trailingStoploss,
            disclosed_quantity=disclosedQuantity,
            validity=validity,
            amo=amo,
            strategy_id=strategyId,
            comments=comments,
            publisher_id=publisherId,
            instrument_key=instrument_key,
            transition_type=OrderTransitionType.HOLDING_TO_POSITION if tradeType == "SELL" else OrderTransitionType.NONE
        )
        self.db.add(order_entry)
        self.db.commit()

        await self._create_order_event(order_entry, OrderEvent.ORDER_PLACED)

        # Enqueue the task
        process_order_task.delay(order_entry.__dict__, organization_id)

        return {"message": "Advanced Order processing started"}

    async def cancel_order_by_platform_id(
        self,
        pseudo_account: str,
        platform_id: str,
        organization_id: str,
        background_tasks: BackgroundTasks = None,
    ):
        if not self.rate_limiter.user_rate_limit(pseudo_account, organization_id) or not self.rate_limiter.account_rate_limit(pseudo_account, organization_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        # Create a dummy OrderModel for asynchronous processing
        order_entry = OrderModel(
            pseudo_account=pseudo_account,
            platform=platform_id,
            variety="CANCEL",
            instrument_key=None,
        )
        self.db.add(order_entry)
        self.db.commit()

        await self._create_order_event(order_entry, OrderEvent.ORDER_PLACED)

        # Enqueue the task
        process_order_task.delay(order_entry.__dict__, organization_id)

        return {"message": f"Cancel order request submitted for platform_id: {platform_id}"}

    async def cancel_child_orders_by_platform_id(
        self,
        pseudo_account: str,
        platform_id: str,
        organization_id: str,
        background_tasks: BackgroundTasks = None,
    ):
        if not self.rate_limiter.user_rate_limit(pseudo_account, organization_id) or not self.rate_limiter.account_rate_limit(pseudo_account, organization_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        # Create a dummy OrderModel for asynchronous processing
        order_entry = OrderModel(
            pseudo_account=pseudo_account,
            platform=platform_id,
            variety="CANCEL_CHILD",
            instrument_key=None,
        )
        self.db.add(order_entry)
        self.db.commit()

        await self._create_order_event(order_entry, OrderEvent.ORDER_PLACED)

        # Enqueue the task
        process_order_task.delay(order_entry.__dict__, organization_id)

        return {"message": f"Cancel child orders request submitted for platform_id: {platform_id}"}

    async def modify_order_by_platform_id(
        self,
        pseudo_account: str,
        platform_id: str,
        order_type: str = None,
        quantity: int = None,
        price: float = None,
        trigger_price: float = None,
        organization_id: str = None,
        background_tasks: BackgroundTasks = None,
    ):
        if not self.rate_limiter.user_rate_limit(pseudo_account, organization_id) or not self.rate_limiter.account_rate_limit(pseudo_account, organization_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        # Create a dummy OrderModel for asynchronous processing
        order_entry = OrderModel(
            pseudo_account=pseudo_account,
            platform=platform_id,
            variety="MODIFY",
            instrument_key=None,
        )
        order_entry.order_type = order_type
        order_entry.quantity = quantity
        order_entry.price = price
        order_entry.trigger_price = trigger_price
        self.db.add(order_entry)
        self.db.commit()

        await self._create_order_event(order_entry, OrderEvent.ORDER_PLACED)

        # Enqueue the task
        process_order_task.delay(order_entry.__dict__, organization_id)

        return {"message": f"Modify order request submitted for platform_id: {platform_id}"}

    async def square_off_position(
        self,
        pseudo_account: str,
        position_category: str,
        position_type: str,
        exchange: str,
        symbol: str,
        organization_id: str = None,
        background_tasks: BackgroundTasks = None,
    ):
        if not self.rate_limiter.user_rate_limit(pseudo_account, organization_id) or not self.rate_limiter.account_rate_limit(pseudo_account, organization_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        instrument_key = f"{exchange}@{symbol}@@@"
        # Create a dummy OrderModel for asynchronous processing
        order_entry = OrderModel(
            pseudo_account=pseudo_account,
            variety="SQUARE_OFF_POSITION",
            instrument_key=instrument_key,
        )
        order_entry.position_category = position_category
        order_entry.position_type = position_type
        order_entry.exchange = exchange
        order_entry.symbol = symbol
        self.db.add(order_entry)
        self.db.commit()

        await self._create_order_event(order_entry, OrderEvent.ORDER_PLACED)

        # Enqueue the task
        process_order_task.delay(order_entry.__dict__, organization_id)

        return {"message": f"Square off position request submitted"}

    async def square_off_portfolio(
        self,
        pseudo_account: str,
        position_category: str,
        organization_id: str = None,
        background_tasks: BackgroundTasks = None,
    ):
        if not self.rate_limiter.user_rate_limit(pseudo_account, organization_id) or not self.rate_limiter.account_rate_limit(pseudo_account, organization_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        # Create a dummy OrderModel for asynchronous processing
        order_entry = OrderModel(
            pseudo_account=pseudo_account,
            variety="SQUARE_OFF_PORTFOLIO",
            instrument_key=None,
        )
        order_entry.position_category = position_category
        self.db.add(order_entry)
        self.db.commit()

        await self._create_order_event(order_entry, OrderEvent.ORDER_PLACED)

        # Enqueue the task
        process_order_task.delay(order_entry.__dict__, organization_id)

        return {"message": f"Square off portfolio request submitted"}

    async def cancel_all_orders(
        self,
        pseudo_account: str,
        organization_id: str = None,
        background_tasks: BackgroundTasks = None,
    ):
        if not self.rate_limiter.user_rate_limit(pseudo_account, organization_id) or not self.rate_limiter.account_rate_limit(pseudo_account, organization_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        # Create a dummy OrderModel for asynchronous processing
        order_entry = OrderModel(
            pseudo_account=pseudo_account,
            variety="CANCEL_ALL_ORDERS",
            instrument_key=None,
        )
        self.db.add(order_entry)
        self.db.commit()

        await self._create_order_event(order_entry, OrderEvent.ORDER_PLACED)

        # Enqueue the task
        process_order_task.delay(order_entry.__dict__, organization_id)

        return {"message": f"Cancel all orders request submitted"}

    async def get_trade_status(self, order_id: str, organization_id: str):
        if not self.rate_limiter.user_rate_limit(order_id, organization_id) or not self.rate_limiter.account_rate_limit(order_id, organization_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        # StocksDeveloper API call to get order status
        cached_status = self.redis_conn.get(f"name:{pseudo_account}:order_status:{order_id}")
        if cached_status:
            return pickle.loads(cached_status)

        api_key = await self._get_api_key(organization_id)
        stocksdeveloper_conn = AutoTrader.create_instance(api_key, AutoTrader.SERVER_URL)
        order_status = stocksdeveloper_conn.get_order_status(order_id=order_id)

        self.redis_conn.set(f"name:{pseudo_account}:order_status:{order_id}", pickle.dumps(order_status), ex=300)

        return order_status

    async def fetch_and_store_data(self, pseudo_acc: str, organization_id: str):
        if not self.rate_limiter.account_rate_limit(pseudo_acc, organization_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        api_key = await self._get_api_key(organization_id)
        stocksdeveloper_conn = AutoTrader.create_instance(api_key, AutoTrader.SERVER_URL)

        # Fetch and store margins
        margins = stocksdeveloper_conn.read_platform_margins(pseudo_account=pseudo_acc)
        for margin in margins:
            instrument_key = f"{margin.get('exchange', '')}@{margin.get('symbol', '')}@@@"
            margin_entry = MarginModel(**margin, pseudo_account=pseudo_acc, margin_date=datetime.utcnow(), instrument_key=instrument_key)
            self.db.add(margin_entry)
            self.redis_conn.set(f"name:{pseudo_acc}:margin:{margin['category']}", pickle.dumps(MarginSchema.from_orm(margin_entry)), ex=300)

        # Fetch and store positions
        positions = stocksdeveloper_conn.read_platform_positions(pseudo_account=pseudo_acc)
        for position in positions:
            instrument_key = f"{position.get('exchange', '')}@{position.get('symbol', '')}@@@"
            position_entry = PositionModel(**position, pseudo_account=pseudo_acc, instrument_key=instrument_key)
            self.db.add(position_entry)
            self.redis_conn.set(f"name:{pseudo_acc}:position:{position['symbol']}", pickle.dumps(PositionSchema.from_orm(position_entry)), ex=300)

        # Fetch and store holdings
        holdings = stocksdeveloper_conn.read_platform_holdings(pseudo_account=pseudo_acc)
        for holding in holdings:
            instrument_key = f"{holding.get('exchange', '')}@{holding.get('symbol', '')}@@@"
            holding_entry = HoldingModel(**holding, pseudo_account=pseudo_acc, instrument_key=instrument_key)
            self.db.add(holding_entry)
            self.redis_conn.set(f"name:{pseudo_acc}:holding:{holding['symbol']}", pickle.dumps(HoldingSchema.from_orm(holding_entry)), ex=300)

        # Fetch and store orders
        orders = stocksdeveloper_conn.read_platform_orders(pseudo_account=pseudo_acc)
        for order in orders:
            instrument_key = f"{order.get('exchange', '')}@{order.get('symbol', '')}@@@"
            order_entry = OrderModel(**order, pseudo_account=pseudo_acc, instrument_key=instrument_key)
            self.db.add(order_entry)
            self.redis_conn.set(f"name:{pseudo_acc}:order:{order['id']}", pickle.dumps(OrderSchema.from_orm(order_entry)), ex=300)

        self.db.commit()

    async def fetch_all_trading_accounts(self, organization_id: str):
        if not self.rate_limiter.account_rate_limit("fetchAllTradingAccounts", organization_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        api_key = await self._get_api_key(organization_id)
        headers = {"api-key": api_key}
        url = "https://apix.stocksdeveloper.in/account/fetchAllTradingAccounts"
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            trading_accounts_data = response.json()
            return trading_accounts_data
        except requests.exceptions.RequestException as e:
            raise HTTPException(status_code=500, detail=str(e))
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=500, detail=str(e))

    async def _check_for_conflicting_orders(self, pseudo_account: str, instrument_key: str, trade_type: str, strategy_id: str):
        """
        Checks for conflicting orders/positions/holdings on the same instrument.
        """
        existing_positions = self.db.query(PositionModel).filter_by(pseudo_account=pseudo_account, instrument_key=instrument_key).all()
        existing_orders = self.db.query(OrderModel).filter_by(pseudo_account=pseudo_account, instrument_key=instrument_key).filter(OrderModel.status.in_(['PENDING', 'PARTIALLY_FILLED'])).all()
        existing_holdings = self.db.query(HoldingModel).filter_by(pseudo_account=pseudo_account, instrument_key=instrument_key).all()

        for position in existing_positions:
            if position.strategy_id != strategy_id:
                if trade_type == "BUY" and position.direction == "SELL":
                    raise HTTPException(status_code=409, detail=f"Conflict: Cannot place BUY order when SELL position exists from another strategy ({position.strategy_id})")
                elif trade_type == "SELL" and position.direction == "BUY":
                    raise HTTPException(status_code=409, detail=f"Conflict: Cannot place SELL order when BUY position exists from another strategy ({position.strategy_id})")

        for order in existing_orders:
            if order.strategy_id != strategy_id:
                if trade_type == "BUY" and order.trade_type == "SELL":
                    raise HTTPException(status_code=409, detail=f"Conflict: Cannot place BUY order when SELL order exists from another strategy ({order.strategy_id})")
                elif trade_type == "SELL" and order.trade_type == "BUY":
                    raise HTTPException(status_code=409, detail=f"Conflict: Cannot place SELL order when BUY order exists from another strategy ({order.strategy_id})")

        for holding in existing_holdings:
            if holding.strategy_id != strategy_id:
                if trade_type == "BUY" and holding.quantity < 0:
                    raise HTTPException(status_code=409, detail=f"Conflict: Cannot place BUY order when SELL holding exists from another strategy ({holding.strategy_id})")
                elif trade_type == "SELL" and holding.quantity > 0:
                    raise HTTPException(status_code=409, detail=f"Conflict: Cannot place SELL order when BUY holding exists from another strategy ({holding.strategy_id})")

    async def _handle_holding_to_position_transition(
        self,
        pseudo_account: str,
        instrument_key: str,
        quantity: int,
        strategy_id: str,
    ):
        """
        Handles the transition of holdings to positions when a sell order is placed.
        """
        existing_holding = self.db.query(HoldingModel).filter_by(
            pseudo_account=pseudo_account,
            instrument_key=instrument_key,
            strategy_id=strategy_id
        ).first()

        if not existing_holding:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient holdings for {instrument_key} for strategy {strategy_id}",
            )

        if existing_holding.quantity < quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient holdings for {instrument_key} for strategy {strategy_id}",
            )

        existing_holding.quantity -= quantity
        new_position = PositionModel(
            pseudo_account=pseudo_account,
            instrument_key=instrument_key,
            strategy_id=strategy_id,
            source_strategy_id=strategy_id,
            net_quantity=-quantity,
            sell_quantity=quantity,
            direction="SELL"
        )
        self.db.add(new_position)
        self.db.commit()

    async def _update_positions_and_holdings(self, order: OrderModel):
        """
        Updates positions and holdings based on order execution.
        This is the most complex logic.
        """

        if order.status not in ["COMPLETE", "PARTIALLY_FILLED"]:
            return  # Only update on completed/partially filled orders

        quantity_filled = order.filled_quantity if order.filled_quantity else order.quantity

        if quantity_filled == 0:
            return

        instrument_key = order.instrument_key
        pseudo_account = order.pseudo_account
        strategy_id = order.strategy_id
        trade_type = order.trade_type

        # 1. Update/Create Position
        existing_position = self.db.query(PositionModel).filter_by(
            pseudo_account=pseudo_account,
            instrument_key=instrument_key,
            strategy_id=strategy_id
        ).first()

        if existing_position:
            if trade_type == "BUY":
                existing_position.net_quantity += quantity_filled
                existing_position.buy_quantity += quantity_filled
                existing_position.buy_value += order.price * quantity_filled
                existing_position.buy_avg_price = existing_position.buy_value / existing_position.buy_quantity if existing_position.buy_quantity else 0
                existing_position.direction = "BUY"
            elif trade_type == "SELL":
                existing_position.net_quantity -= quantity_filled
                existing_position.sell_quantity += quantity_filled
                existing_position.sell_value += order.price * quantity_filled
                existing_position.sell_avg_price = existing_position.sell_value / existing_position.sell_quantity if existing_position.sell_quantity else 0
                existing_position.direction = "SELL"
        else:
            if trade_type == "BUY":
                new_position = PositionModel(
                    pseudo_account=pseudo_account,
                    instrument_key=instrument_key,
                    strategy_id=strategy_id,
                    net_quantity=quantity_filled,
                    buy_quantity=quantity_filled,
                    buy_value=order.price * quantity_filled,
                    buy_avg_price=order.price,
                    direction="BUY"
                )
            elif trade_type == "SELL":
                new_position = PositionModel(
                    pseudo_account=pseudo_account,
                    instrument_key=instrument_key,
                    strategy_id=strategy_id,
                    net_quantity=-quantity_filled,
                    sell_quantity=quantity_filled,
                    sell_value=order.price * quantity_filled,
                    sell_avg_price=order.price,
                    direction="SELL"
                )
            self.db.add(new_position)

        # 2. Handle Position to Holding Transition
        if order.product_type not in ["OPTIONS", "FUTURES"]:  # Equity logic
            if datetime.now().hour >= 15:  # After market close (adjust as needed)
                existing_holding = self.db.query(HoldingModel).filter_by(
                    pseudo_account=pseudo_account,
                    instrument_key=instrument_key,
                    strategy_id=strategy_id
                ).first()

                if existing_holding:
                    existing_holding.quantity += existing_position.net_quantity
                else:
                    new_holding = HoldingModel(
                        pseudo_account=pseudo_account,
                        instrument_key=instrument_key,
                        strategy_id=strategy_id,
                        quantity=existing_position.net_quantity,
                        product=order.product_type
                    )
                    self.db.add(new_holding)

                self.db.delete(existing_position)  # delete the position record
                order.transition_type = OrderTransitionType.POSITION_TO_HOLDING

        self.db.commit()

    async def get_organization_id_from_name(self, organization_name: str) -> str:
        """
        Retrieves the organization ID from the organization name.
        This is a placeholder - replace with your actual logic to fetch this from the user service or wherever you store organization data.
        """
        # Placeholder logic - replace with your actual implementation
        # For example, you might call the user service:
        user_service_url = settings.user_service_url
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{user_service_url}/organizations/{organization_name}")
            response.raise_for_status()
            organization_data = response.json()
            return organization_data["id"]
        # Or you might have a local mapping:
        # organization_mapping = {"Org A": "org_a_id", "Org B": "org_b_id"}
        # return organization_mapping.get(organization_name)
        # If not found, raise an exception:
        # raise ValueError(f"Organization not found: {organization_name}")
        pass

    async def get_orders_by_organization_and_user(self, user_id: str) -> List[OrderSchema]:
        try:
            organization_name = await self._get_organization_name_for_user(user_id)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

        if not self.rate_limiter.account_rate_limit(user_id, organization_name):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        orders = self.db.query(OrderModel).filter_by(pseudo_account=user_id).all()
        return [OrderSchema.from_orm(order) for order in orders]

    async def get_positions_by_organization_and_user(self, user_id: str) -> List[PositionSchema]:
        try:
            organization_name = await self._get_organization_name_for_user(user_id)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

        if not self.rate_limiter.account_rate_limit(user_id, organization_name):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        positions = self.db.query(PositionModel).filter_by(pseudo_account=user_id).all()
        return [PositionSchema.from_orm(position) for position in positions]

    async def get_holdings_by_organization_and_user(self, user_id: str) -> List[HoldingSchema]:
        try:
            organization_name = await self._get_organization_name_for_user(user_id)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

        if not self.rate_limiter.account_rate_limit(user_id, organization_name):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        holdings = self.db.query(HoldingModel).filter_by(pseudo_account=user_id).all()
        return [HoldingSchema.from_orm(holding) for holding in holdings]

    async def get_margins_by_organization_and_user(self, user_id: str) -> List[MarginSchema]:
        try:
            organization_name = await self._get_organization_name_for_user(user_id)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

        if not self.rate_limiter.account_rate_limit(user_id, organization_name):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        margins = self.db.query(MarginModel).filter_by(pseudo_account=user_id).all()
        return [MarginSchema.from_orm(margin) for margin in margins]

    async def get_orders_by_strategy(self, strategy_name: str) -> List[OrderSchema]:
        orders = self.db.query(OrderModel).filter_by(strategy_id=strategy_name).all()
        return [OrderSchema.from_orm(order) for order in orders]

    async def get_positions_by_strategy(self, strategy_name: str) -> List[PositionSchema]:
        positions = self.db.query(PositionModel).filter_by(strategy_id=strategy_name).all()
        return [PositionSchema.from_orm(position) for position in positions]

    async def get_holdings_by_strategy(self, strategy_name: str) -> List[HoldingSchema]:
        holdings = self.db.query(HoldingModel).filter_by(strategy_id=strategy_name).all()
        return [HoldingSchema.from_orm(holding) for holding in holdings]

    async def get_api_key(self, organization_id: str) -> str:
        """
        Celery task to retrieve the API key for a given organization, with caching.
        """
        redis_conn = connection_manager.get_redis_connection()
        cached_key = redis_conn.get(f"api_key:{organization_id}")
        if cached_key:
            return cached_key.decode("utf-8")

        # Call user service to get the API key
        user_service_url = settings.user_service_url
        try:
            response = requests.get(f"{user_service_url}/api_key/{organization_id}")
            response.raise_for_status()
            api_key = response.json()["api_key"]
            redis_conn.set(f"api_key:{organization_id}", api_key.encode("utf-8"), ex=3600)
            return api_key
        except Exception as e:
            print(f"Error getting API key: {e}")
            raise e
        finally:
            redis_conn.close()