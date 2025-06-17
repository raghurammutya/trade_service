# app/tasks/connection_pool_management.py
import logging
from datetime import datetime

from app.core.celery_config import celery_app
from shared_architecture.connections.autotrader_pool import autotrader_pool

logger = logging.getLogger(__name__)

@celery_app.task(bind=True)
def midnight_connection_reset(self):
    """
    Scheduled task to reset all AutoTrader connections at midnight.
    This ensures fresh connections daily and prevents stale connection issues.
    """
    try:
        stats_before = autotrader_pool.get_connection_stats()
        connections_before = stats_before.get('total_connections', 0)
        
        # Reset all connections
        autotrader_pool.reset_all()
        
        stats_after = autotrader_pool.get_connection_stats()
        
        logger.info(f"Midnight connection reset completed. Cleared {connections_before} connections")
        
        return {
            "status": "success",
            "timestamp": datetime.utcnow().isoformat(),
            "connections_cleared": connections_before,
            "reset_time": stats_after.get('last_reset')
        }
        
    except Exception as e:
        logger.error(f"Failed to reset connections at midnight: {e}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }

@celery_app.task(bind=True)
def cleanup_stale_connections(self):
    """
    Periodic task to clean up stale connections.
    Can be run every few hours to maintain pool health.
    """
    try:
        stats_before = autotrader_pool.get_connection_stats()
        
        # Clean up stale connections
        removed_count = autotrader_pool.cleanup_stale_connections()
        
        stats_after = autotrader_pool.get_connection_stats()
        
        logger.info(f"Cleaned up {removed_count} stale connections")
        
        return {
            "status": "success",
            "timestamp": datetime.utcnow().isoformat(),
            "removed_connections": removed_count,
            "remaining_connections": stats_after.get('total_connections', 0)
        }
        
    except Exception as e:
        logger.error(f"Failed to cleanup stale connections: {e}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }

@celery_app.task(bind=True)
def invalidate_organization_connection(self, organization_id: str, reason: str = "Manual invalidation"):
    """
    Task to invalidate a specific organization's connection.
    Useful when API keys change or authentication issues occur.
    """
    try:
        autotrader_pool.invalidate_connection(organization_id)
        
        logger.info(f"Invalidated connection for organization {organization_id}: {reason}")
        
        return {
            "status": "success",
            "organization_id": organization_id,
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to invalidate connection for {organization_id}: {e}")
        return {
            "status": "error",
            "organization_id": organization_id,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }

@celery_app.task(bind=True)
def get_connection_pool_health(self):
    """
    Health check task for connection pool monitoring.
    Returns detailed statistics about pool state.
    """
    try:
        stats = autotrader_pool.get_connection_stats()
        
        # Calculate health metrics
        total_connections = stats.get('total_connections', 0)
        healthy_connections = stats.get('healthy_connections', 0)
        health_ratio = healthy_connections / total_connections if total_connections > 0 else 1.0
        
        # Determine overall health
        if health_ratio >= 0.9:
            health_status = "HEALTHY"
        elif health_ratio >= 0.7:
            health_status = "DEGRADED"
        else:
            health_status = "UNHEALTHY"
        
        result = {
            "status": "success",
            "timestamp": datetime.utcnow().isoformat(),
            "health_status": health_status,
            "health_ratio": health_ratio,
            "connection_stats": stats
        }
        
        # Log warnings for unhealthy state
        if health_status in ["DEGRADED", "UNHEALTHY"]:
            logger.warning(f"Connection pool health is {health_status}: {healthy_connections}/{total_connections} healthy")
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to get connection pool health: {e}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }