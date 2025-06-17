# app/api/endpoints/redis_data_endpoints.py
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List, Dict
from sqlalchemy.orm import Session

from shared_architecture.db import get_db
from shared_architecture.utils.redis_data_manager import RedisDataManager
from app.services.strategy_service import StrategyService
from shared_architecture.connections.connection_manager import connection_manager

router = APIRouter()

async def get_redis_manager():
    """Dependency to get Redis data manager"""
    try:
        redis_conn = await connection_manager.get_redis_connection_async()
        return RedisDataManager(redis_conn)
    except Exception as e:
        print(f"Failed to get Redis connection: {e}")
        return RedisDataManager(None)  # Fallback to disabled mode

@router.get("/account/{organization_id}/{pseudo_account}/summary")
async def get_account_summary(
    organization_id: str,
    pseudo_account: str,
    redis_manager: RedisDataManager = Depends(get_redis_manager)
):
    """Get complete account summary including all strategies"""
    try:
        summary = await redis_manager.get_account_summary(organization_id, pseudo_account)
        
        if not summary:
            raise HTTPException(
                status_code=404,
                detail="No data found for this account. Data may not be cached yet."
            )
        
        return summary
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/account/{organization_id}/{pseudo_account}/positions")
async def get_positions(
    organization_id: str,
    pseudo_account: str,
    strategy_id: Optional[str] = Query(None, description="Filter by strategy ID"),
    redis_manager: RedisDataManager = Depends(get_redis_manager)
):
    """Get positions for an account, optionally filtered by strategy"""
    try:
        positions = await redis_manager.get_positions(organization_id, pseudo_account, strategy_id)
        return {
            "count": len(positions),
            "positions": positions
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/account/{organization_id}/{pseudo_account}/holdings")
async def get_holdings(
    organization_id: str,
    pseudo_account: str,
    strategy_id: Optional[str] = Query(None, description="Filter by strategy ID"),
    redis_manager: RedisDataManager = Depends(get_redis_manager)
):
    """Get holdings for an account, optionally filtered by strategy"""
    try:
        holdings = await redis_manager.get_holdings(organization_id, pseudo_account, strategy_id)
        return {
            "count": len(holdings),
            "holdings": holdings
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/account/{organization_id}/{pseudo_account}/orders")
async def get_orders(
    organization_id: str,
    pseudo_account: str,
    strategy_id: Optional[str] = Query(None, description="Filter by strategy ID"),
    status: Optional[str] = Query(None, description="Filter by order status"),
    redis_manager: RedisDataManager = Depends(get_redis_manager)
):
    """Get orders for an account, optionally filtered by strategy and status"""
    try:
        orders = await redis_manager.get_orders(organization_id, pseudo_account, strategy_id, status)
        return {
            "count": len(orders),
            "orders": orders
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/account/{organization_id}/{pseudo_account}/margins")
async def get_margins(
    organization_id: str,
    pseudo_account: str,
    strategy_id: Optional[str] = Query(None, description="Filter by strategy ID"),
    redis_manager: RedisDataManager = Depends(get_redis_manager)
):
    """Get margins for an account, optionally filtered by strategy"""
    try:
        margins = await redis_manager.get_margins(organization_id, pseudo_account, strategy_id)
        return {
            "count": len(margins),
            "margins": margins
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/account/{organization_id}/{pseudo_account}/strategies")
async def get_strategies(
    organization_id: str,
    pseudo_account: str,
    redis_manager: RedisDataManager = Depends(get_redis_manager)
):
    """Get list of all strategies for an account"""
    try:
        strategies = await redis_manager.get_all_strategies(organization_id, pseudo_account)
        
        # Get metadata for each strategy
        strategy_details = []
        for strategy_id in strategies:
            metadata = await redis_manager.get_strategy_metadata(
                organization_id, pseudo_account, strategy_id
            )
            strategy_details.append({
                "strategy_id": strategy_id,
                "metadata": metadata
            })
        
        return {
            "count": len(strategies),
            "strategies": strategy_details
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/strategy/{organization_id}/{pseudo_account}/{strategy_id}")
async def get_strategy_data(
    organization_id: str,
    pseudo_account: str,
    strategy_id: str,
    redis_manager: RedisDataManager = Depends(get_redis_manager)
):
    """Get all data for a specific strategy"""
    try:
        data = {
            "strategy_id": strategy_id,
            "metadata": await redis_manager.get_strategy_metadata(
                organization_id, pseudo_account, strategy_id
            ),
            "positions": await redis_manager.get_positions(
                organization_id, pseudo_account, strategy_id
            ),
            "holdings": await redis_manager.get_holdings(
                organization_id, pseudo_account, strategy_id
            ),
            "orders": await redis_manager.get_orders(
                organization_id, pseudo_account, strategy_id
            ),
            "margins": await redis_manager.get_margins(
                organization_id, pseudo_account, strategy_id
            )
        }
        
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/strategy/{organization_id}/{pseudo_account}/split")
async def split_data_to_strategy(
    organization_id: str,
    pseudo_account: str,
    request: Dict,
    db: Session = Depends(get_db),
    redis_manager: RedisDataManager = Depends(get_redis_manager)
):
    """
    Split data from one strategy to another
    
    Request body:
    {
        "source_strategy_id": "default",
        "target_strategy_id": "batman",
        "allocations": [
            {
                "instrument_key": "NSE@RELIANCE@equities",
                "data_type": "position",
                "quantity": 100,
                "price": 2500.0
            }
        ]
    }
    """
    try:
        strategy_service = StrategyService(db, redis_manager)
        
        # Validate allocations first
        is_valid, errors = await strategy_service.validate_strategy_allocation(
            organization_id, pseudo_account, request['allocations']
        )
        
        if not is_valid:
            raise HTTPException(
                status_code=400,
                detail={"message": "Invalid allocations", "errors": errors}
            )
        
        # Perform the split
        result = await strategy_service.split_data_to_strategy(
            organization_id,
            pseudo_account,
            request['source_strategy_id'],
            request['target_strategy_id'],
            request['allocations']
        )
        
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/cache/{organization_id}/{pseudo_account}")
async def clear_account_cache(
    organization_id: str,
    pseudo_account: str,
    strategy_id: Optional[str] = Query(None, description="Clear specific strategy only"),
    redis_manager: RedisDataManager = Depends(get_redis_manager)
):
    """Clear cached data for an account or specific strategy"""
    try:
        if strategy_id:
            success = await redis_manager.invalidate_strategy_data(
                organization_id, pseudo_account, strategy_id
            )
            message = f"Strategy {strategy_id} cache cleared" if success else "Failed to clear strategy cache"
        else:
            success = await redis_manager.clear_account_data(organization_id, pseudo_account)
            message = f"Account {pseudo_account} cache cleared" if success else "Failed to clear account cache"
        
        return {"success": success, "message": message}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/sync/{organization_id}/{pseudo_account}")
async def sync_from_database(
    organization_id: str,
    pseudo_account: str,
    strategy_id: Optional[str] = Query(None, description="Sync specific strategy only"),
    db: Session = Depends(get_db),
    redis_manager: RedisDataManager = Depends(get_redis_manager)
):
    """Force sync data from database to Redis cache"""
    try:
        from shared_architecture.db.models.position_model import PositionModel
        from shared_architecture.db.models.holding_model import HoldingModel
        from shared_architecture.db.models.order_model import OrderModel
        from shared_architecture.db.models.margin_model import MarginModel
        
        if strategy_id:
            # Sync specific strategy
            positions = db.query(PositionModel).filter_by(
                pseudo_account=pseudo_account,
                strategy_id=strategy_id
            ).all()
            
            holdings = db.query(HoldingModel).filter_by(
                pseudo_account=pseudo_account,
                strategy_id=strategy_id
            ).all()
            
            orders = db.query(OrderModel).filter_by(
                pseudo_account=pseudo_account,
                strategy_id=strategy_id
            ).all()
            
            margins = db.query(MarginModel).filter_by(
                pseudo_account=pseudo_account,
                strategy_id=strategy_id
            ).all()
            
            # Store in Redis
            await redis_manager.store_positions(organization_id, pseudo_account, positions, strategy_id)
            await redis_manager.store_holdings(organization_id, pseudo_account, holdings, strategy_id)
            await redis_manager.store_orders(organization_id, pseudo_account, orders, strategy_id)
            await redis_manager.store_margins(organization_id, pseudo_account, margins, strategy_id)
            
            message = f"Synced strategy {strategy_id} data to Redis"
        else:
            # Sync all data for account
            positions = db.query(PositionModel).filter_by(pseudo_account=pseudo_account).all()
            holdings = db.query(HoldingModel).filter_by(pseudo_account=pseudo_account).all()
            orders = db.query(OrderModel).filter_by(pseudo_account=pseudo_account).all()
            margins = db.query(MarginModel).filter_by(pseudo_account=pseudo_account).all()
            
            # Group by strategy
            strategies = set()
            for item in positions + holdings + orders + margins:
                if hasattr(item, 'strategy_id') and item.strategy_id:
                    strategies.add(item.strategy_id)
            
            # Store blanket data (no strategy)
            blanket_positions = [p for p in positions if not p.strategy_id]
            blanket_holdings = [h for h in holdings if not h.strategy_id]
            blanket_orders = [o for o in orders if not o.strategy_id]
            blanket_margins = [m for m in margins if not m.strategy_id]
            
            await redis_manager.store_positions(organization_id, pseudo_account, blanket_positions)
            await redis_manager.store_holdings(organization_id, pseudo_account, blanket_holdings)
            await redis_manager.store_orders(organization_id, pseudo_account, blanket_orders)
            await redis_manager.store_margins(organization_id, pseudo_account, blanket_margins)
            
            # Store strategy-wise data
            for strat_id in strategies:
                strat_positions = [p for p in positions if p.strategy_id == strat_id]
                strat_holdings = [h for h in holdings if h.strategy_id == strat_id]
                strat_orders = [o for o in orders if o.strategy_id == strat_id]
                strat_margins = [m for m in margins if m.strategy_id == strat_id]
                
                await redis_manager.store_positions(organization_id, pseudo_account, strat_positions, strat_id)
                await redis_manager.store_holdings(organization_id, pseudo_account, strat_holdings, strat_id)
                await redis_manager.store_orders(organization_id, pseudo_account, strat_orders, strat_id)
                await redis_manager.store_margins(organization_id, pseudo_account, strat_margins, strat_id)
            
            message = f"Synced all data for {pseudo_account} to Redis ({len(strategies)} strategies)"
        
        return {
            "success": True,
            "message": message,
            "counts": {
                "positions": len(positions),
                "holdings": len(holdings),
                "orders": len(orders),
                "margins": len(margins)
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))