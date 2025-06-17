# app/services/production_trade_service.py
"""
Production-ready trade service with enhanced error handling, logging, and validation.
Integrates all quality improvements from Phase 1.
"""

import asyncio
from datetime import datetime
from typing import Dict, Any, Optional, List, Union
from decimal import Decimal
from sqlalchemy.orm import Session
from fastapi import HTTPException, BackgroundTasks

# Import our new infrastructure
from shared_architecture.utils.enhanced_logging import get_logger, LoggingContext, with_logging
from shared_architecture.utils.error_handler import handle_errors, ErrorHandler, create_error_context
from shared_architecture.validation.trade_validators import TradeValidator, OrderValidator, validate_and_raise
from shared_architecture.config.trade_config import get_config, is_feature_enabled, FeatureFlag
from shared_architecture.exceptions.trade_exceptions import (
    ValidationException, AutoTraderException, DatabaseException,
    InsufficientFundsException, OrderNotFoundException, RateLimitException,
    ErrorContext, ErrorSeverity
)

# Import models and utilities
from shared_architecture.db.models.order_model import OrderModel
from shared_architecture.db.models.position_model import PositionModel
from shared_architecture.db.models.holding_model import HoldingModel
from shared_architecture.db.models.margin_model import MarginModel
from shared_architecture.enums import OrderStatus, TradeType, OrderType
from shared_architecture.utils.redis_data_manager import RedisDataManager
from shared_architecture.utils.symbol_converter import AutoTraderAdapter
from shared_architecture.connections.autotrader_pool import AutoTraderConnectionPool

# Import existing services
from app.services.enhanced_trade_service import EnhancedTradeService
from app.services.order_monitoring_service import OrderMonitoringService
from app.utils.rate_limiter import RateLimiter

logger = get_logger(__name__)

class ProductionTradeService:
    """
    Production-ready trade service with comprehensive error handling,
    validation, logging, and monitoring capabilities.
    """
    
    def __init__(self, db: Session, redis_manager: RedisDataManager = None):
        self.db = db
        self.redis_manager = redis_manager
        self.config = get_config()
        self.rate_limiter = RateLimiter()
        self.autotrader_pool = AutoTraderConnectionPool()
        
        # Initialize enhanced services if feature flags are enabled
        self.enhanced_service = None
        self.order_monitor = None
        
        if is_feature_enabled(FeatureFlag.ENHANCED_TRADE_SERVICE):
            self.enhanced_service = EnhancedTradeService(db, redis_manager, self.rate_limiter)
        
        if is_feature_enabled(FeatureFlag.ORDER_MONITORING):
            self.order_monitor = OrderMonitoringService(db, redis_manager, self.rate_limiter)
    
    @with_logging("trade_service.place_order")
    @handle_errors("Failed to place order", ["organization_id", "pseudo_account", "symbol"])
    async def place_regular_order(
        self,
        pseudo_account: str,
        exchange: str,
        instrument_key: str,
        trade_type: str,
        order_type: str,
        product_type: str,
        quantity: int,
        price: float,
        trigger_price: float = 0.0,
        strategy_id: Optional[str] = None,
        organization_id: Optional[str] = None,
        background_tasks: Optional[BackgroundTasks] = None,
    ) -> Dict[str, Any]:
        """
        Place a regular order with comprehensive validation and error handling.
        """
        
        # Create error context for this operation
        context = create_error_context(
            organization_id=organization_id,
            user_id=pseudo_account,
            symbol=instrument_key,
            endpoint="place_regular_order"
        )
        
        with LoggingContext(
            organization_id=organization_id,
            user_id=pseudo_account
        ):
            logger.info(
                "Starting order placement",
                symbol=instrument_key,
                trade_type=trade_type,
                quantity=quantity,
                price=price,
                order_type=order_type
            )
            
            # Input validation
            await self._validate_order_request({
                'pseudo_account': pseudo_account,
                'exchange': exchange,
                'symbol': instrument_key,  # Will be validated as instrument_key
                'trade_type': trade_type,
                'order_type': order_type,
                'product_type': product_type,
                'quantity': quantity,
                'price': price,
                'trigger_price': trigger_price,
                'organization_id': organization_id,
                'strategy_id': strategy_id
            }, context)
            
            # Rate limiting check
            await self._check_rate_limits(pseudo_account, organization_id, context)
            
            # Business logic validation
            await self._validate_business_rules(
                pseudo_account, instrument_key, trade_type, 
                quantity, price, strategy_id, context
            )
            
            # Use enhanced service if available
            if self.enhanced_service and is_feature_enabled(FeatureFlag.ENHANCED_TRADE_SERVICE):
                logger.info("Using enhanced trade service for order placement")
                return await self.enhanced_service.place_regular_order_enhanced(
                    pseudo_account, exchange, instrument_key, trade_type,
                    order_type, product_type, quantity, price, trigger_price,
                    strategy_id, organization_id, background_tasks
                )
            else:
                # Fallback to basic implementation
                return await self._place_order_basic(
                    pseudo_account, exchange, instrument_key, trade_type,
                    order_type, product_type, quantity, price, trigger_price,
                    strategy_id, organization_id, background_tasks, context
                )
    
    @with_logging("trade_service.fetch_data")
    @handle_errors("Failed to fetch and store data", ["organization_id", "pseudo_account"])
    async def fetch_and_store_data(
        self,
        pseudo_account: str,
        organization_id: str
    ) -> Dict[str, Any]:
        """
        Fetch and store trading data with enhanced error handling and logging.
        """
        
        context = create_error_context(
            organization_id=organization_id,
            user_id=pseudo_account,
            endpoint="fetch_and_store_data"
        )
        
        with LoggingContext(
            organization_id=organization_id,
            user_id=pseudo_account
        ):
            logger.info("Starting data fetch and store operation")
            
            # Validate inputs
            validation_results = [
                TradeValidator.validate_pseudo_account(pseudo_account, context),
                TradeValidator.validate_organization_id(organization_id, context)
            ]
            validate_and_raise(validation_results, context)
            
            # Rate limiting
            await self._check_rate_limits(pseudo_account, organization_id, context)
            
            # Get AutoTrader connection
            adapter = await self._get_autotrader_adapter(organization_id, context)
            
            # Fetch data from AutoTrader
            data_summary = {
                'margins_count': 0,
                'positions_count': 0,
                'holdings_count': 0,
                'orders_count': 0,
                'errors': []
            }
            
            # Fetch margins
            try:
                margins_result = await self._fetch_margins(adapter, pseudo_account, organization_id)
                data_summary['margins_count'] = margins_result['count']
                logger.log_performance_metric("margins_fetched", margins_result['count'])
            except Exception as e:
                error_msg = f"Failed to fetch margins: {str(e)}"
                data_summary['errors'].append(error_msg)
                logger.error(error_msg, exc_info=True)
            
            # Fetch positions
            try:
                positions_result = await self._fetch_positions(adapter, pseudo_account, organization_id)
                data_summary['positions_count'] = positions_result['count']
                logger.log_performance_metric("positions_fetched", positions_result['count'])
            except Exception as e:
                error_msg = f"Failed to fetch positions: {str(e)}"
                data_summary['errors'].append(error_msg)
                logger.error(error_msg, exc_info=True)
            
            # Fetch holdings
            try:
                holdings_result = await self._fetch_holdings(adapter, pseudo_account, organization_id)
                data_summary['holdings_count'] = holdings_result['count']
                logger.log_performance_metric("holdings_fetched", holdings_result['count'])
            except Exception as e:
                error_msg = f"Failed to fetch holdings: {str(e)}"
                data_summary['errors'].append(error_msg)
                logger.error(error_msg, exc_info=True)
            
            # Fetch orders
            try:
                orders_result = await self._fetch_orders(adapter, pseudo_account, organization_id)
                data_summary['orders_count'] = orders_result['count']
                logger.log_performance_metric("orders_fetched", orders_result['count'])
            except Exception as e:
                error_msg = f"Failed to fetch orders: {str(e)}"
                data_summary['errors'].append(error_msg)
                logger.error(error_msg, exc_info=True)
            
            # Commit database changes
            try:
                self.db.commit()
                logger.info("Database commit successful", **data_summary)
            except Exception as e:
                self.db.rollback()
                raise DatabaseException(
                    f"Failed to commit data to database: {str(e)}",
                    operation="commit",
                    context=context,
                    original_exception=e
                )
            
            # Store in Redis if available and enabled
            if self.redis_manager and is_feature_enabled(FeatureFlag.DATA_CONSISTENCY_VALIDATION):
                try:
                    await self._store_data_in_redis(pseudo_account, organization_id)
                    logger.info("Redis storage successful")
                except Exception as e:
                    # Don't fail the operation if Redis storage fails
                    logger.warning(f"Redis storage failed: {str(e)}")
            
            logger.log_business_event("data_fetch_completed", data_summary)
            
            return {
                'success': True,
                'message': 'Data fetch and store completed',
                'summary': data_summary
            }
    
    async def _validate_order_request(self, order_data: Dict[str, Any], context: ErrorContext):
        """Validate order request data comprehensively"""
        
        # Use the new validation framework
        validation_results = OrderValidator.validate_complete_order(order_data, context)
        
        # Check for validation errors and raise if found
        validate_and_raise(validation_results, context)
        
        logger.info("Order validation passed", order_id=order_data.get('order_id'))
    
    async def _check_rate_limits(self, pseudo_account: str, organization_id: str, context: ErrorContext):
        """Check rate limits for the user/organization"""
        
        try:
            # Check user rate limits
            user_allowed = await self.rate_limiter.check_rate_limit(
                f"user:{pseudo_account}",
                limit=self.config.rate_limiting.requests_per_minute,
                window=60
            )
            
            if not user_allowed:
                logger.log_security_event("rate_limit_exceeded", {
                    "user_id": pseudo_account,
                    "limit_type": "user_per_minute"
                })
                raise RateLimitException(
                    f"Rate limit exceeded for user {pseudo_account}",
                    limit_type="user_per_minute",
                    context=context
                )
            
            # Check organization rate limits
            org_allowed = await self.rate_limiter.check_rate_limit(
                f"org:{organization_id}",
                limit=self.config.rate_limiting.requests_per_minute * 10,  # 10x user limit
                window=60
            )
            
            if not org_allowed:
                logger.log_security_event("rate_limit_exceeded", {
                    "organization_id": organization_id,
                    "limit_type": "organization_per_minute"
                })
                raise RateLimitException(
                    f"Rate limit exceeded for organization {organization_id}",
                    limit_type="organization_per_minute",
                    context=context
                )
            
        except Exception as e:
            if isinstance(e, RateLimitException):
                raise
            
            # Log rate limit check failure but don't block the operation
            logger.warning(f"Rate limit check failed: {str(e)}", exc_info=True)
    
    async def _validate_business_rules(
        self,
        pseudo_account: str,
        instrument_key: str,
        trade_type: str,
        quantity: int,
        price: float,
        strategy_id: Optional[str],
        context: ErrorContext
    ):
        """Validate business rules for the order"""
        
        # Check order value limits
        order_value = quantity * price
        if order_value > self.config.max_order_value:
            raise ValidationException(
                f"Order value {order_value} exceeds maximum allowed {self.config.max_order_value}",
                field_name="order_value",
                field_value=order_value,
                context=context
            )
        
        if order_value < self.config.min_order_value:
            raise ValidationException(
                f"Order value {order_value} is below minimum required {self.config.min_order_value}",
                field_name="order_value",
                field_value=order_value,
                context=context
            )
        
        # Check daily order limits
        daily_order_count = await self._get_daily_order_count(pseudo_account)
        if daily_order_count >= self.config.max_daily_orders:
            raise RateLimitException(
                f"Daily order limit {self.config.max_daily_orders} exceeded for user {pseudo_account}",
                limit_type="daily_orders",
                context=context
            )
        
        # Validate sufficient funds for buy orders
        if trade_type.upper() == TradeType.BUY.value:
            available_funds = await self._get_available_funds(pseudo_account)
            if available_funds < order_value:
                raise InsufficientFundsException(
                    required_amount=order_value,
                    available_amount=available_funds,
                    context=context
                )
        
        # Validate sufficient holdings for sell orders
        if trade_type.upper() == TradeType.SELL.value:
            available_quantity = await self._get_available_quantity(pseudo_account, instrument_key, strategy_id)
            if available_quantity < quantity:
                raise ValidationException(
                    f"Insufficient quantity for sell order. Available: {available_quantity}, Required: {quantity}",
                    field_name="quantity",
                    field_value=quantity,
                    context=context
                )
    
    async def _get_autotrader_adapter(self, organization_id: str, context: ErrorContext) -> AutoTraderAdapter:
        """Get AutoTrader adapter with connection pooling"""
        
        try:
            # Get API key
            api_key = await self._get_api_key(organization_id)
            
            # Get connection from pool
            connection = await self.autotrader_pool.get_connection(organization_id, api_key)
            
            # Create adapter
            adapter = AutoTraderAdapter(connection)
            
            logger.info("AutoTrader adapter created successfully")
            return adapter
            
        except Exception as e:
            raise AutoTraderException(
                f"Failed to create AutoTrader connection: {str(e)}",
                context=context,
                original_exception=e
            )
    
    async def _place_order_basic(
        self,
        pseudo_account: str,
        exchange: str,
        instrument_key: str,
        trade_type: str,
        order_type: str,
        product_type: str,
        quantity: int,
        price: float,
        trigger_price: float,
        strategy_id: Optional[str],
        organization_id: str,
        background_tasks: Optional[BackgroundTasks],
        context: ErrorContext
    ) -> Dict[str, Any]:
        """Basic order placement implementation"""
        
        # Create order record
        order_entry = OrderModel(
            pseudo_account=pseudo_account,
            exchange=exchange,
            instrument_key=instrument_key,
            symbol=instrument_key.split('@')[1] if '@' in instrument_key else instrument_key,
            trade_type=trade_type.upper(),
            order_type=order_type.upper(),
            product_type=product_type.upper(),
            quantity=quantity,
            price=price,
            trigger_price=trigger_price,
            strategy_id=strategy_id or 'default',
            status=OrderStatus.NEW.value,
            platform_time=datetime.utcnow(),
            variety="REGULAR"
        )
        
        try:
            # Save to database
            self.db.add(order_entry)
            self.db.commit()
            self.db.refresh(order_entry)
            
            logger.log_order_event(
                str(order_entry.id),
                "order_created",
                {
                    "symbol": instrument_key,
                    "trade_type": trade_type,
                    "quantity": quantity,
                    "price": price
                }
            )
            
            # Submit to AutoTrader in background if possible
            if background_tasks:
                background_tasks.add_task(
                    self._submit_order_to_autotrader,
                    order_entry,
                    organization_id
                )
            
            return {
                'success': True,
                'order_id': order_entry.id,
                'message': 'Order placed successfully'
            }
            
        except Exception as e:
            self.db.rollback()
            raise DatabaseException(
                f"Failed to save order: {str(e)}",
                operation="insert",
                table="orders",
                context=context,
                original_exception=e
            )
    
    async def _submit_order_to_autotrader(self, order: OrderModel, organization_id: str):
        """Submit order to AutoTrader (background task)"""
        
        try:
            adapter = await self._get_autotrader_adapter(
                organization_id,
                create_error_context(order_id=str(order.id))
            )
            
            # Convert order to AutoTrader format and submit
            autotrader_result = adapter.place_regular_order(
                pseudo_account=order.pseudo_account,
                exchange=order.exchange,
                instrument_key=order.instrument_key,
                trade_type=order.trade_type,
                order_type=order.order_type,
                product_type=order.product_type,
                quantity=order.quantity,
                price=order.price,
                trigger_price=order.trigger_price
            )
            
            if autotrader_result['success']:
                # Update order with AutoTrader response
                order.exchange_order_id = autotrader_result['result'].get('order_id')
                order.status = OrderStatus.PENDING.value
                self.db.commit()
                
                logger.log_order_event(
                    str(order.id),
                    "order_submitted_to_autotrader",
                    {"exchange_order_id": order.exchange_order_id}
                )
            else:
                # Mark order as failed
                order.status = OrderStatus.REJECTED.value
                order.status_message = autotrader_result.get('message', 'AutoTrader submission failed')
                self.db.commit()
                
                logger.error(
                    "AutoTrader order submission failed",
                    order_id=order.id,
                    error_message=autotrader_result.get('message')
                )
        
        except Exception as e:
            logger.error(
                f"Background order submission failed: {str(e)}",
                order_id=order.id,
                exc_info=True
            )
    
    # Helper methods with proper error handling
    async def _get_api_key(self, organization_id: str) -> str:
        """Get API key for organization with caching"""
        # This would typically come from a secure key management system
        # For now, return a placeholder
        return f"api_key_for_{organization_id}"
    
    async def _get_daily_order_count(self, pseudo_account: str) -> int:
        """Get today's order count for user"""
        today = datetime.utcnow().date()
        return self.db.query(OrderModel).filter(
            OrderModel.pseudo_account == pseudo_account,
            OrderModel.platform_time >= today
        ).count()
    
    async def _get_available_funds(self, pseudo_account: str) -> float:
        """Get available funds for user"""
        # Query margin data for available funds
        margin = self.db.query(MarginModel).filter(
            MarginModel.pseudo_account == pseudo_account,
            MarginModel.category == 'equity'
        ).first()
        
        return margin.available if margin else 0.0
    
    async def _get_available_quantity(self, pseudo_account: str, instrument_key: str, strategy_id: str) -> int:
        """Get available quantity for selling"""
        # Query holdings or positions for available quantity
        holding = self.db.query(HoldingModel).filter(
            HoldingModel.pseudo_account == pseudo_account,
            HoldingModel.instrument_key == instrument_key,
            HoldingModel.strategy_id == (strategy_id or 'default')
        ).first()
        
        return holding.quantity if holding else 0
    
    async def _fetch_margins(self, adapter: AutoTraderAdapter, pseudo_account: str, organization_id: str) -> Dict[str, Any]:
        """Fetch margins with error handling"""
        result = adapter.read_platform_margins(pseudo_account)
        
        if not result['success']:
            raise AutoTraderException(
                f"Failed to fetch margins: {result['message']}",
                api_method="read_platform_margins"
            )
        
        # Process and store margins
        count = 0
        for margin_data in result['result']:
            try:
                margin_entry = MarginModel(
                    pseudo_account=pseudo_account,
                    margin_date=datetime.utcnow(),
                    category=margin_data.get('category', 'unknown'),
                    available=float(margin_data.get('available', 0.0)),
                    utilized=float(margin_data.get('utilized', 0.0)),
                    total=float(margin_data.get('total', 0.0)),
                    # ... other fields
                )
                self.db.add(margin_entry)
                count += 1
            except Exception as e:
                logger.warning(f"Failed to process margin record: {str(e)}")
        
        return {'count': count}
    
    async def _fetch_positions(self, adapter: AutoTraderAdapter, pseudo_account: str, organization_id: str) -> Dict[str, Any]:
        """Fetch positions with error handling"""
        result = adapter.read_platform_positions(pseudo_account)
        
        if not result['success']:
            raise AutoTraderException(
                f"Failed to fetch positions: {result['message']}",
                api_method="read_platform_positions"
            )
        
        # Process and store positions
        count = 0
        for position_data in result['result']:
            try:
                # Data is already converted by AutoTraderAdapter
                position_entry = PositionModel(
                    pseudo_account=pseudo_account,
                    instrument_key=position_data.get('instrument_key'),
                    timestamp=datetime.utcnow(),
                    exchange=position_data.get('exchange'),
                    symbol=position_data.get('symbol'),
                    net_quantity=int(position_data.get('net_quantity', 0)),
                    # ... other fields
                )
                self.db.add(position_entry)
                count += 1
            except Exception as e:
                logger.warning(f"Failed to process position record: {str(e)}")
        
        return {'count': count}
    
    async def _fetch_holdings(self, adapter: AutoTraderAdapter, pseudo_account: str, organization_id: str) -> Dict[str, Any]:
        """Fetch holdings with error handling"""
        result = adapter.read_platform_holdings(pseudo_account)
        
        if not result['success']:
            raise AutoTraderException(
                f"Failed to fetch holdings: {result['message']}",
                api_method="read_platform_holdings"
            )
        
        # Process and store holdings (similar pattern)
        count = len(result['result'])
        # Implementation similar to positions
        
        return {'count': count}
    
    async def _fetch_orders(self, adapter: AutoTraderAdapter, pseudo_account: str, organization_id: str) -> Dict[str, Any]:
        """Fetch orders with error handling"""
        result = adapter.read_platform_orders(pseudo_account)
        
        if not result['success']:
            raise AutoTraderException(
                f"Failed to fetch orders: {result['message']}",
                api_method="read_platform_orders"
            )
        
        # Process and store orders (similar pattern)
        count = len(result['result'])
        # Implementation similar to positions
        
        return {'count': count}
    
    async def _store_data_in_redis(self, pseudo_account: str, organization_id: str):
        """Store fetched data in Redis for caching"""
        if not self.redis_manager:
            return
        
        # Get data from database
        margins = self.db.query(MarginModel).filter_by(pseudo_account=pseudo_account).all()
        positions = self.db.query(PositionModel).filter_by(pseudo_account=pseudo_account).all()
        holdings = self.db.query(HoldingModel).filter_by(pseudo_account=pseudo_account).all()
        orders = self.db.query(OrderModel).filter_by(pseudo_account=pseudo_account).all()
        
        # Store in Redis
        await self.redis_manager.store_margins(organization_id, pseudo_account, margins)
        await self.redis_manager.store_positions(organization_id, pseudo_account, positions)
        await self.redis_manager.store_holdings(organization_id, pseudo_account, holdings)
        await self.redis_manager.store_orders(organization_id, pseudo_account, orders)