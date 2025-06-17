# app/services/enhanced_trade_service.py
import json
import logging
import uuid
from typing import Optional, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from fastapi import HTTPException, BackgroundTasks

from shared_architecture.enums import OrderStatus, OrderLifecycleAction
from shared_architecture.db.models.order_model import OrderModel
from shared_architecture.db.models.order_discrepancy_model import OrderDiscrepancyModel
from shared_architecture.connections.autotrader_pool import autotrader_pool
from shared_architecture.utils.redis_data_manager import RedisDataManager
from shared_architecture.utils.instrument_key_helper import instrument_key_to_symbol
from app.services.order_monitoring_service import OrderMonitoringService
from app.utils.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

class EnhancedTradeService:
    """
    Enhanced trade service with transaction consistency and order monitoring.
    Implements two-phase commit pattern for AutoTrader operations.
    """
    
    def __init__(self, db: Session, redis_manager: Optional[RedisDataManager] = None, rate_limiter: Optional[RateLimiter] = None):
        self.db = db
        self.redis_manager = redis_manager
        self.rate_limiter = rate_limiter
        self.order_monitor = OrderMonitoringService(db, redis_manager, rate_limiter)
    
    async def place_regular_order_enhanced(
        self,
        pseudo_account: str,
        exchange: str,
        instrument_key: str,
        tradeType: str,
        orderType: str,
        productType: str,
        quantity: int,
        price: float,
        triggerPrice: float = 0.0,
        strategy_id: Optional[str] = None,
        organization_id: Optional[str] = None,
        background_tasks: Optional[BackgroundTasks] = None,
    ) -> Dict:
        """
        Enhanced order placement with transaction consistency.
        
        Flow:
        1. Validate inputs and rate limits
        2. Create request ID for idempotency
        3. Send to AutoTrader FIRST
        4. If AutoTrader succeeds, save to database
        5. If DB save fails, log discrepancy (DON'T cancel AutoTrader order)
        6. Start order monitoring
        """
        # Generate unique request ID for idempotency
        request_id = str(uuid.uuid4())
        
        try:
            # Phase 1: Validation and preparation
            await self._validate_order_request(pseudo_account, organization_id, strategy_id, tradeType, instrument_key, quantity)
            
            # Phase 2: Send to AutoTrader FIRST
            autotrader_response = await self._send_regular_order_to_autotrader(
                organization_id, pseudo_account, exchange, instrument_key,
                tradeType, orderType, productType, quantity, price, triggerPrice
            )
            
            if not autotrader_response['success']:
                # AutoTrader failed - no database changes needed
                raise HTTPException(
                    status_code=400,
                    detail=f"Order rejected by broker: {autotrader_response['message']}"
                )
            
            # Phase 3: Save to database with AutoTrader details
            order_entry = await self._create_order_in_database(
                pseudo_account, exchange, instrument_key, tradeType, orderType,
                productType, quantity, price, triggerPrice, strategy_id,
                autotrader_response, request_id
            )
            
            if not order_entry:
                # Database save failed - log discrepancy
                await self._log_order_discrepancy(
                    organization_id, pseudo_account, strategy_id,
                    OrderLifecycleAction.PLACE, "DB_SAVE_FAILED",
                    autotrader_response, None, 
                    "Database save failed after successful AutoTrader order placement"
                )
                
                # DON'T cancel the AutoTrader order - let it execute
                # Return success with warning
                return {
                    "success": True,
                    "message": "Order placed in AutoTrader but database save failed. Order will be reconciled.",
                    "autotrader_order_id": autotrader_response.get('order_id'),
                    "warning": "Database discrepancy logged for manual review"
                }
            
            # Phase 4: Start monitoring
            await self.order_monitor.start_order_monitoring(
                order_entry.id, organization_id, pseudo_account
            )
            
            logger.info(f"Successfully placed order {order_entry.id} with AutoTrader order {autotrader_response.get('order_id')}")
            
            return {
                "success": True,
                "message": "Order placed successfully",
                "order_id": order_entry.id,
                "autotrader_order_id": autotrader_response.get('order_id'),
                "status": order_entry.status
            }
            
        except HTTPException:
            raise  # Re-raise HTTP exceptions
        except Exception as e:
            logger.error(f"Unexpected error in place_regular_order_enhanced: {e}")
            raise HTTPException(status_code=500, detail="Internal server error during order placement")
    
    async def _validate_order_request(self, pseudo_account: str, organization_id: str, strategy_id: str, trade_type: str, instrument_key: str, quantity: int):
        """Validate order request before sending to AutoTrader"""
        if not organization_id:
            raise HTTPException(status_code=400, detail="Organization ID is required")
        
        if not strategy_id:
            raise HTTPException(status_code=400, detail="Strategy ID is required")
        
        # Check rate limits
        if self.rate_limiter:
            rate_limit_ok = await self.rate_limiter.account_rate_limit(pseudo_account, organization_id)
            if not rate_limit_ok:
                raise HTTPException(status_code=429, detail="Too Many Requests")
        
        # Validate instrument exists
        # Add your instrument validation logic here
        
        # Check for conflicting orders
        await self._check_for_conflicting_orders(pseudo_account, instrument_key, trade_type, strategy_id)
        
        # Handle holding to position transition for SELL orders
        if trade_type == "SELL":
            await self._handle_holding_to_position_transition(pseudo_account, instrument_key, quantity, strategy_id)
    
    async def _send_regular_order_to_autotrader(
        self, organization_id: str, pseudo_account: str, exchange: str,
        instrument_key: str, trade_type: str, order_type: str,
        product_type: str, quantity: int, price: float, trigger_price: float
    ) -> Dict:
        """Send order to AutoTrader and return response"""
        try:
            with autotrader_pool.get_connection_context(organization_id) as autotrader_conn:
                # Convert instrument_key to AutoTrader symbol format if needed
                symbol = instrument_key_to_symbol(instrument_key)
                
                response = autotrader_conn.place_regular_order(
                    pseudo_account=pseudo_account,
                    exchange=exchange,
                    symbol=symbol,
                    tradeType=trade_type,
                    orderType=order_type,
                    productType=product_type,
                    quantity=quantity,
                    price=price,
                    triggerPrice=trigger_price
                )
                
                if response.success():
                    return {
                        'success': True,
                        'order_id': response.result.get('order_id'),
                        'exchange_order_id': response.result.get('exchange_order_id'),
                        'status': response.result.get('status', 'PENDING'),
                        'message': response.message,
                        'full_response': response.result
                    }
                else:
                    return {
                        'success': False,
                        'message': response.message,
                        'error_code': getattr(response, 'error_code', None)
                    }
                    
        except Exception as e:
            logger.error(f"AutoTrader API call failed: {e}")
            return {
                'success': False,
                'message': f"AutoTrader connection failed: {str(e)}",
                'error': str(e)
            }
    
    async def _create_order_in_database(
        self, pseudo_account: str, exchange: str, instrument_key: str,
        trade_type: str, order_type: str, product_type: str,
        quantity: int, price: float, trigger_price: float,
        strategy_id: str, autotrader_response: Dict, request_id: str
    ) -> Optional[OrderModel]:
        """Create order entry in database with AutoTrader details"""
        try:
            symbol = instrument_key_to_symbol(instrument_key)
            
            order_entry = OrderModel(
                pseudo_account=pseudo_account,
                exchange=exchange,
                symbol=symbol,
                trade_type=trade_type,
                order_type=order_type,
                product_type=product_type,
                quantity=quantity,
                price=price,
                trigger_price=trigger_price,
                strategy_id=strategy_id,
                instrument_key=instrument_key,
                
                # AutoTrader details
                exchange_order_id=autotrader_response.get('exchange_order_id'),
                platform=autotrader_response.get('order_id'),  # Store AutoTrader order ID
                status=autotrader_response.get('status', 'PENDING'),
                
                # Metadata
                platform_time=datetime.utcnow(),
                variety="REGULAR",
                client_id=request_id,  # Use request_id for idempotency
                
                # Initialize quantities
                filled_quantity=0,
                pending_quantity=quantity,
                
                # Broker details
                stock_broker='StocksDeveloper',
                trading_account=pseudo_account
            )
            
            self.db.add(order_entry)
            self.db.commit()
            self.db.refresh(order_entry)
            
            logger.info(f"Created order {order_entry.id} in database")
            return order_entry
            
        except Exception as e:
            logger.error(f"Failed to save order to database: {e}")
            self.db.rollback()
            return None
    
    async def _log_order_discrepancy(
        self, organization_id: str, pseudo_account: str, strategy_id: str,
        operation_type: OrderLifecycleAction, discrepancy_type: str,
        autotrader_response: Dict, order_id: Optional[int],
        error_message: str, original_request: Optional[Dict] = None
    ):
        """Log order discrepancy for later reconciliation"""
        try:
            discrepancy = OrderDiscrepancyModel(
                organization_id=organization_id,
                pseudo_account=pseudo_account,
                strategy_id=strategy_id,
                order_id=order_id,
                autotrader_order_id=autotrader_response.get('order_id'),
                exchange_order_id=autotrader_response.get('exchange_order_id'),
                operation_type=operation_type.value,
                discrepancy_type=discrepancy_type,
                original_request=json.dumps(original_request) if original_request else None,
                autotrader_response=json.dumps(autotrader_response),
                error_message=error_message,
                severity='HIGH',  # Order placement failures are high severity
                requires_manual_review=True
            )
            
            self.db.add(discrepancy)
            self.db.commit()
            
            logger.error(f"Logged order discrepancy: {discrepancy_type} for org {organization_id}")
            
        except Exception as e:
            logger.error(f"Failed to log order discrepancy: {e}")
    
    async def cancel_order_enhanced(
        self, order_id: int, organization_id: str, reason: str = "User request"
    ) -> Dict:
        """
        Enhanced order cancellation with transaction consistency.
        
        Flow:
        1. Get order from database
        2. Send cancel to AutoTrader FIRST
        3. If AutoTrader succeeds, update database
        4. If DB update fails, log discrepancy
        """
        try:
            # Get order from database
            order = self.db.query(OrderModel).filter_by(id=order_id).first()
            if not order:
                raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
            
            # Check if order can be cancelled
            current_status = OrderStatus(order.status) if order.status else OrderStatus.NEW
            if current_status.is_terminal():
                raise HTTPException(
                    status_code=400, 
                    detail=f"Cannot cancel order with status {current_status}"
                )
            
            # Send cancel to AutoTrader FIRST
            cancel_response = await self._send_cancel_to_autotrader(organization_id, order)
            
            if not cancel_response['success']:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cancel rejected by broker: {cancel_response['message']}"
                )
            
            # Update database
            try:
                order.status = OrderStatus.CANCELLED.value
                order.status_message = reason
                order.modified_time = datetime.utcnow()
                self.db.commit()
                
                # Stop monitoring
                await self.order_monitor.stop_order_monitoring(order_id, "Order cancelled")
                
                logger.info(f"Successfully cancelled order {order_id}")
                
                return {
                    "success": True,
                    "message": "Order cancelled successfully",
                    "order_id": order_id,
                    "status": order.status
                }
                
            except Exception as e:
                # AutoTrader cancel succeeded but DB update failed
                await self._log_order_discrepancy(
                    organization_id, order.pseudo_account, order.strategy_id,
                    OrderLifecycleAction.CANCEL, "DB_UPDATE_FAILED",
                    cancel_response, order_id,
                    f"Database update failed after successful AutoTrader cancel: {str(e)}"
                )
                
                return {
                    "success": True,
                    "message": "Order cancelled in AutoTrader but database update failed",
                    "order_id": order_id,
                    "warning": "Database discrepancy logged for manual review"
                }
                
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Unexpected error in cancel_order_enhanced: {e}")
            raise HTTPException(status_code=500, detail="Internal server error during order cancellation")
    
    async def _send_cancel_to_autotrader(self, organization_id: str, order: OrderModel) -> Dict:
        """Send cancel request to AutoTrader"""
        try:
            with autotrader_pool.get_connection_context(organization_id) as autotrader_conn:
                # Use exchange_order_id or platform order_id
                platform_id = order.exchange_order_id or order.platform or str(order.id)
                
                response = autotrader_conn.cancel_order_by_platform_id(
                    pseudo_account=order.pseudo_account,
                    platform_id=platform_id
                )
                
                if response.success():
                    return {
                        'success': True,
                        'message': response.message,
                        'result': response.result
                    }
                else:
                    return {
                        'success': False,
                        'message': response.message
                    }
                    
        except Exception as e:
            logger.error(f"AutoTrader cancel failed: {e}")
            return {
                'success': False,
                'message': f"AutoTrader connection failed: {str(e)}"
            }
    
    # Placeholder methods - implement based on existing trade_service.py logic
    async def _check_for_conflicting_orders(self, pseudo_account: str, instrument_key: str, trade_type: str, strategy_id: str):
        """Check for conflicting orders - implement existing logic"""
        pass
    
    async def _handle_holding_to_position_transition(self, pseudo_account: str, instrument_key: str, quantity: int, strategy_id: str):
        """Handle holding to position transition - implement existing logic"""
        pass