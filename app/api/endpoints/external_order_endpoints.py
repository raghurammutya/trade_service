from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from sqlalchemy.orm import Session
import logging

from shared_architecture.db.session import get_db
from app.services.data_refresh_service import DataRefreshService
from app.services.external_order_detector import ExternalOrderDetector

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/external", tags=["external_orders"])

@router.post("/trigger-sync", response_model=dict)
async def trigger_manual_sync(
    pseudo_account: str = Query(..., description="Account to sync"),
    organization_id: str = Query(..., description="Organization ID"),
    db: Session = Depends(get_db)
):
    """
    Manually trigger the enhanced sync task (normally runs automatically)
    
    **Use Cases:**
    - Testing external order detection
    - Force sync after known external activity
    - Debug sync issues
    
    **Note:** External order detection happens automatically every 5-10 minutes.
    This endpoint is for manual triggering only.
    """
    
    try:
        from app.tasks.external_order_sync_task import sync_account_with_external_detection
        
        # Queue the enhanced sync task
        task_result = sync_account_with_external_detection.delay(organization_id, pseudo_account)
        
        return {
            "status": "success",
            "message": f"Enhanced sync queued for {pseudo_account}",
            "task_id": task_result.id,
            "note": "Check task status or external orders endpoint for results"
        }
        
    except Exception as e:
        logger.error(f"Error triggering manual sync: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/external-orders/{pseudo_account}", response_model=dict)
async def get_external_orders(
    pseudo_account: str,
    organization_id: str = Query(..., description="Organization ID"),
    days: int = Query(default=7, description="Number of days to look back"),
    db: Session = Depends(get_db)
):
    """
    Get external orders detected for an account
    
    **Returns:**
    - Orders placed outside AutoTrader
    - Strategy assignments (auto vs manual)
    - Discovery timestamps
    - Assignment confidence scores
    """
    
    try:
        from shared_architecture.db.models.order_model import OrderModel
        from datetime import datetime, timedelta
        
        # Get external orders from the last N days
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        # For Option 1: Use comments field to identify external/historical orders
        external_orders = db.query(OrderModel).filter(
            OrderModel.pseudo_account == pseudo_account,
            OrderModel.comments.like('%Historical Import%'),
            OrderModel.timestamp >= cutoff_date
        ).order_by(OrderModel.timestamp.desc()).all()
        
        orders_data = []
        for order in external_orders:
            # Parse metadata from comments if available
            comments_metadata = order.comments or ""
            orders_data.append({
                'order_id': order.id,  # Use database ID
                'original_order_id': order.exchange_order_id,  # Use exchange_order_id
                'trading_symbol': order.symbol,  # Use symbol field
                'trade_type': order.trade_type,
                'quantity': order.quantity,
                'price': order.price,
                'status': order.status,
                'strategy_id': order.strategy_id,
                'assignment_method': 'HISTORICAL',  # Since from historical import
                'assignment_confidence': 100.0,  # Full confidence for historical
                'discovered_at': order.timestamp.isoformat() if order.timestamp else None,
                'created_at': order.timestamp.isoformat() if order.timestamp else None,
                'metadata': comments_metadata
            })
        
        return {
            "pseudo_account": pseudo_account,
            "external_orders": orders_data,
            "total_count": len(orders_data),
            "date_range": {
                "from": cutoff_date.isoformat(),
                "to": datetime.utcnow().isoformat()
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting external orders: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/unassigned-orders/{pseudo_account}", response_model=dict)
async def get_unassigned_external_orders(
    pseudo_account: str,
    organization_id: str = Query(..., description="Organization ID"),
    db: Session = Depends(get_db)
):
    """
    Get external orders that couldn't be auto-assigned to strategies
    These require manual review and assignment
    """
    
    try:
        from shared_architecture.db.models.order_model import OrderModel
        
        unassigned_orders = db.query(OrderModel).filter(
            OrderModel.pseudo_account == pseudo_account,
            OrderModel.comments.like('%Historical Import%'),
            OrderModel.strategy_id.is_(None)
        ).order_by(OrderModel.timestamp.desc()).all()
        
        orders_data = []
        for order in unassigned_orders:
            orders_data.append({
                'order_id': order.id,
                'original_order_id': order.exchange_order_id,
                'trading_symbol': order.symbol,
                'trade_type': order.trade_type,
                'quantity': order.quantity,
                'price': order.price,
                'status': order.status,
                'discovered_at': order.timestamp.isoformat() if order.timestamp else None,
                'suggested_strategies': []  # Would contain ML suggestions
            })
        
        return {
            "pseudo_account": pseudo_account,
            "unassigned_orders": orders_data,
            "count": len(orders_data),
            "message": "These orders require manual strategy assignment"
        }
        
    except Exception as e:
        logger.error(f"Error getting unassigned orders: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/assign-order-to-strategy", response_model=dict)
async def manually_assign_order_to_strategy(
    order_id: str = Query(..., description="Order ID to assign"),
    strategy_id: str = Query(..., description="Strategy ID to assign to"),
    assigned_by: str = Query(..., description="User making the assignment"),
    db: Session = Depends(get_db)
):
    """
    Manually assign an external order to a strategy
    Used for orders that couldn't be auto-assigned
    """
    
    try:
        from shared_architecture.db.models.order_model import OrderModel
        from shared_architecture.db.models.strategy_model import StrategyModel
        
        # Find the order
        order = db.query(OrderModel).filter_by(exchange_order_id=order_id).first()
        if not order:
            raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
        
        # Validate strategy exists and belongs to same account
        strategy = db.query(StrategyModel).filter_by(strategy_id=strategy_id).first()
        if not strategy:
            raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")
        
        if strategy.pseudo_account != order.pseudo_account:
            raise HTTPException(
                status_code=400, 
                detail="Strategy and order must belong to the same account"
            )
        
        # Assign order to strategy
        order.strategy_id = strategy_id
        order.assignment_method = 'MANUAL'
        order.assignment_confidence = 100.0
        order.updated_at = datetime.utcnow()
        
        # Update external metadata
        if not order.external_metadata:
            order.external_metadata = {}
        order.external_metadata['manual_assignment'] = {
            'assigned_by': assigned_by,
            'assigned_at': datetime.utcnow().isoformat(),
            'previous_strategy_id': order.strategy_id
        }
        
        db.commit()
        
        # Update strategy metrics
        from app.services.strategy_management_service import StrategyManagementService
        strategy_service = StrategyManagementService(db)
        await strategy_service._update_strategy_metrics(strategy)
        
        return {
            "status": "success",
            "message": f"Order {order_id} assigned to strategy {strategy_id}",
            "assignment": {
                "order_id": order_id,
                "strategy_id": strategy_id,
                "assigned_by": assigned_by,
                "method": "MANUAL"
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error assigning order to strategy: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/assignment-suggestions/{order_id}", response_model=dict)
async def get_strategy_assignment_suggestions(
    order_id: str,
    db: Session = Depends(get_db)
):
    """
    Get AI/ML suggestions for strategy assignment
    Future enhancement for intelligent assignment
    """
    
    try:
        from shared_architecture.db.models.order_model import OrderModel
        from shared_architecture.db.models.strategy_model import StrategyModel
        
        order = db.query(OrderModel).filter_by(exchange_order_id=order_id).first()
        if not order:
            raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
        
        # Get active strategies for the account
        strategies = db.query(StrategyModel).filter(
            StrategyModel.pseudo_account == order.pseudo_account,
            StrategyModel.status == 'ACTIVE'
        ).all()
        
        suggestions = []
        for strategy in strategies:
            # Simple rule-based suggestions
            # In production, this would use ML models
            
            confidence = 20.0  # Base confidence
            reasons = []
            
            # Check symbol match
            if order.trading_symbol in (strategy.tags or []):
                confidence += 40.0
                reasons.append("Symbol mentioned in strategy tags")
            
            # Check recent activity
            if strategy.updated_at and (datetime.utcnow() - strategy.updated_at).days < 7:
                confidence += 20.0
                reasons.append("Recent strategy activity")
            
            # Check strategy type
            if order.trade_type == 'BUY' and 'long' in (strategy.tags or []):
                confidence += 10.0
                reasons.append("Strategy favors long positions")
            
            suggestions.append({
                'strategy_id': strategy.strategy_id,
                'strategy_name': strategy.strategy_name,
                'confidence_score': min(confidence, 95.0),  # Cap at 95%
                'reasons': reasons,
                'risk_assessment': 'LOW' if confidence > 60 else 'MEDIUM' if confidence > 30 else 'HIGH'
            })
        
        # Sort by confidence
        suggestions.sort(key=lambda x: x['confidence_score'], reverse=True)
        
        return {
            "order_id": order_id,
            "order_details": {
                "trading_symbol": order.trading_symbol,
                "trade_type": order.trade_type,
                "quantity": order.quantity
            },
            "suggestions": suggestions[:5],  # Top 5 suggestions
            "note": "These are rule-based suggestions. ML-based suggestions coming in future versions."
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting assignment suggestions: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))