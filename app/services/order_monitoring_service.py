# app/services/order_monitoring_service.py
import asyncio
import logging
from typing import Dict, List, Optional, Set
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from shared_architecture.enums import OrderStatus, PollingFrequency
from shared_architecture.db.models.order_model import OrderModel
from shared_architecture.db.models.margin_model import MarginModel
from shared_architecture.db.models.position_model import PositionModel
from shared_architecture.connections.autotrader_pool import autotrader_pool
from shared_architecture.utils.redis_data_manager import RedisDataManager
from app.utils.rate_limiter import RateLimiter
from app.core.config import settings

logger = logging.getLogger(__name__)

class OrderMonitoringService:
    """
    Service for monitoring order lifecycle and polling for status updates.
    Features:
    - Rate-limited polling based on order age
    - Automatic margin refresh on order placement
    - Position refresh on order completion
    - Redis sync for real-time updates
    """
    
    def __init__(self, db: Session, redis_manager: Optional[RedisDataManager] = None, rate_limiter: Optional[RateLimiter] = None):
        self.db = db
        self.redis_manager = redis_manager
        self.rate_limiter = rate_limiter
        
        # Tracking active polling sessions
        self.active_polls: Dict[int, asyncio.Task] = {}  # order_id -> task
        self.poll_counts: Dict[int, int] = {}  # order_id -> poll_count
        
        # Configuration
        self.max_poll_duration = 300  # 5 minutes max polling
        self.max_polls_per_order = 60  # Maximum polls per order
        
    async def start_order_monitoring(self, order_id: int, organization_id: str, pseudo_account: str) -> bool:
        """
        Start monitoring an order after placement.
        
        Args:
            order_id: Internal order ID
            organization_id: Organization ID
            pseudo_account: Trading account
            
        Returns:
            Success status
        """
        try:
            # Check if already monitoring this order
            if order_id in self.active_polls:
                logger.warning(f"Order {order_id} is already being monitored")
                return True
            
            # Get order from database
            order = self.db.query(OrderModel).filter_by(id=order_id).first()
            if not order:
                logger.error(f"Order {order_id} not found in database")
                return False
            
            # Immediate actions after order placement
            await self._perform_immediate_actions(order, organization_id, pseudo_account)
            
            # Start polling task
            poll_task = asyncio.create_task(
                self._poll_order_status(order_id, organization_id, pseudo_account)
            )
            self.active_polls[order_id] = poll_task
            self.poll_counts[order_id] = 0
            
            logger.info(f"Started monitoring order {order_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start monitoring order {order_id}: {e}")
            return False
    
    async def stop_order_monitoring(self, order_id: int, reason: str = "Manual stop"):
        """Stop monitoring an order"""
        if order_id in self.active_polls:
            task = self.active_polls[order_id]
            task.cancel()
            del self.active_polls[order_id]
            if order_id in self.poll_counts:
                del self.poll_counts[order_id]
            logger.info(f"Stopped monitoring order {order_id}: {reason}")
    
    async def _perform_immediate_actions(self, order: OrderModel, organization_id: str, pseudo_account: str):
        """Perform immediate actions after order placement"""
        try:
            # 1. Refresh margins immediately
            await self._refresh_margins(organization_id, pseudo_account)
            
            # 2. Update Redis with new order
            if self.redis_manager:
                orders = self.db.query(OrderModel).filter_by(
                    pseudo_account=pseudo_account,
                    strategy_id=order.strategy_id
                ).all()
                await self.redis_manager.store_orders(
                    organization_id, pseudo_account, orders, order.strategy_id
                )
            
            logger.info(f"Completed immediate actions for order {order.id}")
            
        except Exception as e:
            logger.error(f"Failed immediate actions for order {order.id}: {e}")
    
    async def _poll_order_status(self, order_id: int, organization_id: str, pseudo_account: str):
        """
        Poll order status until completion or timeout.
        Implements smart polling frequency based on order age.
        """
        start_time = datetime.utcnow()
        last_status = None
        
        try:
            while True:
                # Check if we should stop polling
                elapsed = (datetime.utcnow() - start_time).total_seconds()
                if elapsed > self.max_poll_duration:
                    logger.info(f"Polling timeout for order {order_id} after {elapsed}s")
                    break
                
                if self.poll_counts.get(order_id, 0) >= self.max_polls_per_order:
                    logger.info(f"Max polls reached for order {order_id}")
                    break
                
                # Get current order status from database
                order = self.db.query(OrderModel).filter_by(id=order_id).first()
                if not order:
                    logger.error(f"Order {order_id} not found during polling")
                    break
                
                # Check if order reached terminal state
                current_status = OrderStatus(order.status) if order.status else OrderStatus.NEW
                if current_status.is_terminal():
                    logger.info(f"Order {order_id} reached terminal state: {current_status}")
                    await self._handle_order_completion(order, organization_id, pseudo_account)
                    break
                
                # Check rate limits before polling AutoTrader
                if self.rate_limiter:
                    can_poll = await self.rate_limiter.account_rate_limit(
                        pseudo_account, organization_id, limit=100, window=60
                    )
                    if not can_poll:
                        logger.warning(f"Rate limited for order {order_id}, waiting...")
                        await asyncio.sleep(5)
                        continue
                
                # Poll AutoTrader for status update
                await self._poll_autotrader_status(order, organization_id)
                
                # Update poll counter
                self.poll_counts[order_id] = self.poll_counts.get(order_id, 0) + 1
                
                # Determine next poll interval based on order age
                age_seconds = int(elapsed)
                frequency = PollingFrequency.get_frequency_for_age(age_seconds)
                
                # Status change notification
                if last_status != current_status:
                    logger.info(f"Order {order_id} status changed: {last_status} -> {current_status}")
                    last_status = current_status
                
                # Wait before next poll
                await asyncio.sleep(frequency.value)
                
        except asyncio.CancelledError:
            logger.info(f"Polling cancelled for order {order_id}")
        except Exception as e:
            logger.error(f"Error during polling for order {order_id}: {e}")
        finally:
            # Clean up
            if order_id in self.active_polls:
                del self.active_polls[order_id]
            if order_id in self.poll_counts:
                del self.poll_counts[order_id]
    
    async def _poll_autotrader_status(self, order: OrderModel, organization_id: str):
        """Poll AutoTrader for order status update"""
        try:
            # Get AutoTrader connection
            with autotrader_pool.get_connection_context(organization_id) as autotrader_conn:
                # Use exchange_order_id or our internal order_id
                order_ref = order.exchange_order_id or str(order.id)
                
                # Get status from AutoTrader
                response = autotrader_conn.get_order_status(order_id=order_ref)
                
                if response.success():
                    # Update order with new status
                    result = response.result
                    
                    old_status = order.status
                    order.status = result.get('status', order.status)
                    order.filled_quantity = result.get('filled_quantity', order.filled_quantity)
                    order.average_price = result.get('average_price', order.average_price)
                    order.pending_quantity = order.quantity - (order.filled_quantity or 0)
                    
                    # Update exchange order ID if provided
                    if result.get('exchange_order_id'):
                        order.exchange_order_id = result['exchange_order_id']
                    
                    self.db.commit()
                    
                    # Log status changes
                    if old_status != order.status:
                        logger.info(f"Order {order.id} status updated: {old_status} -> {order.status}")
                        
                        # Sync to Redis on status change
                        if self.redis_manager:
                            await self._sync_order_to_redis(order, organization_id)
                
                else:
                    logger.warning(f"Failed to get status for order {order.id}: {response.message}")
                    
        except Exception as e:
            logger.error(f"Error polling AutoTrader for order {order.id}: {e}")
    
    async def _handle_order_completion(self, order: OrderModel, organization_id: str, pseudo_account: str):
        """Handle actions when order reaches terminal state"""
        try:
            current_status = OrderStatus(order.status)
            
            if current_status in {OrderStatus.COMPLETE, OrderStatus.PARTIALLY_FILLED}:
                # Refresh positions after execution
                await self._refresh_positions(organization_id, pseudo_account, order.strategy_id)
                
                # Trigger position update in trade service
                from app.tasks.sync_to_redis_task import sync_on_data_change
                sync_on_data_change.delay(
                    organization_id, pseudo_account, 'positions', order.strategy_id
                )
                
            # Update Redis with final order state
            if self.redis_manager:
                await self._sync_order_to_redis(order, organization_id)
            
            logger.info(f"Completed order {order.id} handling with status {current_status}")
            
        except Exception as e:
            logger.error(f"Error handling completion for order {order.id}: {e}")
    
    async def _refresh_margins(self, organization_id: str, pseudo_account: str):
        """Refresh margin data from AutoTrader"""
        try:
            with autotrader_pool.get_connection_context(organization_id) as autotrader_conn:
                response = autotrader_conn.read_platform_margins(pseudo_account)
                
                if response.success():
                    # Clear existing margins for this account
                    self.db.query(MarginModel).filter_by(pseudo_account=pseudo_account).delete()
                    
                    # Add new margin data
                    for margin_data in response.result:
                        margin_dict = margin_data.__dict__ if hasattr(margin_data, '__dict__') else margin_data
                        
                        margin_entry = MarginModel(
                            pseudo_account=pseudo_account,
                            margin_date=datetime.utcnow(),
                            category=margin_dict.get('category', 'UNKNOWN'),
                            available=float(margin_dict.get('available', 0.0)),
                            utilized=float(margin_dict.get('utilized', 0.0)),
                            total=float(margin_dict.get('total', 0.0)),
                            # Add other fields...
                            stock_broker='StocksDeveloper',
                            trading_account=pseudo_account
                        )
                        self.db.add(margin_entry)
                    
                    self.db.commit()
                    
                    # Sync to Redis
                    if self.redis_manager:
                        margins = self.db.query(MarginModel).filter_by(pseudo_account=pseudo_account).all()
                        await self.redis_manager.store_margins(organization_id, pseudo_account, margins)
                    
                    logger.info(f"Refreshed margins for {pseudo_account}")
                
        except Exception as e:
            logger.error(f"Error refreshing margins for {pseudo_account}: {e}")
    
    async def _refresh_positions(self, organization_id: str, pseudo_account: str, strategy_id: Optional[str] = None):
        """Refresh position data from AutoTrader"""
        try:
            with autotrader_pool.get_connection_context(organization_id) as autotrader_conn:
                response = autotrader_conn.read_platform_positions(pseudo_account)
                
                if response.success():
                    # This would involve updating positions...
                    # Implementation depends on how positions are managed
                    logger.info(f"Refreshed positions for {pseudo_account}, strategy: {strategy_id}")
                    
        except Exception as e:
            logger.error(f"Error refreshing positions for {pseudo_account}: {e}")
    
    async def _sync_order_to_redis(self, order: OrderModel, organization_id: str):
        """Sync single order to Redis"""
        if not self.redis_manager:
            return
            
        try:
            # Get all orders for this strategy to maintain consistency
            orders = self.db.query(OrderModel).filter_by(
                pseudo_account=order.pseudo_account,
                strategy_id=order.strategy_id
            ).all()
            
            await self.redis_manager.store_orders(
                organization_id, order.pseudo_account, orders, order.strategy_id
            )
            
        except Exception as e:
            logger.error(f"Error syncing order {order.id} to Redis: {e}")
    
    def get_monitoring_stats(self) -> Dict:
        """Get statistics about current monitoring"""
        return {
            "active_orders": len(self.active_polls),
            "total_polls": sum(self.poll_counts.values()),
            "orders_by_poll_count": dict(self.poll_counts)
        }