# app/api/endpoints/management_endpoints.py
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, Dict, List
from sqlalchemy.orm import Session

from shared_architecture.db import get_db
from shared_architecture.db.models.order_discrepancy_model import OrderDiscrepancyModel
from shared_architecture.connections.autotrader_pool import autotrader_pool
from app.services.order_monitoring_service import OrderMonitoringService
from app.services.enhanced_trade_service import EnhancedTradeService
from shared_architecture.utils.redis_data_manager import RedisDataManager
from shared_architecture.connections.connection_manager import connection_manager

router = APIRouter()

async def get_redis_manager():
    """Dependency to get Redis data manager"""
    try:
        redis_conn = await connection_manager.get_redis_connection_async()
        return RedisDataManager(redis_conn)
    except Exception:
        return RedisDataManager(None)

@router.get("/connection-pool/stats")
async def get_connection_pool_stats():
    """Get AutoTrader connection pool statistics"""
    try:
        stats = autotrader_pool.get_connection_stats()
        return {
            "success": True,
            "stats": stats
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/connection-pool/invalidate/{organization_id}")
async def invalidate_organization_connection(organization_id: str, reason: str = "Manual invalidation"):
    """Invalidate AutoTrader connection for a specific organization"""
    try:
        autotrader_pool.invalidate_connection(organization_id)
        return {
            "success": True,
            "message": f"Connection invalidated for organization {organization_id}",
            "reason": reason
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/connection-pool/reset")
async def reset_all_connections():
    """Reset all AutoTrader connections (emergency use)"""
    try:
        stats_before = autotrader_pool.get_connection_stats()
        autotrader_pool.reset_all()
        stats_after = autotrader_pool.get_connection_stats()
        
        return {
            "success": True,
            "message": "All connections reset",
            "connections_cleared": stats_before.get('total_connections', 0),
            "reset_time": stats_after.get('last_reset')
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/discrepancies")
async def get_order_discrepancies(
    organization_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="PENDING, RESOLVED, FAILED"),
    requires_review: Optional[bool] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    db: Session = Depends(get_db)
):
    """Get order discrepancies with optional filtering"""
    try:
        query = db.query(OrderDiscrepancyModel)
        
        if organization_id:
            query = query.filter_by(organization_id=organization_id)
        if status:
            query = query.filter_by(status=status)
        if requires_review is not None:
            query = query.filter_by(requires_manual_review=requires_review)
        
        total = query.count()
        discrepancies = query.offset(offset).limit(limit).all()
        
        return {
            "success": True,
            "total": total,
            "count": len(discrepancies),
            "discrepancies": [d.to_dict() for d in discrepancies]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/discrepancies/{discrepancy_id}/resolve")
async def resolve_discrepancy(
    discrepancy_id: int,
    resolution_notes: str,
    reviewer: str,
    db: Session = Depends(get_db)
):
    """Mark a discrepancy as resolved"""
    try:
        discrepancy = db.query(OrderDiscrepancyModel).filter_by(id=discrepancy_id).first()
        if not discrepancy:
            raise HTTPException(status_code=404, detail="Discrepancy not found")
        
        discrepancy.mark_resolved(resolution_notes)
        discrepancy.reviewed_by = reviewer
        db.commit()
        
        return {
            "success": True,
            "message": "Discrepancy marked as resolved",
            "discrepancy_id": discrepancy_id
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/monitoring/orders")
async def get_order_monitoring_stats():
    """Get statistics about active order monitoring"""
    try:
        # This would need access to the OrderMonitoringService instance
        # For now, return a placeholder
        return {
            "success": True,
            "message": "Order monitoring stats endpoint - implement based on service architecture"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/orders/{order_id}/start-monitoring")
async def start_order_monitoring(
    order_id: int,
    organization_id: str,
    pseudo_account: str,
    db: Session = Depends(get_db),
    redis_manager: RedisDataManager = Depends(get_redis_manager)
):
    """Manually start monitoring an order"""
    try:
        order_monitor = OrderMonitoringService(db, redis_manager)
        success = await order_monitor.start_order_monitoring(order_id, organization_id, pseudo_account)
        
        if success:
            return {
                "success": True,
                "message": f"Started monitoring order {order_id}"
            }
        else:
            raise HTTPException(status_code=400, detail="Failed to start monitoring")
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/orders/{order_id}/stop-monitoring")
async def stop_order_monitoring(
    order_id: int,
    reason: str = "Manual stop",
    db: Session = Depends(get_db),
    redis_manager: RedisDataManager = Depends(get_redis_manager)
):
    """Manually stop monitoring an order"""
    try:
        order_monitor = OrderMonitoringService(db, redis_manager)
        await order_monitor.stop_order_monitoring(order_id, reason)
        
        return {
            "success": True,
            "message": f"Stopped monitoring order {order_id}"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/health/detailed")
async def get_detailed_health():
    """Get detailed health information for the trade service"""
    try:
        # Connection pool health
        pool_stats = autotrader_pool.get_connection_stats()
        pool_health = "HEALTHY" if pool_stats.get('healthy_connections', 0) == pool_stats.get('total_connections', 0) else "DEGRADED"
        
        # Redis health
        redis_health = "UNKNOWN"
        try:
            redis_conn = await connection_manager.get_redis_connection_async()
            if redis_conn:
                await redis_conn.ping()
                redis_health = "HEALTHY"
            else:
                redis_health = "UNAVAILABLE"
        except Exception:
            redis_health = "UNHEALTHY"
        
        return {
            "success": True,
            "timestamp": "now",
            "components": {
                "autotrader_pool": {
                    "status": pool_health,
                    "stats": pool_stats
                },
                "redis": {
                    "status": redis_health
                }
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/emergency/force-sync/{organization_id}/{pseudo_account}")
async def emergency_force_sync(
    organization_id: str,
    pseudo_account: str,
    db: Session = Depends(get_db),
    redis_manager: RedisDataManager = Depends(get_redis_manager)
):
    """Emergency endpoint to force sync all data for an account"""
    try:
        # This could be used when data gets out of sync
        from app.tasks.sync_to_redis_task import sync_account_to_redis
        
        # Queue immediate sync
        task = sync_account_to_redis.delay(organization_id, pseudo_account)
        
        return {
            "success": True,
            "message": f"Emergency sync queued for {pseudo_account}",
            "task_id": task.id
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))