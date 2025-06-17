import uuid
import logging
from typing import List, Dict, Optional, Any
from datetime import datetime, time
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func

from shared_architecture.db.models.strategy_model import StrategyModel
from shared_architecture.db.models.position_model import PositionModel
from shared_architecture.db.models.order_model import OrderModel
from shared_architecture.db.models.holding_model import HoldingModel
from shared_architecture.db.models.margin_model import MarginModel
from shared_architecture.schemas.strategy_schema import (
    StrategyCreate, StrategyUpdate, StrategyResponse, StrategySummary,
    StrategyTaggingRequest, StrategyTaggingResponse,
    StrategySquareOffPreview, StrategySquareOffRequest, StrategySquareOffResponse
)
from shared_architecture.enums import StrategyStatus, OrderStatus, TradeType, OrderType, ProductType
from shared_architecture.errors.custom_exceptions import ValidationError, BusinessLogicError

logger = logging.getLogger(__name__)

class StrategyManagementService:
    def __init__(self, db: Session):
        self.db = db

    async def create_strategy(self, strategy_data: StrategyCreate, created_by: str) -> StrategyResponse:
        """Create a new strategy with comprehensive validation"""
        try:
            # Generate strategy_id if not provided
            if not strategy_data.strategy_id:
                strategy_id = f"STR_{uuid.uuid4().hex[:8].upper()}"
            else:
                strategy_id = strategy_data.strategy_id
                
            # Check if strategy_id already exists
            existing = self.db.query(StrategyModel).filter_by(strategy_id=strategy_id).first()
            if existing:
                raise ValidationError(f"Strategy with ID '{strategy_id}' already exists")
            
            # Create strategy model
            strategy = StrategyModel(
                strategy_id=strategy_id,
                strategy_name=strategy_data.strategy_name,
                pseudo_account=strategy_data.pseudo_account,
                organization_id=strategy_data.organization_id,
                strategy_type=strategy_data.strategy_type.value,
                description=strategy_data.description,
                max_loss_amount=strategy_data.max_loss_amount,
                max_profit_amount=strategy_data.max_profit_amount,
                max_positions=strategy_data.max_positions,
                tags=strategy_data.tags or [],
                configuration=strategy_data.configuration or {},
                auto_square_off_enabled=strategy_data.auto_square_off_enabled,
                square_off_time=strategy_data.square_off_time,
                created_by=created_by,
                started_at=datetime.utcnow()
            )
            
            self.db.add(strategy)
            self.db.commit()
            self.db.refresh(strategy)
            
            logger.info(f"Created strategy {strategy_id} for account {strategy_data.pseudo_account}")
            return StrategyResponse.from_orm(strategy)
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error creating strategy: {str(e)}")
            raise

    async def get_strategy(self, strategy_id: str) -> Optional[StrategyResponse]:
        """Get strategy by ID with current metrics"""
        strategy = self.db.query(StrategyModel).filter_by(strategy_id=strategy_id).first()
        if not strategy:
            return None
            
        # Update real-time metrics
        await self._update_strategy_metrics(strategy)
        return StrategyResponse.from_orm(strategy)

    async def update_strategy(self, strategy_id: str, update_data: StrategyUpdate, updated_by: str) -> Optional[StrategyResponse]:
        """Update strategy with validation"""
        strategy = self.db.query(StrategyModel).filter_by(strategy_id=strategy_id).first()
        if not strategy:
            return None
            
        try:
            # Update fields
            for field, value in update_data.dict(exclude_unset=True).items():
                setattr(strategy, field, value)
                
            strategy.last_modified_by = updated_by
            strategy.updated_at = datetime.utcnow()
            
            self.db.commit()
            self.db.refresh(strategy)
            
            logger.info(f"Updated strategy {strategy_id}")
            return StrategyResponse.from_orm(strategy)
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error updating strategy {strategy_id}: {str(e)}")
            raise

    async def delete_strategy(self, strategy_id: str) -> bool:
        """Delete strategy with comprehensive cleanup"""
        strategy = self.db.query(StrategyModel).filter_by(strategy_id=strategy_id).first()
        if not strategy:
            return False
            
        try:
            # Check if strategy has active positions or orders
            active_positions = self.db.query(PositionModel).filter(
                and_(
                    PositionModel.strategy_id == strategy_id,
                    PositionModel.net_quantity != 0
                )
            ).count()
            
            active_orders = self.db.query(OrderModel).filter(
                and_(
                    OrderModel.strategy_id == strategy_id,
                    OrderModel.status.in_(OrderStatus.get_active_states())
                )
            ).count()
            
            if active_positions > 0 or active_orders > 0:
                raise BusinessLogicError(
                    f"Cannot delete strategy {strategy_id}: has {active_positions} active positions and {active_orders} active orders. "
                    "Please square off all positions and cancel orders first."
                )
            
            # Clear strategy_id from related entities
            self.db.query(PositionModel).filter_by(strategy_id=strategy_id).update({"strategy_id": None})
            self.db.query(OrderModel).filter_by(strategy_id=strategy_id).update({"strategy_id": None})
            self.db.query(HoldingModel).filter_by(strategy_id=strategy_id).update({"strategy_id": None})
            
            # Delete strategy
            self.db.delete(strategy)
            self.db.commit()
            
            logger.info(f"Deleted strategy {strategy_id}")
            return True
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error deleting strategy {strategy_id}: {str(e)}")
            raise

    async def list_strategies(self, pseudo_account: str, organization_id: str) -> List[StrategySummary]:
        """List all strategies for an account with summary metrics"""
        strategies = self.db.query(StrategyModel).filter(
            and_(
                StrategyModel.pseudo_account == pseudo_account,
                StrategyModel.organization_id == organization_id
            )
        ).order_by(StrategyModel.created_at.desc()).all()
        
        summaries = []
        for strategy in strategies:
            # Get summary data
            positions = self.db.query(PositionModel).filter_by(strategy_id=strategy.strategy_id).all()
            orders = self.db.query(OrderModel).filter_by(strategy_id=strategy.strategy_id).order_by(OrderModel.timestamp.desc()).limit(5).all()
            holdings = self.db.query(HoldingModel).filter_by(strategy_id=strategy.strategy_id).all()
            
            # Calculate metrics
            total_pnl = sum(p.unrealised_pnl or 0 for p in positions) + sum(p.realised_pnl or 0 for p in positions)
            unrealised_pnl = sum(p.unrealised_pnl or 0 for p in positions)
            
            # Top positions by absolute PnL
            top_positions = sorted(
                [{"symbol": p.symbol, "quantity": p.net_quantity, "pnl": p.unrealised_pnl or 0} for p in positions if p.net_quantity != 0],
                key=lambda x: abs(x["pnl"]),
                reverse=True
            )[:5]
            
            summaries.append(StrategySummary(
                strategy_id=strategy.strategy_id,
                strategy_name=strategy.strategy_name,
                status=StrategyStatus(strategy.status),
                total_pnl=total_pnl,
                unrealized_pnl=unrealised_pnl,
                total_margin_used=strategy.total_margin_used,
                active_positions_count=len([p for p in positions if p.net_quantity != 0]),
                active_orders_count=len([o for o in orders if o.status in OrderStatus.get_active_states()]),
                holdings_count=len(holdings),
                top_positions=top_positions,
                recent_orders=[{"order_id": o.exchange_order_id, "symbol": o.symbol, "status": o.status} for o in orders],
                holdings_summary={"total_value": sum(h.current_value or 0 for h in holdings)}
            ))
            
        return summaries

    async def tag_positions(self, strategy_id: str, request: StrategyTaggingRequest) -> StrategyTaggingResponse:
        """Tag positions to a strategy"""
        strategy = self.db.query(StrategyModel).filter_by(strategy_id=strategy_id).first()
        if not strategy:
            raise ValidationError(f"Strategy {strategy_id} not found")
            
        tagged_count = 0
        skipped_count = 0
        error_count = 0
        details = []
        
        try:
            for position_id in request.entity_ids:
                position = self.db.query(PositionModel).filter_by(id=position_id).first()
                if not position:
                    error_count += 1
                    details.append({"entity_id": position_id, "status": "error", "message": "Position not found"})
                    continue
                
                # Check if already tagged to different strategy
                if position.strategy_id and position.strategy_id != strategy_id and not request.overwrite_existing:
                    skipped_count += 1
                    details.append({"entity_id": position_id, "status": "skipped", "message": f"Already tagged to {position.strategy_id}"})
                    continue
                
                # Validate account match
                if position.pseudo_account != strategy.pseudo_account:
                    error_count += 1
                    details.append({"entity_id": position_id, "status": "error", "message": "Account mismatch"})
                    continue
                
                # Tag position
                position.strategy_id = strategy_id
                tagged_count += 1
                details.append({"entity_id": position_id, "status": "success", "message": "Tagged successfully"})
            
            self.db.commit()
            
            # Update strategy metrics
            await self._update_strategy_metrics(strategy)
            
            return StrategyTaggingResponse(
                strategy_id=strategy_id,
                entity_type="positions",
                tagged_count=tagged_count,
                skipped_count=skipped_count,
                error_count=error_count,
                details=details
            )
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error tagging positions to strategy {strategy_id}: {str(e)}")
            raise

    async def tag_orders(self, strategy_id: str, request: StrategyTaggingRequest) -> StrategyTaggingResponse:
        """Tag orders to a strategy"""
        strategy = self.db.query(StrategyModel).filter_by(strategy_id=strategy_id).first()
        if not strategy:
            raise ValidationError(f"Strategy {strategy_id} not found")
            
        tagged_count = 0
        skipped_count = 0
        error_count = 0
        details = []
        
        try:
            for order_id in request.entity_ids:
                order = self.db.query(OrderModel).filter_by(exchange_order_id=order_id).first()
                if not order:
                    error_count += 1
                    details.append({"entity_id": order_id, "status": "error", "message": "Order not found"})
                    continue
                
                # Check if already tagged
                if order.strategy_id and order.strategy_id != strategy_id and not request.overwrite_existing:
                    skipped_count += 1
                    details.append({"entity_id": order_id, "status": "skipped", "message": f"Already tagged to {order.strategy_id}"})
                    continue
                
                # Validate account match
                if order.pseudo_account != strategy.pseudo_account:
                    error_count += 1
                    details.append({"entity_id": order_id, "status": "error", "message": "Account mismatch"})
                    continue
                
                # Tag order
                order.strategy_id = strategy_id
                tagged_count += 1
                details.append({"entity_id": order_id, "status": "success", "message": "Tagged successfully"})
            
            self.db.commit()
            await self._update_strategy_metrics(strategy)
            
            return StrategyTaggingResponse(
                strategy_id=strategy_id,
                entity_type="orders",
                tagged_count=tagged_count,
                skipped_count=skipped_count,
                error_count=error_count,
                details=details
            )
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error tagging orders to strategy {strategy_id}: {str(e)}")
            raise

    async def tag_holdings(self, strategy_id: str, request: StrategyTaggingRequest) -> StrategyTaggingResponse:
        """Tag holdings to a strategy"""
        strategy = self.db.query(StrategyModel).filter_by(strategy_id=strategy_id).first()
        if not strategy:
            raise ValidationError(f"Strategy {strategy_id} not found")
            
        tagged_count = 0
        skipped_count = 0
        error_count = 0
        details = []
        
        try:
            for holding_id in request.entity_ids:
                holding = self.db.query(HoldingModel).filter_by(id=holding_id).first()
                if not holding:
                    error_count += 1
                    details.append({"entity_id": holding_id, "status": "error", "message": "Holding not found"})
                    continue
                
                # Check if already tagged
                if holding.strategy_id and holding.strategy_id != strategy_id and not request.overwrite_existing:
                    skipped_count += 1
                    details.append({"entity_id": holding_id, "status": "skipped", "message": f"Already tagged to {holding.strategy_id}"})
                    continue
                
                # Validate account match
                if holding.pseudo_account != strategy.pseudo_account:
                    error_count += 1
                    details.append({"entity_id": holding_id, "status": "error", "message": "Account mismatch"})
                    continue
                
                # Tag holding
                holding.strategy_id = strategy_id
                tagged_count += 1
                details.append({"entity_id": holding_id, "status": "success", "message": "Tagged successfully"})
            
            self.db.commit()
            await self._update_strategy_metrics(strategy)
            
            return StrategyTaggingResponse(
                strategy_id=strategy_id,
                entity_type="holdings",
                tagged_count=tagged_count,
                skipped_count=skipped_count,
                error_count=error_count,
                details=details
            )
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error tagging holdings to strategy {strategy_id}: {str(e)}")
            raise

    async def preview_square_off(self, strategy_id: str) -> StrategySquareOffPreview:
        """Preview square-off orders for a strategy"""
        strategy = self.db.query(StrategyModel).filter_by(strategy_id=strategy_id).first()
        if not strategy:
            raise ValidationError(f"Strategy {strategy_id} not found")
        
        # Get positions and holdings
        positions = self.db.query(PositionModel).filter(
            and_(
                PositionModel.strategy_id == strategy_id,
                PositionModel.net_quantity != 0
            )
        ).all()
        
        holdings = self.db.query(HoldingModel).filter_by(strategy_id=strategy_id).all()
        
        estimated_orders = []
        warnings = []
        total_pnl_impact = 0
        
        # Generate square-off orders for positions
        for position in positions:
            if position.net_quantity == 0:
                continue
                
            # Determine order type (opposite of current position)
            order_type = TradeType.SELL if position.net_quantity > 0 else TradeType.BUY
            
            estimated_order = {
                "trading_symbol": position.symbol,
                "exchange": position.exchange,
                "order_type": order_type.value,
                "quantity": abs(position.net_quantity),
                "product_type": position.type,
                "current_pnl": position.unrealised_pnl or 0,
                "position_type": "LONG" if position.net_quantity > 0 else "SHORT"
            }
            estimated_orders.append(estimated_order)
            total_pnl_impact += position.unrealised_pnl or 0
        
        # Generate square-off orders for holdings
        for holding in holdings:
            if holding.quantity <= 0:
                continue
                
            estimated_order = {
                "trading_symbol": holding.symbol,
                "exchange": holding.exchange,
                "order_type": TradeType.SELL.value,
                "quantity": holding.quantity,
                "product_type": "CNC",
                "current_value": holding.current_value or 0,
                "holding_type": "EQUITY"
            }
            estimated_orders.append(estimated_order)
        
        # Check for warnings
        if len(estimated_orders) > 50:
            warnings.append("Large number of orders may require multiple batches")
        
        # Estimate margin release (simplified)
        margin_release_estimate = sum(getattr(p, 'margin_used', 0) or 0 for p in positions)
        
        return StrategySquareOffPreview(
            strategy_id=strategy_id,
            estimated_orders=estimated_orders,
            total_positions=len(positions),
            total_holdings=len(holdings),
            estimated_pnl_impact=total_pnl_impact,
            margin_release_estimate=margin_release_estimate,
            warnings=warnings
        )

    async def square_off_strategy(self, strategy_id: str, request: StrategySquareOffRequest) -> StrategySquareOffResponse:
        """Execute strategy square-off (Note: This creates order data but doesn't place actual orders)"""
        if not request.confirm:
            raise ValidationError("Square-off requires explicit confirmation")
        
        strategy = self.db.query(StrategyModel).filter_by(strategy_id=strategy_id).first()
        if not strategy:
            raise ValidationError(f"Strategy {strategy_id} not found")
        
        # Get preview first
        preview = await self.preview_square_off(strategy_id)
        
        if request.dry_run:
            return StrategySquareOffResponse(
                strategy_id=strategy_id,
                total_orders_placed=0,
                successful_orders=len(preview.estimated_orders),
                failed_orders=0,
                batch_count=1,
                estimated_completion_time="DRY_RUN",
                order_details=preview.estimated_orders,
                errors=["DRY_RUN: No actual orders placed"]
            )
        
        # NOTE: This is a simplified implementation that creates order records
        # In production, this would integrate with actual broker APIs
        successful_orders = 0
        failed_orders = 0
        order_details = []
        errors = []
        
        try:
            # Create square-off order records (not actual broker orders)
            for estimated_order in preview.estimated_orders:
                try:
                    # This would normally call the trade service to place actual orders
                    # For now, we'll just log the intent
                    order_detail = {
                        "symbol": estimated_order["trading_symbol"],
                        "action": estimated_order["order_type"],
                        "quantity": estimated_order["quantity"],
                        "status": "SIMULATED",
                        "message": "Square-off order simulated (actual placement requires broker integration)"
                    }
                    order_details.append(order_detail)
                    successful_orders += 1
                    
                except Exception as e:
                    failed_orders += 1
                    errors.append(f"Failed to create order for {estimated_order['trading_symbol']}: {str(e)}")
            
            # Update strategy status
            if successful_orders > 0:
                strategy.status = StrategyStatus.SQUARED_OFF.value
                strategy.squared_off_at = datetime.utcnow()
                self.db.commit()
            
            return StrategySquareOffResponse(
                strategy_id=strategy_id,
                total_orders_placed=successful_orders,
                successful_orders=successful_orders,
                failed_orders=failed_orders,
                batch_count=1,
                estimated_completion_time="IMMEDIATE",
                order_details=order_details,
                errors=errors
            )
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error during strategy square-off {strategy_id}: {str(e)}")
            raise

    async def _update_strategy_metrics(self, strategy: StrategyModel):
        """Update real-time strategy metrics"""
        try:
            # Get strategy positions, orders, holdings
            positions = self.db.query(PositionModel).filter_by(strategy_id=strategy.strategy_id).all()
            orders = self.db.query(OrderModel).filter_by(strategy_id=strategy.strategy_id).all()
            holdings = self.db.query(HoldingModel).filter_by(strategy_id=strategy.strategy_id).all()
            
            # Calculate PnL
            total_unrealised_pnl = sum(p.unrealised_pnl or 0 for p in positions)
            total_realised_pnl = sum(p.realised_pnl or 0 for p in positions)
            total_pnl = total_unrealised_pnl + total_realised_pnl
            
            # Calculate counts
            active_positions = len([p for p in positions if p.net_quantity != 0])
            active_orders = len([o for o in orders if o.status in OrderStatus.get_active_states()])
            
            # Update strategy
            strategy.total_pnl = total_pnl
            strategy.realised_pnl = total_realised_pnl
            strategy.unrealised_pnl = total_unrealised_pnl
            strategy.active_positions_count = active_positions
            strategy.total_orders_count = len(orders)
            strategy.active_orders_count = active_orders
            strategy.holdings_count = len(holdings)
            strategy.updated_at = datetime.utcnow()
            
            self.db.commit()
            
        except Exception as e:
            logger.error(f"Error updating strategy metrics for {strategy.strategy_id}: {str(e)}")
            self.db.rollback()