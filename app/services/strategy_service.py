# app/services/strategy_service.py
import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func
from fastapi import HTTPException

from shared_architecture.db.models.order_model import OrderModel
from shared_architecture.db.models.position_model import PositionModel
from shared_architecture.db.models.holding_model import HoldingModel
from shared_architecture.db.models.margin_model import MarginModel
from shared_architecture.utils.redis_data_manager import RedisDataManager

logger = logging.getLogger(__name__)

class StrategyService:
    """Service for managing trading strategies and data allocation"""
    
    def __init__(self, db: Session, redis_manager: Optional[RedisDataManager] = None):
        self.db = db
        self.redis_manager = redis_manager
    
    async def split_data_to_strategy(
        self,
        organization_id: str,
        pseudo_account: str,
        source_strategy_id: str,
        target_strategy_id: str,
        allocations: List[Dict]
    ) -> Dict:
        """
        Split positions, holdings, orders from source strategy to target strategy
        
        Args:
            organization_id: Organization ID
            pseudo_account: Trading account
            source_strategy_id: Source strategy (use 'default' for blanket data)
            target_strategy_id: Target strategy to allocate to
            allocations: List of allocation instructions
                [
                    {
                        "instrument_key": "NSE@RELIANCE@equities",
                        "data_type": "position|holding|order",
                        "quantity": 100,
                        "price": 2500.0,  # Optional, for validation
                        "order_ids": [123, 456]  # For order allocation
                    }
                ]
        
        Returns:
            Summary of allocated data
        """
        results = {
            "positions": [],
            "holdings": [],
            "orders": [],
            "errors": []
        }
        
        for allocation in allocations:
            try:
                instrument_key = allocation['instrument_key']
                data_type = allocation['data_type']
                quantity = allocation.get('quantity', 0)
                price = allocation.get('price')
                
                if data_type == 'position':
                    result = await self._split_position(
                        pseudo_account, instrument_key, source_strategy_id,
                        target_strategy_id, quantity, price
                    )
                    results['positions'].append(result)
                    
                elif data_type == 'holding':
                    result = await self._split_holding(
                        pseudo_account, instrument_key, source_strategy_id,
                        target_strategy_id, quantity
                    )
                    results['holdings'].append(result)
                    
                elif data_type == 'order':
                    order_ids = allocation.get('order_ids', [])
                    result = await self._reassign_orders(
                        pseudo_account, order_ids, target_strategy_id
                    )
                    results['orders'].extend(result)
                    
            except Exception as e:
                results['errors'].append({
                    'allocation': allocation,
                    'error': str(e)
                })
                logger.error(f"Failed to process allocation: {e}")
        
        # Update Redis cache if available
        if self.redis_manager:
            await self._sync_strategy_to_redis(organization_id, pseudo_account, target_strategy_id)
            await self._sync_strategy_to_redis(organization_id, pseudo_account, source_strategy_id)
        
        return results
    
    async def _split_position(
        self,
        pseudo_account: str,
        instrument_key: str,
        source_strategy_id: str,
        target_strategy_id: str,
        quantity: int,
        price: Optional[float] = None
    ) -> Dict:
        """Split a position between strategies"""
        
        # Find source position
        source_position = self.db.query(PositionModel).filter_by(
            pseudo_account=pseudo_account,
            instrument_key=instrument_key,
            strategy_id=source_strategy_id
        ).first()
        
        if not source_position:
            raise ValueError(f"No position found for {instrument_key} in strategy {source_strategy_id}")
        
        # Validate quantity
        if abs(source_position.net_quantity) < quantity:
            raise ValueError(
                f"Insufficient quantity in source position. "
                f"Available: {abs(source_position.net_quantity)}, Requested: {quantity}"
            )
        
        # Validate price if provided
        if price:
            avg_price = (source_position.buy_value / source_position.buy_quantity 
                        if source_position.buy_quantity > 0 else 
                        source_position.sell_value / source_position.sell_quantity)
            
            price_tolerance = 0.01  # 1% tolerance
            if abs(avg_price - price) / avg_price > price_tolerance:
                logger.warning(
                    f"Price mismatch for {instrument_key}: "
                    f"Expected: {price}, Actual avg: {avg_price}"
                )
        
        # Check if target position exists
        target_position = self.db.query(PositionModel).filter_by(
            pseudo_account=pseudo_account,
            instrument_key=instrument_key,
            strategy_id=target_strategy_id
        ).first()
        
        # Calculate split values
        is_buy = source_position.net_quantity > 0
        split_ratio = quantity / abs(source_position.net_quantity)
        
        if is_buy:
            split_buy_qty = int(source_position.buy_quantity * split_ratio)
            split_buy_value = source_position.buy_value * split_ratio
            split_sell_qty = 0
            split_sell_value = 0.0
        else:
            split_buy_qty = 0
            split_buy_value = 0.0
            split_sell_qty = int(source_position.sell_quantity * split_ratio)
            split_sell_value = source_position.sell_value * split_ratio
        
        # Update source position
        source_position.net_quantity -= (quantity if is_buy else -quantity)
        source_position.buy_quantity -= split_buy_qty
        source_position.buy_value -= split_buy_value
        source_position.sell_quantity -= split_sell_qty
        source_position.sell_value -= split_sell_value
        
        # Update averages
        if source_position.buy_quantity > 0:
            source_position.buy_avg_price = source_position.buy_value / source_position.buy_quantity
        if source_position.sell_quantity > 0:
            source_position.sell_avg_price = source_position.sell_value / source_position.sell_quantity
        
        # Create or update target position
        if target_position:
            target_position.net_quantity += (quantity if is_buy else -quantity)
            target_position.buy_quantity += split_buy_qty
            target_position.buy_value += split_buy_value
            target_position.sell_quantity += split_sell_qty
            target_position.sell_value += split_sell_value
            
            # Update averages
            if target_position.buy_quantity > 0:
                target_position.buy_avg_price = target_position.buy_value / target_position.buy_quantity
            if target_position.sell_quantity > 0:
                target_position.sell_avg_price = target_position.sell_value / target_position.sell_quantity
        else:
            # Create new position
            target_position = PositionModel(
                pseudo_account=pseudo_account,
                instrument_key=instrument_key,
                strategy_id=target_strategy_id,
                source_strategy_id=source_strategy_id,
                net_quantity=(quantity if is_buy else -quantity),
                buy_quantity=split_buy_qty,
                buy_value=split_buy_value,
                sell_quantity=split_sell_qty,
                sell_value=split_sell_value,
                buy_avg_price=(split_buy_value / split_buy_qty if split_buy_qty > 0 else 0),
                sell_avg_price=(split_sell_value / split_sell_qty if split_sell_qty > 0 else 0),
                direction="BUY" if is_buy else "SELL",
                timestamp=datetime.utcnow(),
                # Copy other fields from source
                account_id=source_position.account_id,
                exchange=source_position.exchange,
                symbol=source_position.symbol,
                category=source_position.category,
                type=source_position.type,
                platform=source_position.platform,
                stock_broker=source_position.stock_broker,
                trading_account=source_position.trading_account,
                state='OPEN',
                # Initialize numeric fields
                ltp=source_position.ltp,
                mtm=0.0,
                pnl=0.0,
                realised_pnl=0.0,
                unrealised_pnl=0.0,
                multiplier=1,
                net_value=0.0,
                overnight_quantity=0
            )
            self.db.add(target_position)
        
        self.db.commit()
        
        return {
            "instrument_key": instrument_key,
            "quantity_split": quantity,
            "source_remaining": source_position.net_quantity,
            "target_total": target_position.net_quantity
        }
    
    async def _split_holding(
        self,
        pseudo_account: str,
        instrument_key: str,
        source_strategy_id: str,
        target_strategy_id: str,
        quantity: int
    ) -> Dict:
        """Split a holding between strategies"""
        
        # Find source holding
        source_holding = self.db.query(HoldingModel).filter_by(
            pseudo_account=pseudo_account,
            instrument_key=instrument_key,
            strategy_id=source_strategy_id
        ).first()
        
        if not source_holding:
            raise ValueError(f"No holding found for {instrument_key} in strategy {source_strategy_id}")
        
        # Validate quantity
        if source_holding.quantity < quantity:
            raise ValueError(
                f"Insufficient quantity in source holding. "
                f"Available: {source_holding.quantity}, Requested: {quantity}"
            )
        
        # Check if target holding exists
        target_holding = self.db.query(HoldingModel).filter_by(
            pseudo_account=pseudo_account,
            instrument_key=instrument_key,
            strategy_id=target_strategy_id
        ).first()
        
        # Calculate weighted average price for split
        avg_price = source_holding.avg_price
        
        # Update source holding
        source_holding.quantity -= quantity
        
        # Create or update target holding
        if target_holding:
            # Calculate new weighted average
            total_value = (target_holding.quantity * target_holding.avg_price) + (quantity * avg_price)
            total_qty = target_holding.quantity + quantity
            target_holding.quantity = total_qty
            target_holding.avg_price = total_value / total_qty if total_qty > 0 else 0
        else:
            # Create new holding
            target_holding = HoldingModel(
                pseudo_account=pseudo_account,
                instrument_key=instrument_key,
                strategy_id=target_strategy_id,
                source_strategy_id=source_strategy_id,
                quantity=quantity,
                avg_price=avg_price,
                timestamp=datetime.utcnow(),
                # Copy other fields from source
                trading_account=source_holding.trading_account,
                exchange=source_holding.exchange,
                symbol=source_holding.symbol,
                product=source_holding.product,
                isin=source_holding.isin,
                collateral_qty=0,
                t1_qty=0,
                collateral_type=source_holding.collateral_type,
                pnl=0.0,
                haircut=source_holding.haircut,
                instrument_token=source_holding.instrument_token,
                stock_broker=source_holding.stock_broker,
                platform=source_holding.platform,
                ltp=source_holding.ltp,
                current_value=quantity * source_holding.ltp,
                total_qty=quantity
            )
            self.db.add(target_holding)
        
        self.db.commit()
        
        return {
            "instrument_key": instrument_key,
            "quantity_split": quantity,
            "source_remaining": source_holding.quantity,
            "target_total": target_holding.quantity
        }
    
    async def _reassign_orders(
        self,
        pseudo_account: str,
        order_ids: List[int],
        target_strategy_id: str
    ) -> List[Dict]:
        """Reassign orders to a different strategy"""
        
        results = []
        
        for order_id in order_ids:
            order = self.db.query(OrderModel).filter_by(
                id=order_id,
                pseudo_account=pseudo_account
            ).first()
            
            if not order:
                results.append({
                    "order_id": order_id,
                    "status": "error",
                    "message": "Order not found"
                })
                continue
            
            # Only reassign completed or cancelled orders
            if order.status not in ['COMPLETE', 'CANCELLED', 'REJECTED']:
                results.append({
                    "order_id": order_id,
                    "status": "error",
                    "message": f"Cannot reassign order with status {order.status}"
                })
                continue
            
            old_strategy = order.strategy_id
            order.strategy_id = target_strategy_id
            
            results.append({
                "order_id": order_id,
                "status": "success",
                "old_strategy": old_strategy,
                "new_strategy": target_strategy_id
            })
        
        self.db.commit()
        return results
    
    async def get_strategy_summary(
        self,
        organization_id: str,
        pseudo_account: str,
        strategy_id: str
    ) -> Dict:
        """Get comprehensive summary of a strategy"""
        
        # Get data from database
        positions = self.db.query(PositionModel).filter_by(
            pseudo_account=pseudo_account,
            strategy_id=strategy_id
        ).all()
        
        holdings = self.db.query(HoldingModel).filter_by(
            pseudo_account=pseudo_account,
            strategy_id=strategy_id
        ).all()
        
        orders = self.db.query(OrderModel).filter_by(
            pseudo_account=pseudo_account,
            strategy_id=strategy_id
        ).all()
        
        margins = self.db.query(MarginModel).filter_by(
            pseudo_account=pseudo_account,
            strategy_id=strategy_id
        ).all()
        
        # Calculate summary metrics
        summary = {
            "strategy_id": strategy_id,
            "positions": {
                "count": len(positions),
                "total_buy_value": sum(p.buy_value for p in positions),
                "total_sell_value": sum(p.sell_value for p in positions),
                "unrealized_pnl": sum(p.unrealised_pnl for p in positions),
                "realized_pnl": sum(p.realised_pnl for p in positions)
            },
            "holdings": {
                "count": len(holdings),
                "total_value": sum(h.current_value for h in holdings if h.current_value),
                "total_quantity": sum(h.quantity for h in holdings)
            },
            "orders": {
                "total": len(orders),
                "pending": len([o for o in orders if o.status == 'PENDING']),
                "complete": len([o for o in orders if o.status == 'COMPLETE']),
                "rejected": len([o for o in orders if o.status == 'REJECTED'])
            },
            "margins": {
                "available": sum(m.available for m in margins if m.available),
                "utilized": sum(m.utilized for m in margins if m.utilized),
                "total": sum(m.total for m in margins if m.total)
            }
        }
        
        return summary
    
    async def validate_strategy_allocation(
        self,
        organization_id: str,
        pseudo_account: str,
        allocations: List[Dict]
    ) -> Tuple[bool, List[str]]:
        """
        Validate that allocations don't exceed available quantities
        
        Returns:
            (is_valid, list_of_errors)
        """
        errors = []
        
        # Group allocations by instrument and source strategy
        allocation_summary = {}
        
        for alloc in allocations:
            key = (alloc['instrument_key'], alloc.get('source_strategy_id', 'default'))
            if key not in allocation_summary:
                allocation_summary[key] = 0
            allocation_summary[key] += alloc.get('quantity', 0)
        
        # Validate each allocation
        for (instrument_key, source_strategy_id), requested_qty in allocation_summary.items():
            # Check positions
            position = self.db.query(PositionModel).filter_by(
                pseudo_account=pseudo_account,
                instrument_key=instrument_key,
                strategy_id=source_strategy_id
            ).first()
            
            if position:
                available = abs(position.net_quantity)
                if requested_qty > available:
                    errors.append(
                        f"Position {instrument_key}: Requested {requested_qty} "
                        f"exceeds available {available} in strategy {source_strategy_id}"
                    )
            
            # Check holdings
            holding = self.db.query(HoldingModel).filter_by(
                pseudo_account=pseudo_account,
                instrument_key=instrument_key,
                strategy_id=source_strategy_id
            ).first()
            
            if holding:
                if requested_qty > holding.quantity:
                    errors.append(
                        f"Holding {instrument_key}: Requested {requested_qty} "
                        f"exceeds available {holding.quantity} in strategy {source_strategy_id}"
                    )
        
        return (len(errors) == 0, errors)
    
    async def _sync_strategy_to_redis(
        self,
        organization_id: str,
        pseudo_account: str,
        strategy_id: str
    ) -> None:
        """Sync strategy data from database to Redis"""
        
        if not self.redis_manager:
            return
        
        try:
            # Get fresh data from database
            positions = self.db.query(PositionModel).filter_by(
                pseudo_account=pseudo_account,
                strategy_id=strategy_id
            ).all()
            
            holdings = self.db.query(HoldingModel).filter_by(
                pseudo_account=pseudo_account,
                strategy_id=strategy_id
            ).all()
            
            orders = self.db.query(OrderModel).filter_by(
                pseudo_account=pseudo_account,
                strategy_id=strategy_id
            ).all()
            
            margins = self.db.query(MarginModel).filter_by(
                pseudo_account=pseudo_account,
                strategy_id=strategy_id
            ).all()
            
            # Store in Redis
            await self.redis_manager.store_positions(
                organization_id, pseudo_account, positions, strategy_id
            )
            await self.redis_manager.store_holdings(
                organization_id, pseudo_account, holdings, strategy_id
            )
            await self.redis_manager.store_orders(
                organization_id, pseudo_account, orders, strategy_id
            )
            await self.redis_manager.store_margins(
                organization_id, pseudo_account, margins, strategy_id
            )
            
            # Store strategy metadata
            summary = await self.get_strategy_summary(organization_id, pseudo_account, strategy_id)
            await self.redis_manager.store_strategy_metadata(
                organization_id, pseudo_account, strategy_id, summary
            )
            
        except Exception as e:
            logger.error(f"Failed to sync strategy {strategy_id} to Redis: {e}")