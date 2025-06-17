import logging
from typing import List, Dict, Optional, Set
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func

from shared_architecture.db.models.order_model import OrderModel
from shared_architecture.db.models.order_event_model import OrderEventModel
from shared_architecture.db.models.position_model import PositionModel
from shared_architecture.db.models.strategy_model import StrategyModel
from shared_architecture.enums import OrderStatus, OrderEvent
from app.services.strategy_management_service import StrategyManagementService

logger = logging.getLogger(__name__)

class ExternalOrderDetector:
    """
    Detects and processes orders placed outside AutoTrader
    This runs during each data refresh cycle
    """
    
    def __init__(self, db: Session):
        self.db = db
        self.strategy_service = StrategyManagementService(db)
        self._processed_external_orders: Set[str] = set()
        
    async def detect_and_process_external_orders(self, 
                                                fetched_orders: List[Dict],
                                                pseudo_account: str,
                                                organization_id: str) -> Dict:
        """
        Main entry point called during data refresh
        Compares fetched orders with internal database
        
        Args:
            fetched_orders: Orders fetched from broker API
            pseudo_account: Account identifier
            organization_id: Organization identifier
            
        Returns:
            Summary of external orders detected and processed
        """
        try:
            external_orders = []
            updated_orders = []
            new_fills = []
            
            # Get all internal order IDs for this account
            internal_order_ids = self._get_internal_order_ids(pseudo_account)
            
            for broker_order in fetched_orders:
                broker_order_id = broker_order.get('order_id')
                
                # Check if this order exists in our system
                internal_order = self.db.query(OrderModel).filter_by(
                    original_order_id=broker_order_id,
                    pseudo_account=pseudo_account
                ).first()
                
                if not internal_order:
                    # This is an external order - create it
                    external_order = await self._create_external_order(
                        broker_order, pseudo_account, organization_id
                    )
                    external_orders.append(external_order)
                else:
                    # Check for status updates or new fills
                    updates = await self._check_order_updates(internal_order, broker_order)
                    if updates:
                        updated_orders.append(updates)
            
            # Process all detected external orders
            if external_orders:
                await self._process_external_orders(external_orders)
                
            # Handle position discrepancies
            position_adjustments = await self._reconcile_positions(
                fetched_orders, pseudo_account
            )
            
            return {
                'external_orders_detected': len(external_orders),
                'orders_updated': len(updated_orders),
                'position_adjustments': position_adjustments,
                'timestamp': datetime.utcnow()
            }
            
        except Exception as e:
            logger.error(f"Error detecting external orders: {str(e)}")
            raise
    
    def _get_internal_order_ids(self, pseudo_account: str) -> Set[str]:
        """Get all internal order IDs for comparison"""
        orders = self.db.query(OrderModel.original_order_id).filter_by(
            pseudo_account=pseudo_account
        ).all()
        return {order.original_order_id for order in orders}
    
    async def _create_external_order(self, broker_order: Dict, 
                                   pseudo_account: str,
                                   organization_id: str) -> OrderModel:
        """Create order record for externally placed order"""
        
        # Generate internal order ID
        order_id = f"EXT_{broker_order.get('order_id')}"
        
        # Determine order details
        order_model = OrderModel(
            order_id=order_id,
            original_order_id=broker_order.get('order_id'),
            pseudo_account=pseudo_account,
            organization_id=organization_id,
            trading_symbol=broker_order.get('tradingsymbol'),
            instrument_key=broker_order.get('instrument_key', ''),
            exchange=broker_order.get('exchange'),
            order_type=broker_order.get('order_type', 'MARKET'),
            trade_type=broker_order.get('transaction_type', '').upper(),
            quantity=broker_order.get('quantity', 0),
            price=broker_order.get('price', 0),
            trigger_price=broker_order.get('trigger_price', 0),
            status=broker_order.get('status', OrderStatus.NEW.value),
            filled_quantity=broker_order.get('filled_quantity', 0),
            average_price=broker_order.get('average_price', 0),
            product_type=broker_order.get('product', 'MIS'),
            validity=broker_order.get('validity', 'DAY'),
            variety=broker_order.get('variety', 'regular'),
            source_type='EXTERNAL',
            discovery_timestamp=datetime.utcnow(),
            external_metadata={
                'discovered_at': datetime.utcnow().isoformat(),
                'broker_timestamp': broker_order.get('order_timestamp'),
                'broker_data': broker_order
            },
            created_at=self._parse_broker_timestamp(broker_order.get('order_timestamp')),
            updated_at=datetime.utcnow()
        )
        
        # Create order placed event
        order_event = OrderEventModel(
            order_id=order_id,
            event_type=OrderEvent.ORDER_PLACED.value,
            event_timestamp=order_model.created_at,
            event_data={
                'source': 'EXTERNAL',
                'discovered_at': datetime.utcnow().isoformat(),
                'original_order_id': broker_order.get('order_id')
            },
            pseudo_account=pseudo_account,
            organization_id=organization_id
        )
        
        self.db.add(order_model)
        self.db.add(order_event)
        
        # Create additional events based on current status
        if broker_order.get('status') in ['COMPLETE', 'FILLED']:
            fill_event = OrderEventModel(
                order_id=order_id,
                event_type=OrderEvent.ORDER_FILLED.value,
                event_timestamp=self._parse_broker_timestamp(
                    broker_order.get('exchange_update_timestamp', broker_order.get('order_timestamp'))
                ),
                event_data={
                    'filled_quantity': broker_order.get('filled_quantity'),
                    'average_price': broker_order.get('average_price')
                },
                pseudo_account=pseudo_account,
                organization_id=organization_id
            )
            self.db.add(fill_event)
        
        return order_model
    
    async def _check_order_updates(self, internal_order: OrderModel, 
                                 broker_order: Dict) -> Optional[Dict]:
        """Check if internal order needs updates from broker data"""
        updates = {}
        events = []
        
        # Check status changes
        broker_status = broker_order.get('status')
        if broker_status and broker_status != internal_order.status:
            updates['status'] = broker_status
            
            # Create appropriate event
            if broker_status == 'COMPLETE':
                events.append({
                    'type': OrderEvent.ORDER_FILLED.value,
                    'data': {
                        'filled_quantity': broker_order.get('filled_quantity'),
                        'average_price': broker_order.get('average_price')
                    }
                })
            elif broker_status == 'CANCELLED':
                events.append({
                    'type': OrderEvent.ORDER_CANCELLED.value,
                    'data': {'reason': 'Cancelled externally'}
                })
            elif broker_status == 'REJECTED':
                events.append({
                    'type': OrderEvent.ORDER_REJECTED.value,
                    'data': {'reason': broker_order.get('status_message', 'Rejected by broker')}
                })
        
        # Check fill updates
        broker_filled = broker_order.get('filled_quantity', 0)
        if broker_filled > internal_order.filled_quantity:
            updates['filled_quantity'] = broker_filled
            updates['average_price'] = broker_order.get('average_price', 0)
            
            events.append({
                'type': OrderEvent.ORDER_PARTIALLY_FILLED.value,
                'data': {
                    'filled_quantity': broker_filled,
                    'last_fill_quantity': broker_filled - internal_order.filled_quantity,
                    'average_price': broker_order.get('average_price')
                }
            })
        
        # Apply updates if any
        if updates:
            for key, value in updates.items():
                setattr(internal_order, key, value)
            internal_order.updated_at = datetime.utcnow()
            
            # Create events
            for event in events:
                order_event = OrderEventModel(
                    order_id=internal_order.order_id,
                    event_type=event['type'],
                    event_timestamp=datetime.utcnow(),
                    event_data=event['data'],
                    pseudo_account=internal_order.pseudo_account,
                    organization_id=internal_order.organization_id
                )
                self.db.add(order_event)
            
            return {'order_id': internal_order.order_id, 'updates': updates, 'events': events}
        
        return None
    
    async def _process_external_orders(self, external_orders: List[OrderModel]):
        """Process detected external orders"""
        for order in external_orders:
            # Try to assign to strategy
            strategy_assignment = await self._assign_to_strategy(order)
            
            if strategy_assignment:
                order.strategy_id = strategy_assignment['strategy_id']
                order.assignment_method = strategy_assignment['method']
                order.assignment_confidence = strategy_assignment['confidence']
                
                # Update strategy metrics
                await self.strategy_service._update_strategy_metrics(
                    self.db.query(StrategyModel).filter_by(
                        strategy_id=strategy_assignment['strategy_id']
                    ).first()
                )
            else:
                # Add to manual review queue
                logger.warning(f"Could not auto-assign external order {order.order_id}")
        
        self.db.commit()
    
    async def _assign_to_strategy(self, order: OrderModel) -> Optional[Dict]:
        """Intelligently assign external order to strategy"""
        
        # Get active strategies for the account
        strategies = self.db.query(StrategyModel).filter(
            and_(
                StrategyModel.pseudo_account == order.pseudo_account,
                StrategyModel.status == 'ACTIVE'
            )
        ).all()
        
        if not strategies:
            return None
        
        # Single active strategy - high confidence
        if len(strategies) == 1:
            return {
                'strategy_id': strategies[0].strategy_id,
                'method': 'SINGLE_ACTIVE_STRATEGY',
                'confidence': 80.0
            }
        
        # Multiple strategies - check symbol match
        for strategy in strategies:
            # Check if strategy has positions in same symbol
            positions = self.db.query(PositionModel).filter(
                and_(
                    PositionModel.strategy_id == strategy.strategy_id,
                    PositionModel.trading_symbol == order.trading_symbol,
                    PositionModel.quantity != 0
                )
            ).first()
            
            if positions:
                return {
                    'strategy_id': strategy.strategy_id,
                    'method': 'SYMBOL_MATCH',
                    'confidence': 90.0
                }
            
            # Check recent orders in same symbol
            recent_orders = self.db.query(OrderModel).filter(
                and_(
                    OrderModel.strategy_id == strategy.strategy_id,
                    OrderModel.trading_symbol == order.trading_symbol,
                    OrderModel.created_at >= datetime.utcnow() - timedelta(days=7)
                )
            ).first()
            
            if recent_orders:
                return {
                    'strategy_id': strategy.strategy_id,
                    'method': 'RECENT_SYMBOL_ACTIVITY',
                    'confidence': 70.0
                }
        
        # No good match found
        return None
    
    async def _reconcile_positions(self, fetched_orders: List[Dict], 
                                  pseudo_account: str) -> Dict:
        """Reconcile position discrepancies from external orders"""
        # This would compare broker positions with internal positions
        # and create adjustment entries if needed
        
        # For now, return summary
        return {
            'positions_checked': 0,
            'adjustments_made': 0
        }
    
    def _parse_broker_timestamp(self, timestamp_str: Optional[str]) -> datetime:
        """Parse broker timestamp to datetime"""
        if not timestamp_str:
            return datetime.utcnow()
        
        try:
            # Handle different timestamp formats from brokers
            for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d']:
                try:
                    return datetime.strptime(timestamp_str, fmt)
                except ValueError:
                    continue
            
            return datetime.utcnow()
        except:
            return datetime.utcnow()
    
    async def create_orphaned_strategy(self, pseudo_account: str, 
                                     organization_id: str) -> StrategyModel:
        """Create strategy for orphaned external orders"""
        strategy_id = f"EXT_{datetime.now().strftime('%Y%m%d')}"
        
        strategy = StrategyModel(
            strategy_id=strategy_id,
            strategy_name="External Orders",
            pseudo_account=pseudo_account,
            organization_id=organization_id,
            strategy_type="MANUAL",
            status="ACTIVE",
            description="Auto-created strategy for external orders",
            tags=['external', 'auto-created'],
            created_by='EXTERNAL_ORDER_DETECTOR',
            started_at=datetime.utcnow()
        )
        
        self.db.add(strategy)
        self.db.commit()
        
        return strategy