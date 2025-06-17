# app/api/endpoints/strategy_retagging_endpoints.py
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Dict, Optional
from sqlalchemy.orm import Session

from shared_architecture.db import get_db
from shared_architecture.db.models.position_model import PositionModel
from shared_architecture.db.models.holding_model import HoldingModel
from shared_architecture.db.models.order_model import OrderModel
from shared_architecture.utils.data_consistency_validator import DataConsistencyValidator
from shared_architecture.utils.redis_data_manager import RedisDataManager
from shared_architecture.connections.connection_manager import connection_manager
from app.services.strategy_service import StrategyService

router = APIRouter()

async def get_redis_manager():
    """Dependency to get Redis data manager"""
    try:
        redis_conn = await connection_manager.get_redis_connection_async()
        return RedisDataManager(redis_conn)
    except Exception:
        return RedisDataManager(None)

@router.get("/account/{organization_id}/{pseudo_account}/selectable-data")
async def get_selectable_data(
    organization_id: str,
    pseudo_account: str,
    data_type: str = Query(..., description="positions, holdings, or orders"),
    strategy_id: Optional[str] = Query(None, description="Filter by strategy"),
    instrument_key: Optional[str] = Query(None, description="Filter by instrument"),
    db: Session = Depends(get_db)
):
    """
    Get data that can be selected for strategy retagging.
    Returns data with quantities and prices that can be allocated to strategies.
    """
    try:
        if data_type not in ['positions', 'holdings', 'orders']:
            raise HTTPException(status_code=400, detail="data_type must be positions, holdings, or orders")
        
        # Build query based on data type
        if data_type == 'positions':
            query = db.query(PositionModel).filter_by(pseudo_account=pseudo_account)
            if strategy_id:
                query = query.filter_by(strategy_id=strategy_id)
            if instrument_key:
                query = query.filter_by(instrument_key=instrument_key)
            
            data = query.all()
            
            # Convert to selectable format
            selectable_items = []
            for position in data:
                if position.net_quantity != 0:  # Only include non-zero positions
                    selectable_items.append({
                        'id': position.id,
                        'instrument_key': position.instrument_key,
                        'symbol': position.symbol,
                        'exchange': position.exchange,
                        'strategy_id': position.strategy_id or 'default',
                        'net_quantity': position.net_quantity,
                        'buy_quantity': position.buy_quantity or 0,
                        'sell_quantity': position.sell_quantity or 0,
                        'buy_avg_price': position.buy_avg_price or 0.0,
                        'sell_avg_price': position.sell_avg_price or 0.0,
                        'direction': position.direction,
                        'current_value': (position.net_quantity or 0) * (position.ltp or 0),
                        'unrealized_pnl': position.unrealised_pnl or 0.0,
                        'data_type': 'position'
                    })
        
        elif data_type == 'holdings':
            query = db.query(HoldingModel).filter_by(pseudo_account=pseudo_account)
            if strategy_id:
                query = query.filter_by(strategy_id=strategy_id)
            if instrument_key:
                query = query.filter_by(instrument_key=instrument_key)
            
            data = query.all()
            
            selectable_items = []
            for holding in data:
                if holding.quantity > 0:
                    selectable_items.append({
                        'id': holding.id,
                        'instrument_key': holding.instrument_key,
                        'symbol': holding.symbol,
                        'exchange': holding.exchange,
                        'strategy_id': holding.strategy_id or 'default',
                        'quantity': holding.quantity,
                        'avg_price': holding.avg_price or 0.0,
                        'current_value': holding.current_value or 0.0,
                        'ltp': holding.ltp or 0.0,
                        'pnl': holding.pnl or 0.0,
                        'data_type': 'holding'
                    })
        
        elif data_type == 'orders':
            query = db.query(OrderModel).filter_by(pseudo_account=pseudo_account)
            if strategy_id:
                query = query.filter_by(strategy_id=strategy_id)
            if instrument_key:
                query = query.filter_by(instrument_key=instrument_key)
            
            # Only include completed orders for retagging
            query = query.filter(OrderModel.status.in_(['COMPLETE', 'PARTIALLY_FILLED']))
            
            data = query.all()
            
            selectable_items = []
            for order in data:
                selectable_items.append({
                    'id': order.id,
                    'instrument_key': order.instrument_key,
                    'symbol': order.symbol,
                    'exchange': order.exchange,
                    'strategy_id': order.strategy_id or 'default',
                    'quantity': order.quantity,
                    'filled_quantity': order.filled_quantity or 0,
                    'price': order.price,
                    'average_price': order.average_price or order.price,
                    'trade_type': order.trade_type,
                    'order_type': order.order_type,
                    'status': order.status,
                    'platform_time': order.platform_time.isoformat() if order.platform_time else None,
                    'data_type': 'order'
                })
        
        return {
            'success': True,
            'data_type': data_type,
            'count': len(selectable_items),
            'items': selectable_items
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/account/{organization_id}/{pseudo_account}/strategies")
async def get_available_strategies(
    organization_id: str,
    pseudo_account: str,
    db: Session = Depends(get_db)
):
    """Get list of available strategies for an account"""
    try:
        # Get unique strategy IDs from all data types
        position_strategies = db.query(PositionModel.strategy_id).filter_by(
            pseudo_account=pseudo_account
        ).distinct().all()
        
        holding_strategies = db.query(HoldingModel.strategy_id).filter_by(
            pseudo_account=pseudo_account
        ).distinct().all()
        
        order_strategies = db.query(OrderModel.strategy_id).filter_by(
            pseudo_account=pseudo_account
        ).distinct().all()
        
        # Combine and clean up
        all_strategies = set()
        for result in position_strategies + holding_strategies + order_strategies:
            if result[0] and result[0] != 'default':
                all_strategies.add(result[0])
        
        # Add default strategy
        strategies = [
            {'strategy_id': 'default', 'name': 'Default/Blanket', 'is_default': True}
        ]
        
        for strategy_id in sorted(all_strategies):
            strategies.append({
                'strategy_id': strategy_id,
                'name': strategy_id.replace('_', ' ').title(),
                'is_default': False
            })
        
        return {
            'success': True,
            'count': len(strategies),
            'strategies': strategies
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/validate-retagging")
async def validate_retagging_request(
    request: Dict,
    db: Session = Depends(get_db)
):
    """
    Validate a strategy retagging request before execution.
    
    Request format:
    {
        "organization_id": "org123",
        "pseudo_account": "user456",
        "source_strategy_id": "strategy1",
        "target_strategy_id": "strategy2",
        "allocations": [
            {
                "instrument_key": "NSE@RELIANCE@equities",
                "data_type": "position",
                "quantity": 50,
                "price": 1000.0
            }
        ]
    }
    """
    try:
        validator = DataConsistencyValidator(db)
        
        is_valid, errors = validator.validate_strategy_retagging(
            request['organization_id'],
            request['pseudo_account'], 
            request
        )
        
        if is_valid:
            return {
                'success': True,
                'valid': True,
                'message': 'Retagging request is valid'
            }
        else:
            return {
                'success': True,
                'valid': False,
                'errors': errors
            }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/execute-retagging")
async def execute_strategy_retagging(
    request: Dict,
    db: Session = Depends(get_db),
    redis_manager: RedisDataManager = Depends(get_redis_manager)
):
    """
    Execute strategy retagging after validation.
    """
    try:
        # First validate the request
        validator = DataConsistencyValidator(db)
        is_valid, errors = validator.validate_strategy_retagging(
            request['organization_id'],
            request['pseudo_account'],
            request
        )
        
        if not is_valid:
            raise HTTPException(
                status_code=400,
                detail={'message': 'Validation failed', 'errors': errors}
            )
        
        # Execute the retagging
        strategy_service = StrategyService(db, redis_manager)
        result = await strategy_service.split_data_to_strategy(
            request['organization_id'],
            request['pseudo_account'],
            request['source_strategy_id'],
            request['target_strategy_id'],
            request['allocations']
        )
        
        return {
            'success': True,
            'message': 'Strategy retagging completed successfully',
            'result': result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/create-strategy")
async def create_new_strategy(
    request: Dict,
    db: Session = Depends(get_db),
    redis_manager: RedisDataManager = Depends(get_redis_manager)
):
    """
    Create a new strategy and optionally allocate data to it.
    
    Request format:
    {
        "organization_id": "org123",
        "pseudo_account": "user456",
        "strategy_name": "Iron Condor",
        "strategy_id": "iron_condor",
        "description": "Options iron condor strategy",
        "initial_allocations": [...]  # Optional
    }
    """
    try:
        organization_id = request['organization_id']
        pseudo_account = request['pseudo_account']
        strategy_id = request['strategy_id']
        
        # Store strategy metadata
        if redis_manager:
            metadata = {
                'name': request.get('strategy_name', strategy_id),
                'description': request.get('description', ''),
                'created_at': 'now',
                'created_by': 'user',  # Could be passed in request
                'positions_count': 0,
                'holdings_count': 0,
                'orders_count': 0
            }
            
            await redis_manager.store_strategy_metadata(
                organization_id, pseudo_account, strategy_id, metadata
            )
        
        # If initial allocations provided, execute them
        if 'initial_allocations' in request and request['initial_allocations']:
            strategy_service = StrategyService(db, redis_manager)
            
            allocation_request = {
                'source_strategy_id': 'default',
                'target_strategy_id': strategy_id,
                'allocations': request['initial_allocations']
            }
            
            # Validate first
            validator = DataConsistencyValidator(db)
            is_valid, errors = validator.validate_strategy_retagging(
                organization_id, pseudo_account, allocation_request
            )
            
            if not is_valid:
                raise HTTPException(
                    status_code=400,
                    detail={'message': 'Initial allocation validation failed', 'errors': errors}
                )
            
            # Execute allocation
            allocation_result = await strategy_service.split_data_to_strategy(
                organization_id, pseudo_account, 'default',
                strategy_id, request['initial_allocations']
            )
            
            return {
                'success': True,
                'message': f'Strategy {strategy_id} created with initial allocations',
                'strategy_id': strategy_id,
                'allocation_result': allocation_result
            }
        
        return {
            'success': True,
            'message': f'Strategy {strategy_id} created successfully',
            'strategy_id': strategy_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/consistency-check/{organization_id}/{pseudo_account}")
async def check_data_consistency(
    organization_id: str,
    pseudo_account: str,
    data_types: Optional[str] = Query("positions,holdings,orders", description="Comma-separated data types"),
    db: Session = Depends(get_db)
):
    """
    Check data consistency between blanket and strategy datasets.
    """
    try:
        validator = DataConsistencyValidator(db)
        
        # Parse data types
        types_to_check = [t.strip() for t in data_types.split(',')]
        
        # Run consistency check
        issues = validator.validate_account_consistency(
            organization_id, pseudo_account, types_to_check
        )
        
        # Categorize issues by severity
        critical_issues = [i for i in issues if i.severity == 'CRITICAL']
        high_issues = [i for i in issues if i.severity == 'HIGH']
        medium_issues = [i for i in issues if i.severity == 'MEDIUM']
        low_issues = [i for i in issues if i.severity == 'LOW']
        
        return {
            'success': True,
            'is_consistent': len(issues) == 0,
            'total_issues': len(issues),
            'issues_by_severity': {
                'critical': len(critical_issues),
                'high': len(high_issues),
                'medium': len(medium_issues),
                'low': len(low_issues)
            },
            'issues': [issue.to_dict() for issue in issues],
            'recommendation': 'IMMEDIATE_ATTENTION' if critical_issues else 
                           'REVIEW_REQUIRED' if high_issues else 
                           'MONITOR' if medium_issues else 'OK'
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))