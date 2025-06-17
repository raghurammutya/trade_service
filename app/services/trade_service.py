# EMERGENCY: Disable Redis temporarily
DISABLE_REDIS_TEMPORARILY = True  # Set to False when Redis is fixed
import json
import logging
from typing import Optional,List

import httpx
from fastapi import HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import text, func
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
from shared_architecture.db.models.symbol import Symbol
from shared_architecture.utils.safe_converters import safe_parse_datetime
from shared_architecture.utils.instrument_key_helper import (parse_stocksdeveloper_symbol, 
    get_instrument_key, 
    symbol_to_instrument_key, 
    instrument_key_to_symbol)

from shared_architecture.utils.safe_converters import (
    safe_convert_int, 
    safe_convert_float, 
    safe_convert_bool, 
    safe_parse_datetime,
    safe_parse_str
)
from app.core.config import settings
from app.utils.rate_limiter import RateLimiter
from app.tasks.update_order_status import update_order_status_task as celery_update_order_status_task
from app.tasks.update_positions_and_holdings_task import update_positions_and_holdings_task
from app.tasks.create_order_event import create_order_event_task
from app.tasks.process_order_task import process_order_task
from shared_architecture.enums import OrderEvent,OrderTransitionType
from datetime import datetime
from typing import cast, Any

logger = logging.getLogger(__name__)

# Try to import real AutoTrader, define mocks only if import fails
try:
    from com.dakshata.autotrader.api.AutoTrader import AutoTrader
    AUTOTRADER_AVAILABLE = True
    logger.debug("Real AutoTrader imported successfully")
    
    # Real AutoTrader is available, no need for mock classes
    
except ImportError:
    AUTOTRADER_AVAILABLE = False
    logger.warning("Real AutoTrader not available, defining mock classes")
    
    # Only define mock classes when real AutoTrader is not available
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
            return AutoTraderResponse(success=True, result=[], message="Mock: AutoTrader not available")
        
        def read_platform_positions(self, pseudo_account=None):
            return AutoTraderResponse(success=True, result=[], message="Mock: AutoTrader not available")
        
        def read_platform_holdings(self, pseudo_account=None):
            return AutoTraderResponse(success=True, result=[], message="Mock: AutoTrader not available")
        
        def read_platform_orders(self, pseudo_account=None):
            return AutoTraderResponse(success=True, result=[], message="Mock: AutoTrader not available")

class TradeService:
    def __init__(self, db: Session):
        self.db = db
        self.account: Optional[str] = None
        self.token: Optional[str] = None
        
        # Initialize TimescaleDB session factory
        try:
            self.timescaledb_session_factory = connection_manager.get_sync_timescaledb_session()
            logger.info("TimescaleDB session factory initialized")
        except Exception as e:
            logger.error(f"Failed to get TimescaleDB session factory: {e}")
            self.timescaledb_session_factory = None
        
        # Initialize Redis connection directly from connection manager
        try:
            self.redis_conn = connection_manager.get_redis_connection()
            if self.redis_conn:
                from app.utils.rate_limiter import RateLimiter
                from shared_architecture.utils.redis_data_manager import RedisDataManager
                self.rate_limiter = RateLimiter(self.redis_conn)
                self.redis_data_manager = RedisDataManager(self.redis_conn)
                logger.info("Redis connection, rate limiter and data manager initialized")
            else:
                logger.warning("Redis not available")
                self.redis_conn = None
                self.rate_limiter = None
                self.redis_data_manager = None
        except Exception as e:
            logger.warning(f"Redis initialization failed: {e}")
            self.redis_conn = None
            self.rate_limiter = None
            self.redis_data_manager = None
        
        # Initialize RabbitMQ connection
        try:
            self.rabbitmq_conn = connection_manager.get_rabbitmq_connection()
            logger.info("RabbitMQ connection initialized")
        except Exception as e:
            logger.warning(f"RabbitMQ connection failed: {e}")
            self.rabbitmq_conn = None
        
        self.stocksdeveloper_conn = None
    def _init_redis_connection(self):
        """Initialize Redis connection and rate limiter"""
        try:
            self.redis_conn = connection_manager.get_redis_connection()
            if self.redis_conn:
                from app.utils.rate_limiter import RateLimiter
                self.rate_limiter = RateLimiter(self.redis_conn)
                logger.debug("Redis connection and rate limiter initialized successfully")
            else:
                logger.warning("Redis connection is None - rate limiting disabled")
                self.rate_limiter = None
        except Exception as e:
            logger.warning(f"Redis connection failed: {e} - rate limiting disabled")
            self.redis_conn = None
            self.rate_limiter = None
    def set_credentials(self, account: str, token: str):
        self.account = account
        self.token = token
    def ensure_symbol_exists(self, symbol: str, exchange: str = 'NSE') -> str:
        """
        Ensure symbol exists in symbols table, insert if not found.
        Returns the instrument_key.
        """
        # Convert AutoTrader symbol to our internal instrument_key
        from shared_architecture.utils.instrument_key_helper import (
            parse_stocksdeveloper_symbol, symbol_to_instrument_key
        )
        
        symbol_data = parse_stocksdeveloper_symbol(symbol, exchange)
        instrument_key = symbol_data['instrument_key']
        
        # Check if symbol already exists
        existing_symbol = self.db.query(Symbol).filter_by(instrument_key=instrument_key).first()
        
        if existing_symbol:
            logger.debug(f"Symbol {instrument_key} already exists in database")
            return instrument_key
        
        # Insert new symbol
        try:
            logger.debug(f"Inserting new symbol {instrument_key} for original symbol '{symbol}' into database")
            
            # Convert expiry_date string to Date object if present
            expiry_date_obj = None
            if symbol_data['expiry_date']:
                try:
                    expiry_date_obj = datetime.strptime(symbol_data['expiry_date'], '%d-%b-%Y').date()
                except ValueError as e:
                    logger.debug(f"Could not parse expiry date {symbol_data['expiry_date']}: {e}")
            
            new_symbol = Symbol(
                instrument_key=instrument_key,
                exchange_code=symbol_data['exchange'],
                stock_code=symbol_data['stock_code'],
                product_type=symbol_data['product_type'],
                expiry_date=expiry_date_obj,
                option_type=symbol_data['option_type'],
                strike_price=float(symbol_data['strike_price']) if symbol_data['strike_price'] else None,
                symbol=symbol,  # Original AutoTrader symbol
                first_added_datetime=datetime.now().date(),
                refresh_flag=True
            )
            
            self.db.add(new_symbol)
            self.db.flush()  # Flush but don't commit yet
            logger.debug(f"Successfully added symbol {instrument_key} to database")
            
        except Exception as e:
            logger.error(f"Error inserting symbol {instrument_key}: {e}")
            # Don't raise exception, just log and continue
        
        return instrument_key
    async def _check_rate_limits(self, user_id: str, organization_id: str) -> bool:
        """Rate limiting disabled - always allow"""
        logger.debug("Rate limiting disabled, allowing all requests")
        return True
    def _call_api(self, endpoint: str, payload: dict, method: str = "POST") -> dict:
        url = f"{settings.trade_api_url}/{endpoint}"
        headers = {"Authorization": f"Bearer {self.token}"}

        response = httpx.request(method, url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()
    async def _get_redis_connection(self):
        """Get a fresh Redis connection with health check"""
        try:
            fresh_conn = await connection_manager.get_redis_connection_async()
            if fresh_conn and fresh_conn != self.redis_conn:
                # Connection was refreshed, update rate limiter
                self.redis_conn = fresh_conn
                if self.rate_limiter:
                    self.rate_limiter.redis_client = fresh_conn
                logger.debug("Redis connection refreshed")
            return fresh_conn
        except Exception as e:
            logger.warning(f"Could not get Redis connection: {e}")
            return None

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
        strategy_id: Optional[str] = None,
        organization_id: Optional[str] = None,
        background_tasks: Optional[BackgroundTasks] = None,
    ):
        """Places a regular order with improved error handling"""
        
        if organization_id is None:
            raise HTTPException(status_code=400, detail="Organization ID is required")
        
        if strategy_id is None:
            raise HTTPException(status_code=400, detail="Strategy ID is required")

        # Check rate limits with improved handling
        try:
            rate_limit_ok = await self._check_rate_limits(pseudo_account, organization_id)
            if not rate_limit_ok:
                raise HTTPException(status_code=429, detail="Too Many Requests")
            
        except HTTPException:
            raise  # Re-raise HTTP exceptions
        except Exception as e:
            logger.warning(f"Rate limit check failed with error: {e}")
            # Continue processing - fail open on rate limit errors

        # Convert AutoTrader symbol to internal instrument_key
        instrument_key = self.ensure_symbol_exists(symbol, exchange)

        await self._check_for_conflicting_orders(pseudo_account, instrument_key, tradeType, strategy_id)

        if tradeType == "SELL":
            
            await self._handle_holding_to_position_transition(pseudo_account, instrument_key, quantity, strategy_id)
        symbol=instrument_key_to_symbol(instrument_key=instrument_key)
        
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

        try:
            self.db.add(order_entry)
            
            self.db.commit()
            
            self.db.refresh(order_entry)
            
        except Exception as e:
            logger.error(f"Database operation failed: {e}")
            self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
        
        # Try to create order event, but don't fail if it doesn't work
        try:
            await self._create_order_event(order_entry, OrderEvent.ORDER_PLACED)
            
        except Exception as e:
            logger.warning(f"Order event creation failed: {e}")
            # Continue processing even if event creation fails

        # Try to send Celery task, but don't fail if it doesn't work
        try:
            from app.core.celery_config import celery_app
            
            celery_app.send_task('process_order_task', args=[order_entry.to_dict(), organization_id])
            
        except Exception as e:
            logger.warning(f"Celery task creation failed: {e}")
            # For now, continue without background processing

        return {"message": "Order processing started", "order_id": order_entry.id}

    async def place_cover_order(
        self,
        pseudo_account: str,
        exchange: str,
        instrument_key: str,  # AutoTrader symbol format
        tradeType: str,
        orderType: str,
        quantity: int,
        price: float,
        triggerPrice: float,
        strategy_id: Optional[str] = None,
        organization_id: Optional[str] = None,
        background_tasks: Optional[BackgroundTasks] = None,
    ):
        """Places a cover order with improved error handling."""

        if organization_id is None:
            raise HTTPException(status_code=400, detail="Organization ID is required")

        if strategy_id is None:
            raise HTTPException(status_code=400, detail="Strategy ID is required")

        # Check rate limits with improved handling
        try:
            rate_limit_ok = await self._check_rate_limits(pseudo_account, organization_id)
            if not rate_limit_ok:
                raise HTTPException(status_code=429, detail="Too Many Requests")
            
        except HTTPException:
            raise  # Re-raise HTTP exceptions
        except Exception as e:
            logger.warning(f"Rate limit check failed with error: {e}")

        # Convert AutoTrader symbol to internal instrument_key
        
        instrument_key = self.ensure_symbol_exists(instrument_key, exchange)

        await self._check_for_conflicting_orders(pseudo_account, instrument_key, tradeType, strategy_id)

        if tradeType == "SELL":
            
            await self._handle_holding_to_position_transition(pseudo_account, instrument_key, quantity, strategy_id)
        symbol= instrument_key_to_symbol(instrument_key=instrument_key)
        
        order_entry = OrderModel(
            pseudo_account=pseudo_account,
            exchange=exchange,
            symbol=symbol,
            trade_type=tradeType,
            order_type=orderType,
            product_type="CO",  # Cover Order product type
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

        try:
            self.db.add(order_entry)
            
            self.db.commit()
            
            self.db.refresh(order_entry)
            
        except Exception as e:
            logger.error(f"Database operation failed: {e}")
            self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
        
        # Try to create order event, but don't fail if it doesn't work
        try:
            await self._create_order_event(order_entry, OrderEvent.ORDER_PLACED)
            
        except Exception as e:
            logger.warning(f"Order event creation failed: {e}")

        # Try to send Celery task, but don't fail if it doesn't work
        try:
            from app.core.celery_config import celery_app
            
            celery_app.send_task('process_order_task', args=[order_entry.to_dict(), organization_id])
            
        except Exception as e:
            logger.warning(f"Celery task creation failed: {e}")

        return {"message": "Cover Order processing started", "order_id": order_entry.id}

    async def place_bracket_order(
        self,
        pseudo_account: str,
        exchange: str,
        instrument_key: str,  # AutoTrader symbol format
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
        """Places a bracket order with improved error handling."""

        if organization_id is None:
            raise HTTPException(status_code=400, detail="Organization ID is required")

        if strategy_id is None:
            raise HTTPException(status_code=400, detail="Strategy ID is required")

        # Check rate limits with improved handling
        try:
            rate_limit_ok = await self._check_rate_limits(pseudo_account, organization_id)
            if not rate_limit_ok:
                raise HTTPException(status_code=429, detail="Too Many Requests")
            
        except HTTPException:
            raise  # Re-raise HTTP exceptions
        except Exception as e:
            logger.warning(f"Rate limit check failed with error: {e}")

        # Convert AutoTrader symbol to internal instrument_key
        instrument_key = self.ensure_symbol_exists(instrument_key, exchange)

        await self._check_for_conflicting_orders(pseudo_account, instrument_key, tradeType, strategy_id)

        if tradeType == "SELL":
            
            await self._handle_holding_to_position_transition(pseudo_account, instrument_key, quantity, strategy_id)
        symbol=instrument_key_to_symbol(instrument_key=instrument_key)
        
        order_entry = OrderModel(
            pseudo_account=pseudo_account,
            exchange=exchange,
            symbol=symbol,
            trade_type=tradeType,
            order_type=orderType,
            product_type="BO",  # Bracket Order product type
            quantity=quantity,
            price=price,
            trigger_price=triggerPrice,
            target=target,
            stoploss=stoploss,
            trailing_stoploss=trailingStoploss,
            strategy_id=strategy_id,
            instrument_key=instrument_key,
            status="NEW",
            platform_time=datetime.utcnow(),
            transition_type=OrderTransitionType.HOLDING_TO_POSITION if tradeType == "SELL" else OrderTransitionType.NONE,
            variety="BO"
        )

        try:
            self.db.add(order_entry)
            
            self.db.commit()
            
            self.db.refresh(order_entry)
            
        except Exception as e:
            logger.error(f"Database operation failed: {e}")
            self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
        
        # Try to create order event, but don't fail if it doesn't work
        try:
            await self._create_order_event(order_entry, OrderEvent.ORDER_PLACED)
            
        except Exception as e:
            logger.warning(f"Order event creation failed: {e}")

        # Try to send Celery task, but don't fail if it doesn't work
        try:
            from app.core.celery_config import celery_app
            
            celery_app.send_task('process_order_task', args=[order_entry.to_dict(), organization_id])
            
        except Exception as e:
            logger.warning(f"Celery task creation failed: {e}")

        return {"message": "Bracket Order processing started", "order_id": order_entry.id}

    async def place_advanced_order(
        self, variety: str, pseudo_account: str, exchange: str, instrument_key: str,
        tradeType: str, orderType: str, productType: str, quantity: int,
        price: float, triggerPrice: float, target: float, stoploss: float,
        trailingStoploss: float, disclosedQuantity: int, validity: str,
        amo: bool, strategyId: str, comments: str, publisherId: str,
        organization_id: str, background_tasks: Optional[BackgroundTasks] = None,
    ):
        """Places an advanced order with improved error handling."""

        if organization_id is None:
            raise HTTPException(status_code=400, detail="Organization ID is required")

        if strategyId is None:
            raise HTTPException(status_code=400, detail="Strategy ID is required")

        # Check rate limits with improved handling
        try:
            rate_limit_ok = await self._check_rate_limits(pseudo_account, organization_id)
            if not rate_limit_ok:
                raise HTTPException(status_code=429, detail="Too Many Requests")
            
        except HTTPException:
            raise  # Re-raise HTTP exceptions
        except Exception as e:
            logger.warning(f"Rate limit check failed with error: {e}")

        # Convert AutoTrader symbol to internal instrument_key
        instrument_key = self.ensure_symbol_exists(instrument_key, exchange)

        await self._check_for_conflicting_orders(pseudo_account, instrument_key, tradeType, strategyId)

        if tradeType == "SELL":
            
            await self._handle_holding_to_position_transition(pseudo_account, instrument_key, quantity, strategyId)
        symbol=instrument_key_to_symbol(instrument_key=instrument_key)
        
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
            trailing_stoploss=trailingStoploss,
            disclosed_quantity=disclosedQuantity,
            validity=validity,
            amo=amo,
            strategy_id=strategyId,
            comments=comments,
            publisher_id=publisherId,
            instrument_key=instrument_key,
            status="NEW",
            platform_time=datetime.utcnow(),
            transition_type=OrderTransitionType.HOLDING_TO_POSITION if tradeType == "SELL" else OrderTransitionType.NONE
        )

        try:
            self.db.add(order_entry)
            
            self.db.commit()
            
            self.db.refresh(order_entry)
            
        except Exception as e:
            logger.error(f"Database operation failed: {e}")
            self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
        
        # Try to create order event, but don't fail if it doesn't work
        try:
            await self._create_order_event(order_entry, OrderEvent.ORDER_PLACED)
            
        except Exception as e:
            logger.warning(f"Order event creation failed: {e}")

        # Try to send Celery task, but don't fail if it doesn't work
        try:
            from app.core.celery_config import celery_app
            
            celery_app.send_task('process_order_task', args=[order_entry.to_dict(), organization_id])
            
        except Exception as e:
            logger.warning(f"Celery task creation failed: {e}")

        return {"message": "Advanced Order processing started", "order_id": order_entry.id}

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

    def verify_symbol_exists(self, instrument_key: str) -> bool:
        """Verify that a symbol exists in the database"""
        try:
            symbol = self.db.query(Symbol).filter_by(instrument_key=instrument_key).first()
            exists = symbol is not None
            return exists
        except Exception as e:
            return False

    async def fetch_and_store_data(self, pseudo_acc: str, organization_id: str):
        """Fetches and stores various datasets (margins, positions, holdings, orders) for a user."""
        if not await self._check_rate_limits(pseudo_acc, organization_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        api_key = await self.get_api_key(organization_id)
        
        # Create AutoTrader connection using the connection pool
        try:
            from shared_architecture.connections.autotrader_pool import AutoTraderConnectionPool
            pool = AutoTraderConnectionPool()
            stocksdeveloper_conn = await pool.get_connection(organization_id, api_key)
            logger.debug("AutoTrader connection obtained from pool")
        except Exception as e:
            logger.debug(f"Connection pool failed, using direct connection: {e}")
            # Fallback to direct connection
            if AUTOTRADER_AVAILABLE:
                try:
                    stocksdeveloper_conn = AutoTrader.create_instance(api_key, AutoTrader.SERVER_URL)
                    logger.debug("Real AutoTrader instance created successfully")
                except Exception as e:
                    logger.warning(f"Real AutoTrader creation failed: {e}, falling back to mock")
                    stocksdeveloper_conn = None
            else:
                logger.warning("Using mock AutoTrader (import failed)")
                stocksdeveloper_conn = AutoTrader.create_instance(api_key, AutoTrader.SERVER_URL)

        if stocksdeveloper_conn is None:
            logger.error(f"AutoTrader connection failed for organization {organization_id}")
            return

        # Create AutoTrader adapter for consistent symbol conversion
        from shared_architecture.utils.symbol_converter import AutoTraderAdapter
        adapter = AutoTraderAdapter(stocksdeveloper_conn)

        logger.debug(f"API key: {api_key}")
        logger.debug(f"AutoTrader available: {AUTOTRADER_AVAILABLE}")
        logger.debug(f"Connection object type: {type(stocksdeveloper_conn)}")
        logger.debug(f"pseudo_acc: {pseudo_acc}")
        # ===== FETCH AND STORE MARGINS =====
        try:
            logger.debug(f"About to call read_platform_margins for {pseudo_acc}")
            margins_result = adapter.read_platform_margins(pseudo_acc)
            logger.debug(f"Margins response success: {margins_result['success']}")
            
            if margins_result['success']:
                margin_results = margins_result['result']
                logger.debug(f"Margin results length: {len(margin_results) if margin_results else 'None'}")
                
                if margin_results and len(margin_results) > 0:
                    # First, delete existing margins for today to avoid duplicates
                    today = datetime.utcnow().date()
                    self.db.query(MarginModel).filter(
                        MarginModel.pseudo_account == pseudo_acc,
                        func.date(MarginModel.margin_date) == today
                    ).delete(synchronize_session=False)
                    for i, margin in enumerate(margin_results):
                        try:
                            margin_dict = {}
                            
                            # Try different ways to extract data from margin object
                            if isinstance(margin, dict):
                                margin_dict = margin.copy()
                            elif hasattr(margin, '__dict__'):
                                margin_dict = margin.__dict__.copy()
                            else:
                                attrs = [attr for attr in dir(margin) if not attr.startswith('_')]
                                for attr in attrs:
                                    try:
                                        value = getattr(margin, attr)
                                        if not callable(value):
                                            margin_dict[attr] = value
                                    except Exception:
                                        pass
                            if not margin_dict:
                                continue
                            
                            category = str(margin_dict.get('category', f'unknown_category_{i}'))
                            
                            margin_entry = MarginModel(
                                pseudo_account=pseudo_acc,
                                margin_date=datetime.utcnow(),
                                category=safe_parse_str(margin_dict.get('category', f'unknown_category_{i}')),
                                available=safe_convert_float(margin_dict.get('available'), 0.0),
                                utilized=safe_convert_float(margin_dict.get('utilized'), 0.0),
                                total=safe_convert_float(margin_dict.get('total'), 0.0),
                                collateral=safe_convert_float(margin_dict.get('collateral'), 0.0),
                                span=safe_convert_float(margin_dict.get('span'), 0.0),
                                exposure=safe_convert_float(margin_dict.get('exposure'), 0.0),
                                adhoc=safe_convert_float(margin_dict.get('adhoc'), 0.0),
                                net=safe_convert_float(margin_dict.get('net'), 0.0),
                                funds=safe_convert_float(margin_dict.get('funds'), 0.0),
                                payin=safe_convert_float(margin_dict.get('payin'), 0.0),
                                payout=safe_convert_float(margin_dict.get('payout'), 0.0),
                                realised_mtm=safe_convert_float(margin_dict.get('realised_mtm'), 0.0),
                                unrealised_mtm=safe_convert_float(margin_dict.get('unrealised_mtm'), 0.0),
                                stock_broker=safe_parse_str(margin_dict.get('stock_broker', 'Unknown')),
                                trading_account=safe_parse_str(margin_dict.get('trading_account', 'Unknown'))
                            )
                            
                            self.db.add(margin_entry)
                        except Exception as e:
                            continue
                else:
                    logger.debug(f"No margin results returned for {pseudo_acc}")
            else:
                logger.debug(f"Margins API call failed for {pseudo_acc}: {margins_result['message']}")
        except Exception as e:
            logger.debug(f"Exception in margins fetch: {e}")
            
        # ===== FETCH AND STORE POSITIONS =====
        try:
            positions_result = adapter.read_platform_positions(pseudo_acc)
            if positions_result['success']:
                position_results = positions_result['result']
                if position_results and len(position_results) > 0:
                    # First, delete existing positions for today to avoid duplicates
                    today = datetime.utcnow().date()
                    self.db.query(PositionModel).filter(
                        PositionModel.pseudo_account == pseudo_acc,
                        func.date(PositionModel.timestamp) == today
                    ).delete(synchronize_session=False)
                    for i, position_dict in enumerate(position_results):
                        try:
                            # Data already converted by AutoTraderAdapter - instrument_key should be present
                            if not position_dict:
                                continue
                            
                            # Get properly converted fields
                            exchange = str(position_dict.get('exchange', 'NSE'))
                            instrument_key = position_dict.get('instrument_key')
                            symbol = position_dict.get('symbol', f'UNKNOWN_SYMBOL_{i}')
                            
                            # Fallback conversion if needed
                            if not instrument_key and symbol:
                                instrument_key = symbol_to_instrument_key(symbol, exchange)
                                instrument_key = self.ensure_symbol_exists(symbol, exchange)
                            elif instrument_key:
                                # Ensure symbol exists in our database
                                instrument_key = self.ensure_symbol_exists(instrument_key_to_symbol(instrument_key), exchange)
                            
                            position_entry = PositionModel(
                                pseudo_account=pseudo_acc,
                                instrument_key=instrument_key,
                                timestamp=datetime.utcnow(),
                                account_id=pseudo_acc,
                                exchange=exchange,
                                symbol=symbol,  # Use converted symbol
                                net_quantity=safe_convert_int(position_dict.get('net_quantity'), 0),
                                buy_quantity=safe_convert_int(position_dict.get('buy_quantity'), 0),
                                sell_quantity=safe_convert_int(position_dict.get('sell_quantity'), 0),
                                buy_avg_price=safe_convert_float(position_dict.get('buy_avg_price'), 0.0),
                                sell_avg_price=safe_convert_float(position_dict.get('sell_avg_price'), 0.0),
                                buy_value=safe_convert_float(position_dict.get('buy_value'), 0.0),
                                sell_value=safe_convert_float(position_dict.get('sell_value'), 0.0),
                                ltp=safe_convert_float(position_dict.get('ltp'), 0.0),
                                pnl=safe_convert_float(position_dict.get('pnl', position_dict.get('unrealized_pnl', position_dict.get('unrealised_pnl', position_dict.get('mtm')))), 0.0),
                                realised_pnl=safe_convert_float(position_dict.get('realised_pnl', position_dict.get('realized_pnl')), 0.0),
                                unrealised_pnl=safe_convert_float(position_dict.get('unrealised_pnl', position_dict.get('unrealized_pnl', position_dict.get('mtm'))), 0.0),
                                mtm=safe_convert_float(position_dict.get('mtm'), 0.0),
                                at_pnl=safe_convert_float(position_dict.get('atPnl'), 0.0),
                                direction=safe_parse_str(position_dict.get('direction', 'NONE')),
                                category=safe_parse_str(position_dict.get('category', 'INTRADAY')),
                                type=safe_parse_str(position_dict.get('type', 'EQUITY')),
                                state=safe_parse_str(position_dict.get('state', 'OPEN')),
                                platform=safe_parse_str(position_dict.get('platform', position_dict.get('stock_broker', 'Unknown'))),
                                stock_broker=safe_parse_str(position_dict.get('stock_broker', position_dict.get('platform', 'Unknown'))),
                                trading_account=pseudo_acc,
                                multiplier=safe_convert_int(position_dict.get('multiplier'), 1),
                                net_value=safe_convert_float(position_dict.get('net_value'), 0.0),
                                overnight_quantity=safe_convert_int(position_dict.get('overnight_quantity'), 0)
                            )
                            
                            self.db.add(position_entry)
                        except Exception as e:
                            continue
                else:
                    logger.debug(f"No position results returned for {pseudo_acc}")
            else:
                logger.debug(f"Positions API call failed for {pseudo_acc}: {positions_result['message']}")
        except Exception as e:
            logger.debug(f"Exception in positions fetch: {e}")
            
        # ===== FETCH AND STORE HOLDINGS =====
        try:
            holdings_result = adapter.read_platform_holdings(pseudo_acc)
            if holdings_result['success']:
                holding_results = holdings_result['result']
                if holding_results and len(holding_results) > 0:
                    # First, delete existing holdings for today to avoid duplicates
                    today = datetime.utcnow().date()
                    self.db.query(HoldingModel).filter(
                        HoldingModel.pseudo_account == pseudo_acc,
                        func.date(HoldingModel.timestamp) == today
                    ).delete(synchronize_session=False)
                    for i, holding_dict in enumerate(holding_results):
                        try:
                            # Data already converted by AutoTraderAdapter - instrument_key should be present
                            if not holding_dict:
                                continue
                            
                            # Get properly converted fields
                            exchange = str(holding_dict.get('exchange', 'NSE'))
                            instrument_key = holding_dict.get('instrument_key')
                            symbol = holding_dict.get('symbol', f'UNKNOWN_SYMBOL_{i}')
                            
                            # Fallback conversion if needed
                            if not instrument_key and symbol:
                                instrument_key = symbol_to_instrument_key(symbol, exchange)
                                instrument_key = self.ensure_symbol_exists(symbol, exchange)
                            elif instrument_key:
                                # Symbol exists in our database - check if already exists, create if not
                                existing_symbol = self.db.query(Symbol).filter_by(instrument_key=instrument_key).first()
                                if not existing_symbol:
                                    # For bonds, use the original symbol from the data
                                    # For other types, extract from instrument_key
                                    if '@bonds' in instrument_key:
                                        original_symbol = symbol  # Use the actual bond symbol from the data
                                    else:
                                        original_symbol = instrument_key_to_symbol(instrument_key)
                                    self.ensure_symbol_exists(original_symbol, exchange)
                                else:
                                    logger.debug(f"Symbol {instrument_key} already exists in database")
                            
                            holding_entry = HoldingModel(
                                pseudo_account=pseudo_acc,
                                instrument_key=instrument_key,
                                timestamp=datetime.utcnow(),
                                trading_account=pseudo_acc,
                                exchange=exchange,
                                symbol=symbol,  # Use converted symbol
                                quantity=safe_convert_int(holding_dict.get('quantity'), 0),
                                product=safe_parse_str(holding_dict.get('product', 'DELIVERY')),
                                isin=safe_parse_str(holding_dict.get('isin', '')),
                                collateral_qty=safe_convert_int(holding_dict.get('collateral_qty'), 0),
                                t1_qty=safe_convert_int(holding_dict.get('t1_qty'), 0),
                                collateral_type=safe_parse_str(holding_dict.get('collateral_type', '')),
                                pnl=safe_convert_float(holding_dict.get('pnl', holding_dict.get('unrealized_pnl', holding_dict.get('unrealised_pnl'))), 0.0),
                                haircut=safe_convert_float(holding_dict.get('haircut'), 0.0),
                                avg_price=safe_convert_float(holding_dict.get('avg_price'), 0.0),
                                instrument_token=safe_convert_int(holding_dict.get('instrument_token'), 0),
                                stock_broker=safe_parse_str(holding_dict.get('stock_broker', holding_dict.get('platform', 'Unknown'))),
                                platform=safe_parse_str(holding_dict.get('platform', holding_dict.get('stock_broker', 'Unknown'))),
                                ltp=safe_convert_float(holding_dict.get('ltp'), 0.0),
                                current_value=safe_convert_float(holding_dict.get('currentValue', holding_dict.get('current_value', holding_dict.get('market_value'))), 0.0),
                                total_qty=safe_convert_int(holding_dict.get('totalQty'), 0)
                            )
                            
                            self.db.add(holding_entry)
                        except Exception as e:
                            continue
                else:
                    logger.debug(f"No holding results returned for {pseudo_acc}")
            else:
                logger.debug(f"Holdings API call failed for {pseudo_acc}: {holdings_result['message']}")
        except Exception as e:
            logger.debug(f"Exception in holdings fetch: {e}")
            
        # ===== FETCH AND STORE ORDERS =====
        try:
            orders_result = adapter.read_platform_orders(pseudo_acc)
            if orders_result['success']:
                order_results = orders_result['result']
                if order_results and len(order_results) > 0:
                    for i, order_dict in enumerate(order_results):
                        try:
                            # Data already converted by AutoTraderAdapter - instrument_key should be present
                            if not order_dict:
                                continue
                            # Get properly converted fields
                            exchange = str(order_dict.get('exchange', 'NSE'))
                            instrument_key = order_dict.get('instrument_key')
                            symbol = order_dict.get('symbol', f'UNKNOWN_SYMBOL_{i}')
                            
                            # Fallback conversion if needed
                            if not instrument_key and symbol:
                                instrument_key = symbol_to_instrument_key(symbol, exchange)
                                instrument_key = self.ensure_symbol_exists(symbol, exchange)
                            elif instrument_key:
                                # Ensure symbol exists in our database
                                instrument_key = self.ensure_symbol_exists(instrument_key_to_symbol(instrument_key), exchange)
                            
                            # Convert timestamp fields safely
                            exchange_time = safe_parse_datetime(cast(Any, order_dict.get('exchange_time'))) if order_dict.get('exchange_time') else None
                            platform_time = safe_parse_datetime(cast(Any, order_dict.get('platform_time'))) if order_dict.get('platform_time') else None  
                            modified_time = safe_parse_datetime(cast(Any, order_dict.get('modified_time'))) if order_dict.get('modified_time') else None
                            
                            # If platform_time is still None, use current time
                            if platform_time is None:
                                platform_time = datetime.utcnow()
                            order_entry = OrderModel(
                                pseudo_account=pseudo_acc,
                                instrument_key=instrument_key,
                                timestamp=datetime.utcnow(),
                                exchange=exchange,
                                symbol=symbol,  # Use converted symbol
                                trade_type=safe_parse_str(order_dict.get('trade_type', 'BUY')),
                                order_type=safe_parse_str(order_dict.get('order_type', 'MARKET')),
                                product_type=safe_parse_str(order_dict.get('productType', 'INTRADAY')),
                                variety=safe_parse_str(order_dict.get('variety', 'REGULAR')),
                                quantity=safe_convert_int(order_dict.get('quantity'), 0),
                                price=safe_convert_float(order_dict.get('price'), 0.0),
                                trigger_price=safe_convert_float(order_dict.get('trigger_price'), 0.0),
                                average_price=safe_convert_float(order_dict.get('average_price'), 0.0),
                                filled_quantity=safe_convert_int(order_dict.get('filled_quantity'), 0),
                                pending_quantity=safe_convert_int(order_dict.get('pending_quantity'), 0),
                                disclosed_quantity=safe_convert_int(order_dict.get('disclosed_quantity'), 0),
                                status=safe_parse_str(order_dict.get('status', 'NEW')),
                                status_message=safe_parse_str(order_dict.get('status_message', '')),
                                exchange_order_id=safe_parse_str(order_dict.get('exchange_order_id', '')),
                                platform=safe_parse_str(order_dict.get('platform', 'StocksDeveloper')),
                                stock_broker='StocksDeveloper',
                                trading_account=pseudo_acc,
                                validity=safe_parse_str(order_dict.get('validity', 'DAY')),
                                amo=safe_convert_bool(order_dict.get('amo'), False),
                                exchange_time=exchange_time,
                                platform_time=platform_time,
                                modified_time=modified_time,
                                client_id=safe_parse_str(order_dict.get('client_id', '')),
                                nest_request_id=safe_parse_str(order_dict.get('nest_request_id', '')),
                                publisher_id=safe_parse_str(order_dict.get('publisher_id', '')),
                                parent_order_id=safe_convert_int(order_dict.get('parent_order_id')) if order_dict.get('parent_order_id') else None,
                                independent_exchange=safe_parse_str(order_dict.get('independent_exchange', '')),
                                independent_symbol=safe_parse_str(order_dict.get('independent_symbol', '')),
                                target=safe_convert_float(order_dict.get('target')),
                                stoploss=safe_convert_float(order_dict.get('stoploss')),
                                trailing_stoploss=safe_convert_float(order_dict.get('trailing_stoploss')),
                                position_category=safe_parse_str(order_dict.get('position_category', '')),
                                position_type=safe_parse_str(order_dict.get('position_type', '')),
                                comments=safe_parse_str(order_dict.get('comments', '')),
                                strategy_id=safe_parse_str(order_dict.get('strategy_id', 'default')),
                                transition_type='NONE'
                            )
                            
                            self.db.add(order_entry)
                        except Exception as e:
                            import traceback
                            continue
                else:
                    logger.debug(f"No order results returned for {pseudo_acc}")
            else:
                logger.debug(f"Orders API call failed for {pseudo_acc}: {orders_result['message']}")
        except Exception as e:
            import traceback
            logger.debug(f"Exception in orders fetch: {type(e).__name__}: {e}")
            logger.debug(f"Orders fetch traceback: {traceback.format_exc()}")
        # Commit all changes
        try:
            self.db.commit()
            # Verify the data was actually inserted
            margin_count = self.db.query(MarginModel).filter_by(pseudo_account=pseudo_acc).count()
            position_count = self.db.query(PositionModel).filter_by(pseudo_account=pseudo_acc).count()
            holding_count = self.db.query(HoldingModel).filter_by(pseudo_account=pseudo_acc).count()
            order_count = self.db.query(OrderModel).filter_by(pseudo_account=pseudo_acc).count()
            # Store data in Redis if available
            if self.redis_data_manager:
                try:
                    # Get all data from DB (with default strategy_id)
                    margins = self.db.query(MarginModel).filter_by(pseudo_account=pseudo_acc).all()
                    positions = self.db.query(PositionModel).filter_by(pseudo_account=pseudo_acc).all()
                    holdings = self.db.query(HoldingModel).filter_by(pseudo_account=pseudo_acc).all()
                    orders = self.db.query(OrderModel).filter_by(pseudo_account=pseudo_acc).all()
                    
                    # Store in Redis (without strategy_id for blanket data)
                    await self.redis_data_manager.store_margins(organization_id, pseudo_acc, margins)
                    await self.redis_data_manager.store_positions(organization_id, pseudo_acc, positions)
                    await self.redis_data_manager.store_holdings(organization_id, pseudo_acc, holdings)
                    await self.redis_data_manager.store_orders(organization_id, pseudo_acc, orders)
                    
                    # Also store by strategy if data has strategy_id
                    strategies = set()
                    for item in margins + positions + holdings + orders:
                        if hasattr(item, 'strategy_id') and item.strategy_id and item.strategy_id != 'default':
                            strategies.add(item.strategy_id)
                    
                    for strategy_id in strategies:
                        strat_margins = [m for m in margins if m.strategy_id == strategy_id]
                        strat_positions = [p for p in positions if p.strategy_id == strategy_id]
                        strat_holdings = [h for h in holdings if h.strategy_id == strategy_id]
                        strat_orders = [o for o in orders if o.strategy_id == strategy_id]
                        
                        if strat_margins:
                            await self.redis_data_manager.store_margins(organization_id, pseudo_acc, strat_margins, strategy_id)
                        if strat_positions:
                            await self.redis_data_manager.store_positions(organization_id, pseudo_acc, strat_positions, strategy_id)
                        if strat_holdings:
                            await self.redis_data_manager.store_holdings(organization_id, pseudo_acc, strat_holdings, strategy_id)
                        if strat_orders:
                            await self.redis_data_manager.store_orders(organization_id, pseudo_acc, strat_orders, strategy_id)
                except Exception as e:
                    print(f"WARNING: Failed to store data in Redis: {e}")
                    # Don't fail the operation if Redis storage fails
            
        except Exception as e:
            import traceback
            self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
        
        return {
            "message": f"Data fetched and stored for {pseudo_acc}",
            "counts": {
                "margins": self.db.query(MarginModel).filter_by(pseudo_account=pseudo_acc).count(),
                "positions": self.db.query(PositionModel).filter_by(pseudo_account=pseudo_acc).count(),
                "holdings": self.db.query(HoldingModel).filter_by(pseudo_account=pseudo_acc).count(),
                "orders": self.db.query(OrderModel).filter_by(pseudo_account=pseudo_acc).count()
            }
        }

    async def _create_order_event(self, order: OrderModel, event_type: OrderEvent, details: Optional[str] = None):
        """
        Triggers a Celery task to create and store an OrderEvent.
        """
        # Use send_task instead of apply_async for consistency
        from app.core.celery_config import celery_app
        celery_app.send_task('create_order_event_task', args=[order.id, event_type.value, details])

    async def _get_organization_name_for_user(self, user_id: str) -> str:
        """Return default organization name - no Redis lookup"""
        return "default_org"

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
        Updates positions and holdings based on order execution status.
        🔧 FIX: Use separate database session for Celery tasks.
        """
        if order.status not in ["COMPLETE", "PARTIALLY_FILLED"]:
            print(f"Order {order.id} status is {order.status}. Skipping position/holding update.")
            return

        # Extract actual values from SQLAlchemy columns
        filled_qty_val = getattr(order, 'filled_quantity', None)
        order_qty_val = getattr(order, 'quantity', None) or 0

        # Use actual Python values for comparison
        quantity_impact = filled_qty_val if filled_qty_val is not None and filled_qty_val > 0 else order_qty_val
        if quantity_impact == 0:
            return

        # 🔧 FIX: Create a new database session for this operation
        if not self.timescaledb_session_factory:
            logger.error("No TimescaleDB session factory available")
            return
            
        session = self.db
        try:
            instrument_key = order.instrument_key
            pseudo_account = order.pseudo_account
            strategy_id = order.strategy_id
            trade_type = order.trade_type
            trade_type_val = str(order.trade_type or "")
            signed_quantity_impact = quantity_impact if trade_type_val == "BUY" else -quantity_impact

            existing_position = session.query(PositionModel).filter_by(
                pseudo_account=pseudo_account,
                instrument_key=instrument_key,
                strategy_id=strategy_id
            ).first()

            if existing_position:
                # Extract current values to Python variables using getattr()
                current_net_qty = int(getattr(existing_position, 'net_quantity', 0) or 0)
                current_buy_qty = int(getattr(existing_position, 'buy_quantity', 0) or 0)
                current_sell_qty = int(getattr(existing_position, 'sell_quantity', 0) or 0)
                current_buy_val = float(getattr(existing_position, 'buy_value', 0) or 0)
                current_sell_val = float(getattr(existing_position, 'sell_value', 0) or 0)
                order_price_val = float(getattr(order, 'price', 0) or 0)
                
                # Calculate the final net quantity
                final_net_qty = current_net_qty + signed_quantity_impact
                
                # Update net quantity
                setattr(existing_position, 'net_quantity', final_net_qty)
                
                if trade_type_val == "BUY":
                    new_buy_qty = current_buy_qty + quantity_impact
                    new_buy_val = current_buy_val + (order_price_val * quantity_impact)
                    setattr(existing_position, 'buy_quantity', new_buy_qty)
                    setattr(existing_position, 'buy_value', new_buy_val)
                    setattr(existing_position, 'buy_avg_price', new_buy_val / new_buy_qty if new_buy_qty else 0)
                else:
                    new_sell_qty = current_sell_qty + quantity_impact
                    new_sell_val = current_sell_val + (order_price_val * quantity_impact)
                    setattr(existing_position, 'sell_quantity', new_sell_qty)
                    setattr(existing_position, 'sell_value', new_sell_val)
                    setattr(existing_position, 'sell_avg_price', new_sell_val / new_sell_qty if new_sell_qty else 0)
                
                # Update direction based on final net quantity
                if final_net_qty > 0:
                    setattr(existing_position, 'direction', "BUY")
                elif final_net_qty < 0:
                    setattr(existing_position, 'direction', "SELL")
                else:
                    setattr(existing_position, 'direction', "NONE")

                setattr(existing_position, 'timestamp', datetime.utcnow())

            else:
                buy_quantity_val = safe_convert_int(getattr(trade_type, 'BUY', 0) or 0)
                sell_quantity_val = safe_convert_int(getattr(trade_type, 'SELL', 0) or 0)
                buy_val = safe_convert_float(getattr(trade_type, 'BUY', order.price * quantity_impact) or 0)
                sell_val = safe_convert_float(getattr(trade_type, 'SELL', order.price * quantity_impact) or 0)   
                buy_price = safe_convert_float(getattr(trade_type, 'BUY', None) or order.price)
                sell_price = safe_convert_float(getattr(trade_type, 'SELL', None) or order.price)
            
                new_position = PositionModel(
                    pseudo_account=pseudo_account,
                    instrument_key=instrument_key,
                    strategy_id=strategy_id,
                    net_quantity=signed_quantity_impact,
                    buy_quantity=buy_quantity_val,
                    sell_quantity=sell_quantity_val,
                    buy_value=buy_val,
                    sell_value=sell_val,
                    buy_avg_price=buy_price,
                    sell_avg_price=sell_price,
                    direction=trade_type,
                    timestamp=datetime.utcnow(),
                    account_id=pseudo_account,
                    exchange=order.exchange,
                    symbol=order.symbol,
                    platform='StocksDeveloper', pnl=0.0, realised_pnl=0.0, unrealised_pnl=0.0,
                    state='OPEN',
                    category="INTRADAY",
                    type=order.product_type,
                    ltp=0.0, mtm=0.0, multiplier=1, net_value=0.0, overnight_quantity=0, 
                    stock_broker="StocksDeveloper", trading_account=pseudo_account
                )
                session.add(new_position)

            session.commit()
            logger.info(f"Successfully updated positions for order {order.id}")
            
            # Trigger Redis sync for the affected strategy
            try:
                from app.tasks.sync_to_redis_task import sync_on_data_change
                # Get organization_id - you may need to pass this in or retrieve it
                organization_id = getattr(order, 'organization_id', 'default_org')
                sync_on_data_change.delay(organization_id, pseudo_account, 'positions', strategy_id)
            except Exception as e:
                logger.warning(f"Failed to trigger Redis sync: {e}")
            
        except Exception as e:
            logger.error(f"Error updating positions for order {order.id}: {e}")
            session.rollback()
            raise

    async def get_organization_id_from_name(self, organization_name: str) -> str:
            """
            Retrieves the organization ID from the organization name using the User Service.
            """
            user_service_url = settings.user_service_url
            try:
                # Add timeout and connection pooling
                timeout = httpx.Timeout(10.0, connect=5.0)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.get(f"{user_service_url}/organizations/by_name/{organization_name}")
                    response.raise_for_status()
                    organization_data = response.json()
                    if "id" not in organization_data:
                        raise ValueError(f"User Service response for organization '{organization_name}' missing 'id'. Response: {organization_data}")
                    return organization_data["id"]
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout) as e:
                # Handle connection issues gracefully - return a mock ID for testing
                                # For testing, return the organization name as ID
                return organization_name
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    raise ValueError(f"Organization '{organization_name}' not found via User Service.")
                raise
            except Exception as e:
                # For testing, return the organization name as ID
                return organization_name

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
        if not self._check_rate_limits(trade_order.user_id, organization_id) or \
           not self._check_rate_limits(trade_order.user_id, organization_id):
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
        """Get API key from settings only"""
        try:
            from app.core.config import settings
            api_key = settings.stocksdeveloper_api_key
            if not api_key:
                raise HTTPException(status_code=500, detail="AutoTrader API key not found in settings")
            return api_key
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get API key: {str(e)}")

    async def get_trade_status(self, order_id: str):
        """Get trade status without Redis caching"""
        if not hasattr(self, 'stocksdeveloper_conn') or self.stocksdeveloper_conn is None:
            raise HTTPException(status_code=500, detail="StocksDeveloper connection not available")
        
        order_status = self.stocksdeveloper_conn.get_order_status(order_id=order_id)
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
        
        if not await self._check_rate_limits(pseudo_account, org_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        order_entry = OrderModel(
            pseudo_account=pseudo_account, 
            platform=platform_id, 
            variety="MODIFY",
            status="PENDING_MODIFICATION", 
            instrument_key="SYSTEM", 
            platform_time=datetime.utcnow(),
            strategy_id="SYSTEM", 
            order_type=order_type or "N/A",  # Use default if None
            quantity=quantity or 0,          # Use default if None
            price=price or 0.0,              # Use default if None
            trigger_price=trigger_price or 0.0,  # Use default if None
            exchange="SYSTEM", 
            symbol="SYSTEM",
            trade_type="SYSTEM", 
            product_type="SYSTEM"
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
        if not await self._check_rate_limits(user_id, organization_id):
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
        if not await self._check_rate_limits(pseudo_account, org_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        order_entry = OrderModel(
            pseudo_account=pseudo_account, variety="CANCEL_ALL_ORDERS",
            instrument_key="SYSTEM", status="PENDING_CANCEL_ALL",
            platform_time=datetime.utcnow(), strategy_id="SYSTEM",
            exchange="SYSTEM", symbol="SYSTEM", trade_type="SYSTEM",
            order_type="SYSTEM", product_type="SYSTEM", quantity=0, price=0.0
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
        if not await self._check_rate_limits(user_id, organization_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        orders = self.db.query(OrderModel).filter_by(pseudo_account=user_id).all()
        return [OrderSchema.from_orm(order) for order in orders]

    async def square_off_position(
        self, pseudo_account: str, position_category: str, position_type: str,
        exchange: str, instrument_key: str, organization_id: Optional[str] = None,
        background_tasks: Optional[BackgroundTasks] = None,
    ):
        """Squares off a specific position."""
        if organization_id is None:
            raise HTTPException(status_code=400, detail="Organization ID is required")

        # Type assertion
        org_id: str = organization_id

        # Then use org_id instead of organization_id in rate limiter calls
        if not await self._check_rate_limits(pseudo_account, org_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        # Convert AutoTrader symbol to internal instrument_key
        symbol = instrument_key_to_symbol(instrument_key)
        order_entry = OrderModel(
            pseudo_account=pseudo_account, variety="SQUARE_OFF_POSITION",
            instrument_key=instrument_key, status="PENDING_SQUARE_OFF",
            platform_time=datetime.utcnow(), strategy_id="SYSTEM",
            position_category=position_category, position_type=position_type,
            exchange=exchange, symbol=symbol, trade_type="SYSTEM",
            order_type="SYSTEM", product_type="SYSTEM", quantity=0, price=0.0
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
        if not await self._check_rate_limits(pseudo_account, org_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        order_entry = OrderModel(
            pseudo_account=pseudo_account, variety="SQUARE_OFF_PORTFOLIO",
            instrument_key="SYSTEM", status="PENDING_PORTFOLIO_SQUARE_OFF",
            platform_time=datetime.utcnow(), strategy_id="SYSTEM",
            position_category=position_category, exchange="SYSTEM", symbol="SYSTEM",
            trade_type="SYSTEM", order_type="SYSTEM", product_type="SYSTEM", quantity=0, price=0.0
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
        if not await self._check_rate_limits(pseudo_account, org_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        order_entry = OrderModel(
            pseudo_account=pseudo_account, platform=platform_id, variety="CANCEL",
            status="PENDING_CANCEL", instrument_key="SYSTEM", platform_time=datetime.utcnow(),
            strategy_id="SYSTEM", exchange="SYSTEM", symbol="SYSTEM", trade_type="SYSTEM",
            order_type="SYSTEM", product_type="SYSTEM", quantity=0, price=0.0
        )
        self.db.add(order_entry)
        self.db.commit()
        self.db.refresh(order_entry)

        await self._create_order_event(order_entry, OrderEvent.ORDER_PLACED, details=f"Cancellation request for platform_id: {platform_id}")

        from app.core.celery_config import celery_app
        celery_app.send_task('process_order_task', args=[order_entry.to_dict(), org_id])

        return {"message": f"Cancel order request submitted for platform_id: {platform_id}", "request_id": order_entry.id}

    async def get_positions_by_organization_and_user(self, organization_name: str, user_id: str) -> List[PositionSchema]:
        """Retrieves positions for a specific user within an organization."""
        organization_id = await self.get_organization_id_from_name(organization_name)
        if not await self._check_rate_limits(user_id, organization_id):
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
        if not await self._check_rate_limits(pseudo_account, org_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        order_entry = OrderModel(
            pseudo_account=pseudo_account, platform=platform_id, variety="CANCEL_CHILD",
            status="PENDING_CANCEL_CHILD", instrument_key="SYSTEM", platform_time=datetime.utcnow(),
            strategy_id="SYSTEM", exchange="SYSTEM", symbol="SYSTEM", trade_type="SYSTEM",
            order_type="SYSTEM", product_type="SYSTEM", quantity=0, price=0.0
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
        if not await self._check_rate_limits(user_id, organization_id):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        holdings = self.db.query(HoldingModel).filter_by(pseudo_account=user_id).all()
        return [HoldingSchema.from_orm(holding) for holding in holdings]
    
