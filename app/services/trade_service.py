import json
from typing import Optional,List

import httpx
from fastapi import HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from datetime import datetime
import pickle
import requests

from shared_architecture.connections.connection_manager import connection_manager
from shared_architecture.db.models.broker import Broker
from shared_architecture.db.models.order_model import OrderModel
from shared_architecture.db.models.margin_model import MarginModel
from shared_architecture.db.models.position_model import PositionModel
from shared_architecture.db.models.holding_model import HoldingModel
from shared_architecture.schemas.margin_schema import MarginSchema
from shared_architecture.schemas.position_schema import PositionSchema
from shared_architecture.schemas.holding_schema import HoldingSchema
from shared_architecture.schemas.order_schema import OrderSchema
from shared_architecture.schemas.trade_schemas import TradeOrder

from app.core.config import settings
from app.utils.rate_limiter import RateLimiter
from app.tasks.update_order_status import update_order_status_task as celery_update_order_status_task
from app.tasks.update_positions_and_holdings_task import update_positions_and_holdings_task
from app.tasks.create_order_event import create_order_event_task
from app.tasks.process_order_task import process_order_task
from shared_architecture.enums import OrderEvent,OrderTransitionType
from typing import cast
# Add AutoTrader import - adjust based on your actual package
try:
    from com.dakshata.autotrader.api import AutoTrader
except ImportError:
    # Mock AutoTrader if not available
    class AutoTraderResponse:
        def __init__(self, success=False, result=None, message="Mock response"):
            self._success = success
            self.result = result or []
            self.message = message
        
        def success(self):
            return self._success
    
    class AutoTrader:
        @staticmethod
        def create_instance(api_key, server_url):
            return AutoTraderMock()
        SERVER_URL = "mock_url"
    
    class AutoTraderMock:
        def read_platform_margins(self, pseudo_account=None):
            return AutoTraderResponse(success=False, result=[], message="Mock: AutoTrader not available")
        
        def read_platform_positions(self, pseudo_account=None):
            return AutoTraderResponse(success=False, result=[], message="Mock: AutoTrader not available")
        
        def read_platform_holdings(self, pseudo_account=None):
            return AutoTraderResponse(success=False, result=[], message="Mock: AutoTrader not available")
        
        def read_platform_orders(self, pseudo_account=None):
            return AutoTraderResponse(success=False, result=[], message="Mock: AutoTrader not available")
class TradeService:
    def __init__(self, db: Session):
        self.db = db
        self.account: Optional[str] = None
        self.token: Optional[str] = None
        self.timescaledb_conn = connection_manager.get_sync_timescaledb_session() # Or self.db directly if preferred
        # Fix Redis connection type issue
        self.redis_conn = connection_manager.get_redis_connection()  # type: ignore
        self.rabbitmq_conn = connection_manager.get_rabbitmq_connection() # For any direct synchronous publishes
        self.rate_limiter = RateLimiter(self.redis_conn)  # type: ignore   
        self.stocksdeveloper_conn=None
    def set_credentials(self, account: str, token: str):
        self.account = account
        self.token = token

    def _call_api(self, endpoint: str, payload: dict, method: str = "POST") -> dict:
        url = f"{settings.trade_api_url}/{endpoint}"
        headers = {"Authorization": f"Bearer {self.token}"}

        response = httpx.request(method, url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()

    def place_order(self, order: OrderModel):
        payload = {
            "account": self.account,
            "symbol": order.symbol,
            "quantity": order.quantity,
            "order_type": order.order_type,
            "price": order.price,
            "side": order.side,
        }
        result = self._call_api("orders/place", payload)
        # Cast to int to help Pylance recognize it's not Column[int]
        self._handle_response(cast(int, order.id), result)

    def modify_order(self, order: OrderModel):
        payload = {
            "account": self.account,
            "order_id": order.exchange_order_id,
            "quantity": order.quantity,
            "price": order.price,
        }
        result = self._call_api("orders/modify", payload)
        # Cast to int to help Pylance recognize it's not Column[int]
        self._handle_response(cast(int, order.id), result)

    def cancel_order(self, order: OrderModel):
        payload = {
            "account": self.account,
            "order_id": order.exchange_order_id,
        }
        result = self._call_api("orders/cancel", payload)
        # Cast to int to help Pylance recognize it's not Column[int]
        self._handle_response(cast(int, order.id), result)

    def _handle_response(self, order_id: int, response: dict):
        """
        Handle the API response by delegating to the Celery update task.
        """
        celery_update_order_status_task.apply_async(args=[order_id, response]) # type: ignore

    def sync_order_status(self, order: OrderModel):
        payload = {
            "account": self.account,
            "order_id": order.exchange_order_id,
        }
        result = self._call_api("orders/status", payload)

        # Cast to int to help Pylance recognize it's not Column[int]
        self._handle_response(cast(int, order.id), result)

    async def fetch_and_store_data(self, pseudo_acc: str, organization_id: str):
        """Fetches and stores various datasets (margins, positions, holdings, orders) for a user."""
        if not self.rate_limiter.account_rate_limit(pseudo_acc, organization_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        api_key = await self.get_api_key(organization_id)
        stocksdeveloper_conn = AutoTrader.create_instance(api_key, AutoTrader.SERVER_URL)

        # Check if stocksdeveloper_conn is None (mock case)
        if stocksdeveloper_conn is None:
            print(f"AutoTrader connection failed for organization {organization_id}")
            return

        # Fetch and store margins
        # Fetch and store margins
        margins_response = stocksdeveloper_conn.read_platform_margins(pseudo_account=pseudo_acc)  # type: ignore
        if margins_response.success():
            # Ensure result is iterable
            margin_results = margins_response.result
            if margin_results and hasattr(margin_results, '__iter__'):
                for margin in margin_results:
                    # Construct instrument_key (if available/applicable for margins)
                    # This might need adjustment based on actual margin data structure
                    instrument_key = f"{margin.get('exchange', '')}@{margin.get('symbol', '')}@{margin.get('productType', '')}@{margin.get('expiry_date', '')}@{margin.get('option_type', '')}@{margin.get('strike_price', '')}"
                    margin_entry = MarginModel(**margin, pseudo_account=pseudo_acc, margin_date=datetime.utcnow(), instrument_key=instrument_key)
                    self.db.add(margin_entry)
                    margin_data = pickle.dumps(MarginSchema.from_orm(margin_entry))
                    await self.redis_conn.set(f"org:{organization_id}:margin:{pseudo_acc}:{margin['category']}", margin_data, ex=300)
            else:
                print(f"Margins result is not iterable for {pseudo_acc}: {margin_results}")
        else:
            print(f"Failed to fetch margins for {pseudo_acc}: {margins_response.message}")

        # Fetch and store positions
        positions_response = stocksdeveloper_conn.read_platform_positions(pseudo_account=pseudo_acc)  # type: ignore
        if positions_response.success():
            # Ensure result is iterable
            position_results = positions_response.result
            if position_results and hasattr(position_results, '__iter__'):
                for position in position_results:
                    # Construct instrument_key from position data
                    instrument_key = f"{position.get('exchange', '')}@{position.get('symbol', '')}@{position.get('type', '')}@{position.get('expiry', '')}@{position.get('option_type', '')}@{position.get('strike_price', '')}"
                    position_entry = PositionModel(**position, pseudo_account=pseudo_acc, instrument_key=instrument_key)
                    self.db.add(position_entry)
                    position_data = pickle.dumps(PositionSchema.from_orm(position_entry))
                    await self.redis_conn.set(f"org:{organization_id}:position:{pseudo_acc}:{position['symbol']}", position_data, ex=300)
            else:
                print(f"Positions result is not iterable for {pseudo_acc}: {position_results}")
        else:
            print(f"Failed to fetch positions for {pseudo_acc}: {positions_response.message}")


        # Fetch and store holdings
        holdings_response = stocksdeveloper_conn.read_platform_holdings(pseudo_account=pseudo_acc)  # type: ignore
        if holdings_response.success():
            # Ensure result is iterable
            holding_results = holdings_response.result
            if holding_results and hasattr(holding_results, '__iter__'):
                for holding in holding_results:
                    # Construct instrument_key from holding data
                    instrument_key = f"{holding.get('exchange', '')}@{holding.get('symbol', '')}@{holding.get('product', '')}@{holding.get('expiry', '')}@{holding.get('option_type', '')}@{holding.get('strike_price', '')}"
                    holding_entry = HoldingModel(**holding, pseudo_account=pseudo_acc, instrument_key=instrument_key)
                    self.db.add(holding_entry)
                    holding_data = pickle.dumps(HoldingSchema.from_orm(holding_entry))
                    await self.redis_conn.set(f"org:{organization_id}:holding:{pseudo_acc}:{holding['symbol']}", holding_data, ex=300)
            else:
                print(f"Holdings result is not iterable for {pseudo_acc}: {holding_results}")
        else:
            print(f"Failed to fetch holdings for {pseudo_acc}: {holdings_response.message}")

        # Fetch and store orders
        orders_response = stocksdeveloper_conn.read_platform_orders(pseudo_account=pseudo_acc)  # type: ignore
        if orders_response.success():
            # Ensure result is iterable
            order_results = orders_response.result
            if order_results and hasattr(order_results, '__iter__'):
                for order_data in order_results:
                    # Construct instrument_key from order data
                    instrument_key = f"{order_data.get('exchange', '')}@{order_data.get('symbol', '')}@{order_data.get('productType', '')}@{order_data.get('expiry', '')}@{order_data.get('option_type', '')}@{order_data.get('strike_price', '')}"
                    # Ensure datetime objects are handled correctly from API response (string to datetime)
                    if 'exchange_time' in order_data and isinstance(order_data['exchange_time'], str):
                        try:
                            order_data['exchange_time'] = datetime.fromisoformat(order_data['exchange_time'].replace('Z', '+00:00')) # Handle ISO format
                        except ValueError:
                            pass # Handle if format is different
                    if 'platform_time' in order_data and isinstance(order_data['platform_time'], str):
                        try:
                            order_data['platform_time'] = datetime.fromisoformat(order_data['platform_time'].replace('Z', '+00:00'))
                        except ValueError:
                            pass
                    if 'modified_time' in order_data and isinstance(order_data['modified_time'], str):
                        try:
                            order_data['modified_time'] = datetime.fromisoformat(order_data['modified_time'].replace('Z', '+00:00'))
                        except ValueError:
                            pass

                    # Assuming order_data dict keys match OrderModel columns
                    order_entry = OrderModel(**order_data, pseudo_account=pseudo_acc, instrument_key=instrument_key)
                    self.db.add(order_entry)
                    order_data_pickled = pickle.dumps(OrderSchema.from_orm(order_entry))
                    await self.redis_conn.set(f"org:{organization_id}:order:{pseudo_acc}:{order_data['id']}", order_data_pickled, ex=300)
            else:
                print(f"Orders result is not iterable for {pseudo_acc}: {order_results}")
        else:
            print(f"Failed to fetch orders for {pseudo_acc}: {orders_response.message}")

        self.db.commit()

    async def _create_order_event(self, order: OrderModel, event_type: OrderEvent, details: Optional[str] = None):
        """
        Triggers a Celery task to create and store an OrderEvent.
        """
        # Use send_task instead of apply_async for consistency
        from app.core.celery_config import celery_app
        celery_app.send_task('create_order_event_task', args=[order.id, event_type.value, details])


    async def _get_organization_name_for_user(self, user_id: str) -> str:
        """
        Retrieves the organization name for a user from Redis cache.
        """
        organization_name = await self.redis_conn.get(f"user:{user_id}:organization")
        if organization_name:
            return organization_name.decode("utf-8")
        else:
            raise ValueError(f"Organization name not found for user: {user_id}")

    async def _check_for_conflicting_orders(self, pseudo_account: str, instrument_key: str, trade_type: str, strategy_id: str):
        """
        Checks for conflicting orders/positions/holdings on the same instrument by other strategies.
        Raises HTTPException (409 Conflict) if a conflict is detected.
        """
        existing_positions = self.db.query(PositionModel).filter_by(pseudo_account=pseudo_account, instrument_key=instrument_key).all()
        existing_orders = self.db.query(OrderModel).filter_by(pseudo_account=pseudo_account, instrument_key=instrument_key).filter(OrderModel.status.in_(['PENDING', 'PARTIALLY_FILLED'])).all()
        existing_holdings = self.db.query(HoldingModel).filter_by(pseudo_account=pseudo_account, instrument_key=instrument_key).all()

        for position in existing_positions:
            if position.strategy_id != strategy_id:  # type: ignore
                if trade_type == "BUY" and position.direction == "SELL":  # type: ignore
                    raise HTTPException(status_code=409, detail=f"Conflict: Cannot place BUY order when SELL position exists from another strategy ({position.strategy_id}) on {instrument_key}")  # type: ignore
                elif trade_type == "SELL" and position.direction == "BUY":  # type: ignore
                    raise HTTPException(status_code=409, detail=f"Conflict: Cannot place SELL order when BUY position exists from another strategy ({position.strategy_id}) on {instrument_key}")  # type: ignore

        for order_in_db in existing_orders:
            if order_in_db.strategy_id != strategy_id:  # type: ignore
                if trade_type == "BUY" and order_in_db.trade_type == "SELL":  # type: ignore
                    raise HTTPException(status_code=409, detail=f"Conflict: Cannot place BUY order when SELL order exists from another strategy ({order_in_db.strategy_id}) on {instrument_key}")  # type: ignore
                elif trade_type == "SELL" and order_in_db.trade_type == "BUY":  # type: ignore
                    raise HTTPException(status_code=409, detail=f"Conflict: Cannot place SELL order when BUY order exists from another strategy ({order_in_db.strategy_id}) on {instrument_key}")  # type: ignore

        for holding in existing_holdings:
            if holding.strategy_id != strategy_id:  # type: ignore
                if trade_type == "BUY" and holding.quantity < 0:  # type: ignore
                    raise HTTPException(status_code=409, detail=f"Conflict: Cannot place BUY order when SELL holding exists from another strategy ({holding.strategy_id}) on {instrument_key}")  # type: ignore
                elif trade_type == "SELL" and holding.quantity > 0:  # type: ignore
                    raise HTTPException(status_code=409, detail=f"Conflict: Cannot place SELL order when BUY holding exists from another strategy ({holding.strategy_id}) on {instrument_key}")  # type: ignore

    async def _handle_holding_to_position_transition(
        self,
        pseudo_account: str,
        instrument_key: str,
        quantity: int,
        strategy_id: str,
    ):
        """
        Handles the intraday transition of holdings to positions when a sell order is placed.
        Reduces holding quantity and creates a temporary position for the sell.
        """
        existing_holding = self.db.query(HoldingModel).filter_by(
            pseudo_account=pseudo_account,
            instrument_key=instrument_key,
            strategy_id=strategy_id
        ).first()

        if not existing_holding:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient holdings for {instrument_key} for strategy {strategy_id}. No matching holding found."
            )

        if existing_holding.quantity < quantity:  # type: ignore
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient holdings for {instrument_key} for strategy {strategy_id}. Available: {existing_holding.quantity}, Requested: {quantity}."
            )

        existing_holding.quantity -= quantity  # type: ignore
        self.db.add(existing_holding)

        new_position = PositionModel(
            pseudo_account=pseudo_account,
            instrument_key=instrument_key,
            strategy_id=strategy_id,
            source_strategy_id=strategy_id,
            net_quantity=-quantity,
            sell_quantity=quantity,
            direction="SELL",
            timestamp=datetime.utcnow(),
            account_id=pseudo_account,
            exchange=instrument_key.split('@')[0],
            symbol=instrument_key.split('@')[1],
            atPnl=0.0, mtm=0.0, multiplier=1, net_value=0.0, overnight_quantity=0,
            platform='StocksDeveloper', pnl=0.0, realised_pnl=0.0, type='INTRADAY', unrealised_pnl=0.0,
            state='OPEN'
        )
        self.db.add(new_position)
        self.db.commit()

    async def _update_positions_and_holdings(self, order: OrderModel):
        """
        Updates positions and holdings based on order execution status (COMPLETE/PARTIALLY_FILLED).
        This function is designed to be called by a Celery task, so it receives a detached SQLAlchemy object.
        """
        if order.status not in ["COMPLETE", "PARTIALLY_FILLED"]:  # type: ignore
            print(f"Order {order.id} status is {order.status}. Skipping position/holding update.")
            return

        quantity_impact = order.filled_quantity if order.filled_quantity is not None else order.quantity  # type: ignore
        if quantity_impact == 0:  # type: ignore
            return

        instrument_key = order.instrument_key
        pseudo_account = order.pseudo_account
        strategy_id = order.strategy_id
        trade_type = order.trade_type
        signed_quantity_impact = quantity_impact if trade_type == "BUY" else -quantity_impact  # type: ignore

        existing_position = self.db.query(PositionModel).filter_by(
            pseudo_account=pseudo_account,
            instrument_key=instrument_key,
            strategy_id=strategy_id
        ).first()

        if existing_position:
            existing_position.net_quantity += signed_quantity_impact  # type: ignore
            if trade_type == "BUY":  # type: ignore
                existing_position.buy_quantity = (existing_position.buy_quantity or 0) + quantity_impact  # type: ignore
                existing_position.buy_value = (existing_position.buy_value or 0) + (order.price * quantity_impact)  # type: ignore
                existing_position.buy_avg_price = existing_position.buy_value / existing_position.buy_quantity if existing_position.buy_quantity else 0  # type: ignore
            else:
                existing_position.sell_quantity = (existing_position.sell_quantity or 0) + quantity_impact  # type: ignore
                existing_position.sell_value = (existing_position.sell_value or 0) + (order.price * quantity_impact)  # type: ignore
                existing_position.sell_avg_price = existing_position.sell_value / existing_position.sell_quantity if existing_position.sell_quantity else 0  # type: ignore
            
            if existing_position.net_quantity > 0:  # type: ignore
                existing_position.direction = "BUY"  # type: ignore
            elif existing_position.net_quantity < 0:  # type: ignore
                existing_position.direction = "SELL"  # type: ignore
            else:
                existing_position.direction = "NONE"  # type: ignore
            
            existing_position.timestamp = datetime.utcnow()  # type: ignore

        else:
            new_position = PositionModel(
                pseudo_account=pseudo_account,
                instrument_key=instrument_key,
                strategy_id=strategy_id,
                net_quantity=signed_quantity_impact,
                buy_quantity=quantity_impact if trade_type == "BUY" else 0,  # type: ignore
                sell_quantity=quantity_impact if trade_type == "SELL" else 0,  # type: ignore
                buy_value=order.price * quantity_impact if trade_type == "BUY" else 0,  # type: ignore
                sell_value=order.price * quantity_impact if trade_type == "SELL" else 0,  # type: ignore
                buy_avg_price=order.price if trade_type == "BUY" else 0,  # type: ignore
                sell_avg_price=order.price if trade_type == "SELL" else 0,  # type: ignore
                direction=trade_type,
                timestamp=datetime.utcnow(),
                account_id=pseudo_account,
                exchange=order.exchange,
                symbol=order.symbol,
                platform='StocksDeveloper', pnl=0.0, realised_pnl=0.0, unrealised_pnl=0.0,
                state='OPEN',
                category="INTRADAY",
                type=order.product_type,
                ltp=0.0, mtm=0.0, multiplier=1, net_value=0.0, overnight_quantity=0, stock_broker="StocksDeveloper", trading_account=pseudo_account
            )
            self.db.add(new_position)

        self.db.commit()

    async def get_organization_id_from_name(self, organization_name: str) -> str:
        """
        Retrieves the organization ID from the organization name using the User Service.
        """
        user_service_url = settings.user_service_url
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{user_service_url}/organizations/by_name/{organization_name}")
                response.raise_for_status()
                organization_data = response.json()
                if "id" not in organization_data:
                    raise ValueError(f"User Service response for organization '{organization_name}' missing 'id'. Response: {organization_data}")
                return organization_data["id"]
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise ValueError(f"Organization '{organization_name}' not found via User Service.")
            print(f"HTTP Error fetching organization ID for '{organization_name}': {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            print(f"Error fetching organization ID for '{organization_name}': {e}")
            raise

    # --- API Endpoints for Order Actions (FastAPI facing) ---

    async def execute_trade_order(
        self,
        trade_order: TradeOrder,
        organization_id: str,
        background_tasks: Optional[BackgroundTasks] = None,
    ):
        """
        Receives a trade order, performs checks, persists it, and enqueues it for asynchronous processing.
        This is a generic entry point for different order types via a unified TradeOrder schema.
        """
        if not self.rate_limiter.user_rate_limit(trade_order.user_id, organization_id) or \
           not self.rate_limiter.account_rate_limit(trade_order.user_id, organization_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        # Construct instrument_key (assuming TradeOrder includes necessary attributes)
        exchange_val = getattr(trade_order, 'exchange', None)
        product_type_val = getattr(trade_order, 'product_type', None)
        if exchange_val and product_type_val:
            instrument_key = f"{exchange_val.value}@{trade_order.symbol}@{product_type_val.value}@{getattr(trade_order, 'expiry_date', '')}@{getattr(trade_order, 'option_type', '')}@{getattr(trade_order, 'strike_price', '')}"
        else:
            raise HTTPException(status_code=400, detail="Missing required fields: exchange or product_type")

        strategy_id = getattr(trade_order, 'strategy_id', None)
        if not strategy_id:
             raise HTTPException(status_code=400, detail="Strategy ID is required for trade order execution.")
        
        side_val = getattr(trade_order, 'side', None)
        if not side_val:
            raise HTTPException(status_code=400, detail="Side is required for trade order execution.")
            
        await self._check_for_conflicting_orders(trade_order.user_id, instrument_key, side_val.value, strategy_id)

        if side_val.value == "SELL":
            await self._handle_holding_to_position_transition(trade_order.user_id, instrument_key, trade_order.quantity, strategy_id)

        # Create OrderModel instance from TradeOrder schema
        order_type_val = getattr(trade_order, 'order_type', None)
        variety_val = getattr(trade_order, 'variety', None)
        
        order_entry = OrderModel(
            pseudo_account=trade_order.user_id,
            exchange=exchange_val.value if exchange_val else "",
            symbol=trade_order.symbol,
            trade_type=side_val.value if side_val else "",
            order_type=order_type_val.value if order_type_val else "",
            product_type=product_type_val.value if product_type_val else "",
            quantity=trade_order.quantity,
            price=trade_order.price,
            trigger_price=getattr(trade_order, 'trigger_price', 0.0),
            strategy_id=strategy_id,
            instrument_key=instrument_key,
            status="NEW", # Initial status before broker interaction
            platform_time=datetime.utcnow(),
            transition_type=OrderTransitionType.HOLDING_TO_POSITION if side_val.value == "SELL" else OrderTransitionType.NONE,
            variety=variety_val.value if variety_val else ""
        )
        # Populate optional fields
        for field in ['target', 'stoploss', 'trailing_stoploss', 'disclosed_quantity', 'validity', 'amo', 'comments', 'publisher_id']:
            if hasattr(trade_order, field):
                setattr(order_entry, field, getattr(trade_order, field))

        self.db.add(order_entry)
        self.db.commit()
        self.db.refresh(order_entry)

        await self._create_order_event(order_entry, OrderEvent.ORDER_PLACED)

        # Enqueue the actual order processing to Celery
        from app.core.celery_config import celery_app
        celery_app.send_task('process_order_task', args=[order_entry.to_dict(), organization_id])

        return {"message": "Order processing started", "order_id": order_entry.id}

    async def place_regular_order(
        self,
        pseudo_account: str,
        exchange: str, # Using str here as it comes from API endpoint directly, will be converted to Enum value later
        symbol: str,
        tradeType: str, # Using str here, will be converted to Enum value later
        orderType: str, # Using str here, will be converted to Enum value later
        productType: str, # Using str here, will be converted to Enum value later
        quantity: int,
        price: float,
        triggerPrice: float = 0.0,
        strategy_id: Optional[str] = None,
        organization_id: Optional[str] = None,
        background_tasks: Optional[BackgroundTasks] = None,
    ):
        """Places a regular order."""
        # Add None checks for organization_id and strategy_id
        if organization_id is None:
            raise HTTPException(status_code=400, detail="Organization ID is required")
        if strategy_id is None:
            raise HTTPException(status_code=400, detail="Strategy ID is required")
            
        if not self.rate_limiter.user_rate_limit(pseudo_account, organization_id) or \
           not self.rate_limiter.account_rate_limit(pseudo_account, organization_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        instrument_key = f"{exchange}@{symbol}@{productType}@@@"
        await self._check_for_conflicting_orders(pseudo_account, instrument_key, tradeType, strategy_id)

        if tradeType == "SELL":
            await self._handle_holding_to_position_transition(pseudo_account, instrument_key, quantity, strategy_id)

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
            status="NEW",
            platform_time=datetime.utcnow(),
            transition_type=OrderTransitionType.HOLDING_TO_POSITION if tradeType == "SELL" else OrderTransitionType.NONE,
            variety="REGULAR"
        )
        self.db.add(order_entry)
        self.db.commit()
        self.db.refresh(order_entry)

        await self._create_order_event(order_entry, OrderEvent.ORDER_PLACED)
        from app.core.celery_config import celery_app
        celery_app.send_task('process_order_task', args=[order_entry.to_dict(), organization_id])

        return {"message": "Order processing started", "order_id": order_entry.id}

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
        strategy_id: Optional[str] = None,
        organization_id: Optional[str] = None,
        background_tasks: Optional[BackgroundTasks] = None,
    ):
        """Places a cover order."""
        # Add None checks
        if organization_id is None:
            raise HTTPException(status_code=400, detail="Organization ID is required")
        if strategy_id is None:
            raise HTTPException(status_code=400, detail="Strategy ID is required")
        
        # Type assertions after None checks
        org_id: str = organization_id
        strat_id: str = strategy_id
        
        if not self.rate_limiter.user_rate_limit(pseudo_account, org_id) or \
        not self.rate_limiter.account_rate_limit(pseudo_account, org_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        instrument_key = f"{exchange}@{symbol}@@@"
        await self._check_for_conflicting_orders(pseudo_account, instrument_key, tradeType, strat_id)

        if tradeType == "SELL":
            await self._handle_holding_to_position_transition(pseudo_account, instrument_key, quantity, strat_id)

        order_entry = OrderModel(
            pseudo_account=pseudo_account,
            exchange=exchange,
            symbol=symbol,
            trade_type=tradeType,
            order_type=orderType,
            product_type="CO",  # Fixed: Cover Order uses "CO"
            quantity=quantity,
            price=price,
            trigger_price=triggerPrice,
            strategy_id=strat_id,  # Use strat_id
            instrument_key=instrument_key,
            status="NEW",
            platform_time=datetime.utcnow(),
            transition_type=OrderTransitionType.HOLDING_TO_POSITION if tradeType == "SELL" else OrderTransitionType.NONE,  # type: ignore
            variety="CO"  # Fixed: Cover Order uses "CO" variety
        )
        self.db.add(order_entry)
        self.db.commit()
        self.db.refresh(order_entry)

        await self._create_order_event(order_entry, OrderEvent.ORDER_PLACED)
        from app.core.celery_config import celery_app
        celery_app.send_task('process_order_task', args=[order_entry.to_dict(), org_id])

        return {"message": "Cover Order processing started", "order_id": order_entry.id}

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
        strategy_id: Optional[str] = None,
        organization_id: Optional[str] = None,
        background_tasks: Optional[BackgroundTasks] = None
    ):
        """Places a bracket order."""
        # Add None checks FIRST
        if organization_id is None:
            raise HTTPException(status_code=400, detail="Organization ID is required")
        if strategy_id is None:
            raise HTTPException(status_code=400, detail="Strategy ID is required")
        
        # NOW the type assertions work because we've eliminated None
        org_id: str = organization_id  # Now guaranteed to be str
        strat_id: str = strategy_id    # Now guaranteed to be str
        
        if not self.rate_limiter.user_rate_limit(pseudo_account, org_id) or \
        not self.rate_limiter.account_rate_limit(pseudo_account, org_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        instrument_key = f"{exchange}@{symbol}@@@"
        await self._check_for_conflicting_orders(pseudo_account, instrument_key, tradeType, strat_id)

        if tradeType == "SELL":
            await self._handle_holding_to_position_transition(pseudo_account, instrument_key, quantity, strat_id)

        order_entry = OrderModel(
            pseudo_account=pseudo_account,
            exchange=exchange,
            symbol=symbol,
            trade_type=tradeType,
            order_type=orderType,
            product_type="BO",
            quantity=quantity,
            price=price,
            trigger_price=triggerPrice,
            target=target,
            stoploss=stoploss,
            trailing_stoploss=trailingStoploss,
            strategy_id=strat_id,  # Use strat_id instead of strategy_id
            instrument_key=instrument_key,
            status="NEW",
            platform_time=datetime.utcnow(),
            transition_type=OrderTransitionType.HOLDING_TO_POSITION if tradeType == "SELL" else OrderTransitionType.NONE,
            variety="BO"
        )
        self.db.add(order_entry)
        self.db.commit()
        self.db.refresh(order_entry)

        await self._create_order_event(order_entry, OrderEvent.ORDER_PLACED)
        
        # Add the missing import
        from app.core.celery_config import celery_app
        celery_app.send_task('process_order_task', args=[order_entry.to_dict(), org_id])

        return {"message": "Bracket Order processing started", "order_id": order_entry.id}

    async def get_orders_by_strategy(self, strategy_name: str, organization_id: Optional[str] = None, background_tasks: Optional[BackgroundTasks] = None) -> List[OrderSchema]:
        """Retrieves orders associated with a specific strategy."""
        orders = self.db.query(OrderModel).filter_by(strategy_id=strategy_name).all()
        return [OrderSchema.from_orm(order) for order in orders]

    async def get_positions_by_strategy(self, strategy_name: str) -> List[PositionSchema]:
        """Retrieves positions associated with a specific strategy."""
        positions = self.db.query(PositionModel).filter_by(strategy_id=strategy_name).all()
        return [PositionSchema.from_orm(position) for position in positions]

    async def get_holdings_by_strategy(self, strategy_name: str) -> List[HoldingSchema]:
        """Retrieves holdings associated with a specific strategy."""
        holdings = self.db.query(HoldingModel).filter_by(strategy_id=strategy_name).all()
        return [HoldingSchema.from_orm(holding) for holding in holdings]
    
    async def get_api_key(self, organization_id: str) -> str:
        """
        Retrieves the API key for a given organization, with caching.
        This function is designed to be called asynchronously within the FastAPI application context.
        """
        # This function is now correctly placed within the TradeService class
        # It calls connection_manager.get_redis_connection() directly for its session
        redis_conn = connection_manager.get_redis_connection()
        cached_key = await redis_conn.get(f"api_key:{organization_id}")
        if cached_key:
            result = await cached_key  # Await the Redis result
            return result.decode("utf-8")

        user_service_url = settings.user_service_url
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{user_service_url}/api_key/{organization_id}")
                response.raise_for_status()
                api_key = response.json()["api_key"]
                await redis_conn.set(f"api_key:{organization_id}", api_key.encode("utf-8"), ex=3600)
                return api_key
        except httpx.HTTPStatusError as e:
            print(f"HTTP Error getting API key for organization {organization_id}: {e.response.status_code} - {e.response.text}")
            raise HTTPException(status_code=500, detail=f"Failed to retrieve API key: {e.response.status_code} - {e.response.text}")
        except Exception as e:
            print(f"Error getting API key for organization {organization_id}: {e}")
            raise HTTPException(status_code=500, detail=f"An unexpected error occurred while retrieving API key: {str(e)}")
        finally:
            await redis_conn.aclose() # Close connection after use., strategy_id)

        if tradeType == "SELL":
            await self._handle_holding_to_position_transition(pseudo_account, instrument_key, quantity, strategy_id)

        order_entry = OrderModel(
            pseudo_account=pseudo_account,
            exchange=exchange,
            symbol=symbol,
            trade_type=tradeType,
            order_type=orderType,
            product_type="CO",
            quantity=quantity,
            price=price,
            trigger_price=triggerPrice,
            strategy_id=strategy_id,
            instrument_key=instrument_key,
            status="NEW",
            platform_time=datetime.utcnow(),
            transition_type=OrderTransitionType.HOLDING_TO_POSITION if tradeType == "SELL" else OrderTransitionType.NONE,
            variety="CO"
        )
        self.db.add(order_entry)
        self.db.commit()
        self.db.refresh(order_entry)

        await self._create_order_event(order_entry, OrderEvent.ORDER_PLACED)
        from app.core.celery_config import celery_app
        celery_app.send_task('process_order_task', args=[order_entry.to_dict(), organization_id])

        return {"message": "Cover Order processing started", "order_id": order_entry.id}

    async def get_trade_status(self, order_id: str):
        # StocksDeveloper API call to get order status
        cached_status = await self.redis_conn.get(f"order_status:{order_id}")
        if cached_status:
            return pickle.loads(cached_status)

        # Check if stocksdeveloper_conn exists and is not None
        if not hasattr(self, 'stocksdeveloper_conn') or self.stocksdeveloper_conn is None:
            raise HTTPException(status_code=500, detail="StocksDeveloper connection not available")
        
        order_status = self.stocksdeveloper_conn.get_order_status(order_id=order_id)  # type: ignore

        # Serialize and cache the status
        cached_data = pickle.dumps(order_status)
        await self.redis_conn.set(f"order_status:{order_id}", cached_data, ex=300)  # cache for 5 minutes

        return order_status
    
    async def fetch_all_trading_accounts(self):
        api_key_to_use = settings.stocksdeveloper_api_key
        headers = {"api-key": api_key_to_use}
        url = "https://apix.stocksdeveloper.in/account/fetchAllTradingAccounts"
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            trading_accounts_data = response.json()
            return trading_accounts_data
        except requests.exceptions.RequestException as e:
            raise e
        except json.JSONDecodeError as e:
            raise e
        
    async def modify_order_by_platform_id(
        self, 
        pseudo_account: str, 
        platform_id: str, 
        order_type: Optional[str] = None,
        quantity: Optional[int] = None, 
        price: Optional[float] = None, 
        trigger_price: Optional[float] = None,
        organization_id: Optional[str] = None, 
        background_tasks: Optional[BackgroundTasks] = None,
    ):
        """Modifies an existing order by its platform ID."""
        
        # Add None checks for required parameters
        if organization_id is None:
            raise HTTPException(status_code=400, detail="Organization ID is required")
        
        # Type assertions after None checks
        org_id: str = organization_id
        
        if not self.rate_limiter.user_rate_limit(pseudo_account, org_id) or \
        not self.rate_limiter.account_rate_limit(pseudo_account, org_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        order_entry = OrderModel(
            pseudo_account=pseudo_account, 
            platform=platform_id, 
            variety="MODIFY",
            status="PENDING_MODIFICATION", 
            instrument_key="N/A", 
            platform_time=datetime.utcnow(),
            strategy_id="N/A", 
            order_type=order_type or "N/A",  # Use default if None
            quantity=quantity or 0,          # Use default if None
            price=price or 0.0,              # Use default if None
            trigger_price=trigger_price or 0.0,  # Use default if None
            exchange="N/A", 
            symbol="N/A",
            trade_type="N/A", 
            product_type="N/A"
        )
        self.db.add(order_entry)
        self.db.commit()
        self.db.refresh(order_entry)

        await self._create_order_event(order_entry, OrderEvent.ORDER_PLACED, details=f"Modification request for platform_id: {platform_id}")

        # Fix Celery task call
        from app.core.celery_config import celery_app
        celery_app.send_task('process_order_task', args=[order_entry.to_dict(), org_id])

        return {"message": f"Modify order request submitted for platform_id: {platform_id}", "request_id": order_entry.id}

    async def get_margins_by_organization_and_user(self, organization_name: str, user_id: str) -> List[MarginSchema]:
        """Retrieves margins for a specific user within an organization."""
        organization_id = await self.get_organization_id_from_name(organization_name)
        if not self.rate_limiter.account_rate_limit(user_id, organization_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        margins = self.db.query(MarginModel).filter_by(pseudo_account=user_id).all()
        return [MarginSchema.from_orm(margin) for margin in margins]
    
    async def cancel_all_orders(
        self, pseudo_account: str, organization_id: Optional[str] = None,
        background_tasks: Optional[BackgroundTasks] = None,
    ):
        """Cancels all pending orders for a user."""
        if organization_id is None:
            raise HTTPException(status_code=400, detail="Organization ID is required")

        # Type assertion
        org_id: str = organization_id

        # Then use org_id instead of organization_id in rate limiter calls
        if not self.rate_limiter.user_rate_limit(pseudo_account, org_id) or \
        not self.rate_limiter.account_rate_limit(pseudo_account, org_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        order_entry = OrderModel(
            pseudo_account=pseudo_account, variety="CANCEL_ALL_ORDERS",
            instrument_key="N/A", status="PENDING_CANCEL_ALL",
            platform_time=datetime.utcnow(), strategy_id="N/A",
            exchange="N/A", symbol="N/A", trade_type="N/A",
            order_type="N/A", product_type="N/A", quantity=0, price=0.0
        )
        self.db.add(order_entry)
        self.db.commit()
        self.db.refresh(order_entry)

        await self._create_order_event(order_entry, OrderEvent.ORDER_PLACED, details="Cancel all orders request")

        from app.core.celery_config import celery_app
        celery_app.send_task('process_order_task', args=[order_entry.to_dict(), org_id])

        return {"message": f"Cancel all orders request submitted", "request_id": order_entry.id}

    async def get_orders_by_organization_and_user(self, organization_name: str, user_id: str) -> List[OrderSchema]:
        """Retrieves orders for a specific user within an organization."""
        organization_id = await self.get_organization_id_from_name(organization_name)
        if not self.rate_limiter.account_rate_limit(user_id, organization_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        orders = self.db.query(OrderModel).filter_by(pseudo_account=user_id).all()
        return [OrderSchema.from_orm(order) for order in orders]

    async def square_off_position(
        self, pseudo_account: str, position_category: str, position_type: str,
        exchange: str, symbol: str, organization_id: Optional[str] = None,
        background_tasks: Optional[BackgroundTasks] = None,
    ):
        """Squares off a specific position."""
        if organization_id is None:
            raise HTTPException(status_code=400, detail="Organization ID is required")

        # Type assertion
        org_id: str = organization_id

        # Then use org_id instead of organization_id in rate limiter calls
        if not self.rate_limiter.user_rate_limit(pseudo_account, org_id) or \
        not self.rate_limiter.account_rate_limit(pseudo_account, org_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        instrument_key = f"{exchange}@{symbol}@@@"
        order_entry = OrderModel(
            pseudo_account=pseudo_account, variety="SQUARE_OFF_POSITION",
            instrument_key=instrument_key, status="PENDING_SQUARE_OFF",
            platform_time=datetime.utcnow(), strategy_id="N/A",
            position_category=position_category, position_type=position_type,
            exchange=exchange, symbol=symbol, trade_type="N/A",
            order_type="N/A", product_type="N/A", quantity=0, price=0.0
        )
        self.db.add(order_entry)
        self.db.commit()
        self.db.refresh(order_entry)

        await self._create_order_event(order_entry, OrderEvent.ORDER_PLACED, details=f"Square off request for {instrument_key}")

        from app.core.celery_config import celery_app
        celery_app.send_task('process_order_task', args=[order_entry.to_dict(), org_id])

        return {"message": f"Square off position request submitted", "request_id": order_entry.id}

    async def square_off_portfolio(
        self, pseudo_account: str, position_category: str,
        organization_id: Optional[str] = None, background_tasks: Optional[BackgroundTasks] = None,
    ):
        """Squares off an entire portfolio based on category."""
        if organization_id is None:
            raise HTTPException(status_code=400, detail="Organization ID is required")

        # Type assertion
        org_id: str = organization_id

        # Then use org_id instead of organization_id in rate limiter calls
        if not self.rate_limiter.user_rate_limit(pseudo_account, org_id) or \
        not self.rate_limiter.account_rate_limit(pseudo_account, org_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        order_entry = OrderModel(
            pseudo_account=pseudo_account, variety="SQUARE_OFF_PORTFOLIO",
            instrument_key="N/A", status="PENDING_PORTFOLIO_SQUARE_OFF",
            platform_time=datetime.utcnow(), strategy_id="N/A",
            position_category=position_category, exchange="N/A", symbol="N/A",
            trade_type="N/A", order_type="N/A", product_type="N/A", quantity=0, price=0.0
        )
        self.db.add(order_entry)
        self.db.commit()
        self.db.refresh(order_entry)

        await self._create_order_event(order_entry, OrderEvent.ORDER_PLACED, details=f"Square off portfolio request for category: {position_category}")

        from app.core.celery_config import celery_app
        celery_app.send_task('process_order_task', args=[order_entry.to_dict(), org_id])

        return {"message": f"Square off portfolio request submitted", "request_id": order_entry.id}

    async def cancel_order_by_platform_id(
        self, pseudo_account: str, platform_id: str, organization_id: str,
        background_tasks: Optional[BackgroundTasks] = None,
    ):
        """Cancels an order by its platform ID."""
        if organization_id is None:
            raise HTTPException(status_code=400, detail="Organization ID is required")

        # Type assertion
        org_id: str = organization_id

        # Then use org_id instead of organization_id in rate limiter calls
        if not self.rate_limiter.user_rate_limit(pseudo_account, org_id) or \
        not self.rate_limiter.account_rate_limit(pseudo_account, org_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        order_entry = OrderModel(
            pseudo_account=pseudo_account, platform=platform_id, variety="CANCEL",
            status="PENDING_CANCEL", instrument_key="N/A", platform_time=datetime.utcnow(),
            strategy_id="N/A", exchange="N/A", symbol="N/A", trade_type="N/A",
            order_type="N/A", product_type="N/A", quantity=0, price=0.0
        )
        self.db.add(order_entry)
        self.db.commit()
        self.db.refresh(order_entry)

        await self._create_order_event(order_entry, OrderEvent.ORDER_PLACED, details=f"Cancellation request for platform_id: {platform_id}")

        from app.core.celery_config import celery_app
        celery_app.send_task('process_order_task', args=[order_entry.to_dict(), org_id])

        return {"message": f"Cancel order request submitted for platform_id: {platform_id}", "request_id": order_entry.id}

    async def place_advanced_order(
        self, variety: str, pseudo_account: str, exchange: str, symbol: str,
        tradeType: str, orderType: str, productType: str, quantity: int,
        price: float, triggerPrice: float, target: float, stoploss: float,
        trailingStoploss: float, disclosedQuantity: int, validity: str,
        amo: bool, strategyId: str, comments: str, publisherId: str,
        organization_id: str, background_tasks: Optional[BackgroundTasks] = None,
    ):
        """Places an advanced order (e.g., AMO)."""
        if organization_id is None:
            raise HTTPException(status_code=400, detail="Organization ID is required")

        # Type assertion
        org_id: str = organization_id

        # Then use org_id instead of organization_id in rate limiter calls
        if not self.rate_limiter.user_rate_limit(pseudo_account, org_id) or \
        not self.rate_limiter.account_rate_limit(pseudo_account, org_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        instrument_key = f"{exchange}@{symbol}@{productType}@@@"
        await self._check_for_conflicting_orders(pseudo_account, instrument_key, tradeType, strategyId)

        if tradeType == "SELL":
            await self._handle_holding_to_position_transition(pseudo_account, instrument_key, quantity, strategyId)

        order_entry = OrderModel(
            variety=variety, pseudo_account=pseudo_account, exchange=exchange,
            symbol=symbol, trade_type=tradeType, order_type=orderType,
            product_type=productType, quantity=quantity, price=price,
            trigger_price=triggerPrice, target=target, stoploss=stoploss,
            trailing_stoploss=trailingStoploss, disclosed_quantity=disclosedQuantity,
            validity=validity, amo=amo, strategy_id=strategyId, comments=comments,
            publisher_id=publisherId, instrument_key=instrument_key, status="NEW",
            platform_time=datetime.utcnow(),
            transition_type=OrderTransitionType.HOLDING_TO_POSITION if tradeType == "SELL" else OrderTransitionType.NONE
        )
        self.db.add(order_entry)
        self.db.commit()
        self.db.refresh(order_entry)

        await self._create_order_event(order_entry, OrderEvent.ORDER_PLACED)
        from app.core.celery_config import celery_app
        celery_app.send_task('process_order_task', args=[order_entry.to_dict(), org_id])

        return {"message": "Advanced Order processing started", "order_id": order_entry.id}

    async def get_positions_by_organization_and_user(self, organization_name: str, user_id: str) -> List[PositionSchema]:
        """Retrieves positions for a specific user within an organization."""
        organization_id = await self.get_organization_id_from_name(organization_name)
        if not self.rate_limiter.account_rate_limit(user_id, organization_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        positions = self.db.query(PositionModel).filter_by(pseudo_account=user_id).all()
        return [PositionSchema.from_orm(position) for position in positions]
    
    async def cancel_child_orders_by_platform_id(
        self, pseudo_account: str, platform_id: str, organization_id: str,
        background_tasks: Optional[BackgroundTasks] = None,
    ):
        """Cancels child orders associated with a parent platform ID."""
        if organization_id is None:
            raise HTTPException(status_code=400, detail="Organization ID is required")

        # Type assertion
        org_id: str = organization_id

        # Then use org_id instead of organization_id in rate limiter calls
        if not self.rate_limiter.user_rate_limit(pseudo_account, org_id) or \
        not self.rate_limiter.account_rate_limit(pseudo_account, org_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        order_entry = OrderModel(
            pseudo_account=pseudo_account, platform=platform_id, variety="CANCEL_CHILD",
            status="PENDING_CANCEL_CHILD", instrument_key="N/A", platform_time=datetime.utcnow(),
            strategy_id="N/A", exchange="N/A", symbol="N/A", trade_type="N/A",
            order_type="N/A", product_type="N/A", quantity=0, price=0.0
        )
        self.db.add(order_entry)
        self.db.commit()
        self.db.refresh(order_entry)

        await self._create_order_event(order_entry, OrderEvent.ORDER_PLACED, details=f"Cancellation request for child orders of platform_id: {platform_id}")

        from app.core.celery_config import celery_app
        celery_app.send_task('process_order_task', args=[order_entry.to_dict(), org_id])

        return {"message": f"Cancel child orders request submitted for platform_id: {platform_id}", "request_id": order_entry.id}

    async def get_holdings_by_organization_and_user(self, organization_name: str, user_id: str) -> List[HoldingSchema]:
        """Retrieves holdings for a specific user within an organization."""
        organization_id = await self.get_organization_id_from_name(organization_name)
        if not self.rate_limiter.account_rate_limit(user_id, organization_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        holdings = self.db.query(HoldingModel).filter_by(pseudo_account=user_id).all()
        return [HoldingSchema.from_orm(holding) for holding in holdings]