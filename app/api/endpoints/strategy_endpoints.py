from fastapi import APIRouter, Depends, HTTPException, Query, Body
from typing import List, Optional
from sqlalchemy.orm import Session

from shared_architecture.db.session import get_db
from shared_architecture.schemas.strategy_schema import (
    StrategyCreate, StrategyUpdate, StrategyResponse, StrategySummary, StrategyListResponse,
    StrategyTaggingRequest, StrategyTaggingResponse,
    PositionTaggingRequest, OrderTaggingRequest, HoldingTaggingRequest,
    StrategySquareOffPreview, StrategySquareOffRequest, StrategySquareOffResponse
)
from app.services.strategy_management_service import StrategyManagementService
from shared_architecture.errors.custom_exceptions import ValidationError, BusinessLogicError

router = APIRouter(prefix="/strategy", tags=["strategy_management"])

@router.post("/create", response_model=StrategyResponse)
async def create_strategy(
    strategy_data: StrategyCreate,
    created_by: str = Query(..., description="User creating the strategy"),
    db: Session = Depends(get_db)
):
    """
    Create a new trading strategy
    
    **Features:**
    - Auto-generates strategy ID if not provided
    - Validates strategy configuration
    - Sets up risk management parameters
    - Initializes performance tracking
    """
    try:
        service = StrategyManagementService(db)
        return await service.create_strategy(strategy_data, created_by)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create strategy: {str(e)}")

@router.get("/{strategy_id}", response_model=StrategyResponse)
async def get_strategy(
    strategy_id: str,
    db: Session = Depends(get_db)
):
    """
    Get strategy details with real-time metrics
    
    **Returns:**
    - Complete strategy configuration
    - Current performance metrics
    - Position/order/holding counts
    - PnL breakdown
    """
    try:
        service = StrategyManagementService(db)
        strategy = await service.get_strategy(strategy_id)
        if not strategy:
            raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")
        return strategy
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get strategy: {str(e)}")

@router.put("/{strategy_id}", response_model=StrategyResponse)
async def update_strategy(
    strategy_id: str,
    update_data: StrategyUpdate,
    updated_by: str = Query(..., description="User updating the strategy"),
    db: Session = Depends(get_db)
):
    """
    Update strategy configuration and settings
    
    **Updatable Fields:**
    - Name, description, status
    - Risk management parameters
    - Auto square-off settings
    - Tags and configuration
    """
    try:
        service = StrategyManagementService(db)
        strategy = await service.update_strategy(strategy_id, update_data, updated_by)
        if not strategy:
            raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")
        return strategy
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update strategy: {str(e)}")

@router.delete("/{strategy_id}")
async def delete_strategy(
    strategy_id: str,
    db: Session = Depends(get_db)
):
    """
    Delete strategy with comprehensive validation
    
    **Safety Checks:**
    - Prevents deletion if active positions exist
    - Prevents deletion if active orders exist
    - Cleans up entity relationships
    - Maintains data integrity
    """
    try:
        service = StrategyManagementService(db)
        success = await service.delete_strategy(strategy_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")
        return {"message": f"Strategy {strategy_id} deleted successfully"}
    except BusinessLogicError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete strategy: {str(e)}")

@router.get("/list/{pseudo_account}", response_model=StrategyListResponse)
async def list_strategies(
    pseudo_account: str,
    organization_id: str = Query(..., description="Organization ID"),
    db: Session = Depends(get_db)
):
    """
    List all strategies for an account with summary metrics
    
    **Returns:**
    - Strategy summaries with key metrics
    - Top positions by PnL
    - Recent orders
    - Holdings summary
    - Aggregate statistics
    """
    try:
        service = StrategyManagementService(db)
        strategies = await service.list_strategies(pseudo_account, organization_id)
        
        # Calculate aggregate metrics
        total_pnl = sum(s.total_pnl for s in strategies)
        total_margin = sum(s.total_margin_used for s in strategies)
        active_count = len([s for s in strategies if s.status.value == "ACTIVE"])
        
        return StrategyListResponse(
            strategies=strategies,
            total_count=len(strategies),
            active_count=active_count,
            total_pnl=total_pnl,
            total_margin_used=total_margin
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list strategies: {str(e)}")

# Position Tagging Endpoints
@router.post("/{strategy_id}/tag-positions", response_model=StrategyTaggingResponse)
async def tag_positions_to_strategy(
    strategy_id: str,
    request: PositionTaggingRequest,
    db: Session = Depends(get_db)
):
    """
    Tag positions to a strategy
    
    **Features:**
    - Bulk position tagging
    - Account validation
    - Overwrite protection
    - Detailed results with error handling
    """
    try:
        service = StrategyManagementService(db)
        return await service.tag_positions(strategy_id, request)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to tag positions: {str(e)}")

@router.post("/{strategy_id}/tag-orders", response_model=StrategyTaggingResponse)
async def tag_orders_to_strategy(
    strategy_id: str,
    request: OrderTaggingRequest,
    db: Session = Depends(get_db)
):
    """
    Tag orders to a strategy
    
    **Features:**
    - Bulk order tagging
    - Account validation
    - Overwrite protection
    - Comprehensive error reporting
    """
    try:
        service = StrategyManagementService(db)
        return await service.tag_orders(strategy_id, request)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to tag orders: {str(e)}")

@router.post("/{strategy_id}/tag-holdings", response_model=StrategyTaggingResponse)
async def tag_holdings_to_strategy(
    strategy_id: str,
    request: HoldingTaggingRequest,
    db: Session = Depends(get_db)
):
    """
    Tag holdings to a strategy
    
    **Features:**
    - Bulk holding tagging
    - Account validation
    - Overwrite protection
    - Detailed response with status tracking
    """
    try:
        service = StrategyManagementService(db)
        return await service.tag_holdings(strategy_id, request)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to tag holdings: {str(e)}")

# Strategy Data Retrieval Endpoints
@router.get("/{strategy_id}/positions")
async def get_strategy_positions(
    strategy_id: str,
    db: Session = Depends(get_db)
):
    """Get all positions tagged to a strategy"""
    from shared_architecture.db.models.position_model import PositionModel
    
    positions = db.query(PositionModel).filter_by(strategy_id=strategy_id).all()
    return {
        "strategy_id": strategy_id,
        "positions": [
            {
                "id": p.id,
                "trading_symbol": p.symbol,
                "exchange": p.exchange,
                "instrument_key": p.instrument_key,
                "net_quantity": p.net_quantity,
                "buy_avg_price": p.buy_avg_price,
                "sell_avg_price": p.sell_avg_price,
                "ltp": p.ltp,
                "unrealized_pnl": p.unrealised_pnl,
                "realized_pnl": p.realised_pnl,
                "product_type": p.type
            } for p in positions
        ],
        "total_positions": len(positions),
        "active_positions": len([p for p in positions if p.net_quantity != 0])
    }

@router.get("/{strategy_id}/orders")
async def get_strategy_orders(
    strategy_id: str,
    status_filter: Optional[str] = Query(None, description="Filter by order status"),
    db: Session = Depends(get_db)
):
    """Get all orders tagged to a strategy"""
    from shared_architecture.db.models.order_model import OrderModel
    
    query = db.query(OrderModel).filter_by(strategy_id=strategy_id)
    if status_filter:
        query = query.filter_by(status=status_filter)
    
    orders = query.order_by(OrderModel.timestamp.desc()).all()
    return {
        "strategy_id": strategy_id,
        "orders": [
            {
                "order_id": o.exchange_order_id,
                "trading_symbol": o.symbol,
                "exchange": o.exchange,
                "order_type": o.order_type,
                "quantity": o.quantity,
                "price": o.price,
                "status": o.status,
                "filled_quantity": o.filled_quantity,
                "created_at": o.timestamp.isoformat() if o.timestamp else None
            } for o in orders
        ],
        "total_orders": len(orders)
    }

@router.get("/{strategy_id}/holdings")
async def get_strategy_holdings(
    strategy_id: str,
    db: Session = Depends(get_db)
):
    """Get all holdings tagged to a strategy"""
    from shared_architecture.db.models.holding_model import HoldingModel
    
    holdings = db.query(HoldingModel).filter_by(strategy_id=strategy_id).all()
    return {
        "strategy_id": strategy_id,
        "holdings": [
            {
                "id": h.id,
                "trading_symbol": h.symbol,
                "exchange": h.exchange,
                "instrument_key": h.instrument_key,
                "quantity": h.quantity,
                "average_price": h.avg_price,
                "current_price": h.ltp,
                "current_value": h.current_value,
                "pnl": h.pnl
            } for h in holdings
        ],
        "total_holdings": len(holdings),
        "total_value": sum(h.current_value or 0 for h in holdings)
    }

@router.get("/{strategy_id}/summary")
async def get_strategy_summary(
    strategy_id: str,
    db: Session = Depends(get_db)
):
    """Get comprehensive strategy summary with all data"""
    try:
        service = StrategyManagementService(db)
        strategy = await service.get_strategy(strategy_id)
        if not strategy:
            raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")
        
        # Get detailed data
        positions_response = await get_strategy_positions(strategy_id, db)
        orders_response = await get_strategy_orders(strategy_id, db=db)
        holdings_response = await get_strategy_holdings(strategy_id, db)
        
        return {
            "strategy": strategy,
            "positions": positions_response,
            "orders": orders_response,
            "holdings": holdings_response
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get strategy summary: {str(e)}")

# Square-off Endpoints
@router.get("/{strategy_id}/square-off/preview", response_model=StrategySquareOffPreview)
async def preview_strategy_square_off(
    strategy_id: str,
    db: Session = Depends(get_db)
):
    """
    Preview strategy square-off without executing
    
    **Returns:**
    - Estimated orders to be placed
    - PnL impact calculation
    - Margin release estimate
    - Warnings and recommendations
    """
    try:
        service = StrategyManagementService(db)
        return await service.preview_square_off(strategy_id)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to preview square-off: {str(e)}")

@router.post("/{strategy_id}/square-off", response_model=StrategySquareOffResponse)
async def execute_strategy_square_off(
    strategy_id: str,
    request: StrategySquareOffRequest,
    db: Session = Depends(get_db)
):
    """
    Execute strategy square-off
    
    **WARNING: This will close all positions and holdings in the strategy**
    
    **Features:**
    - Requires explicit confirmation
    - Supports dry-run mode
    - Batch processing for large strategies
    - Comprehensive error handling
    - Data integrity protection
    
    **Note:** Current implementation simulates order placement.
    Production version requires integration with actual broker APIs.
    """
    try:
        service = StrategyManagementService(db)
        return await service.square_off_strategy(strategy_id, request)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except BusinessLogicError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to execute square-off: {str(e)}")

# Utility Endpoints
@router.post("/{strategy_id}/recalculate-metrics")
async def recalculate_strategy_metrics(
    strategy_id: str,
    db: Session = Depends(get_db)
):
    """Manually trigger strategy metrics recalculation"""
    try:
        service = StrategyManagementService(db)
        strategy = await service.get_strategy(strategy_id)
        if not strategy:
            raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")
        
        return {"message": f"Metrics recalculated for strategy {strategy_id}", "strategy": strategy}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to recalculate metrics: {str(e)}")

@router.get("/{strategy_id}/risk-metrics")
async def get_strategy_risk_metrics(
    strategy_id: str,
    db: Session = Depends(get_db)
):
    """Get detailed risk metrics for strategy"""
    # This would integrate with margin calculation service
    # For now, return basic metrics
    try:
        service = StrategyManagementService(db)
        strategy = await service.get_strategy(strategy_id)
        if not strategy:
            raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")
        
        return {
            "strategy_id": strategy_id,
            "current_pnl": strategy.total_pnl,
            "unrealized_pnl": strategy.unrealized_pnl,
            "margin_used": strategy.total_margin_used,
            "max_loss_limit": strategy.max_loss_amount,
            "max_profit_target": strategy.max_profit_amount,
            "risk_metrics": {
                "loss_percentage": (strategy.total_pnl / strategy.max_loss_amount * 100) if strategy.max_loss_amount > 0 else 0,
                "profit_percentage": (strategy.total_pnl / strategy.max_profit_amount * 100) if strategy.max_profit_amount > 0 else 0,
                "position_utilization": (strategy.active_positions_count / strategy.max_positions * 100) if strategy.max_positions > 0 else 0
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get risk metrics: {str(e)}")