# app/api/endpoints/health_endpoints.py
"""
Health check endpoints for trade service monitoring.
Provides comprehensive health monitoring and diagnostics.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import JSONResponse
from typing import Dict, Any, Optional, List
from datetime import datetime
import asyncio

from shared_architecture.monitoring.health_checker import (
    HealthChecker, DatabaseHealthCheck, RedisHealthCheck, 
    ExternalAPIHealthCheck, SystemResourceHealthCheck, ApplicationHealthCheck,
    HealthStatus, SystemHealth
)
from shared_architecture.db.database import get_db, engine
from shared_architecture.utils.enhanced_logging import get_logger
from app.core.config import get_settings

router = APIRouter(prefix="/health", tags=["health"])
logger = get_logger(__name__)

# Global health checker instance
health_checker = None

def get_health_checker() -> HealthChecker:
    """Get or create the global health checker instance."""
    global health_checker
    
    if health_checker is None:
        health_checker = HealthChecker()
        
        # Add database health check
        health_checker.add_check(DatabaseHealthCheck(engine))
        
        # Add Redis health check
        settings = get_settings()
        if hasattr(settings, 'redis_url') and settings.redis_url:
            health_checker.add_check(RedisHealthCheck(settings.redis_url))
        
        # Add system resource health check
        health_checker.add_check(SystemResourceHealthCheck())
        
        # Add application health check
        health_checker.add_check(ApplicationHealthCheck())
        
        # Add external API health checks (if configured)
        if hasattr(settings, 'external_apis') and settings.external_apis:
            for api_name, api_config in settings.external_apis.items():
                health_checker.add_check(ExternalAPIHealthCheck(
                    name=api_name,
                    url=api_config.get('health_url', api_config.get('url')),
                    timeout=api_config.get('timeout', 10),
                    expected_status=api_config.get('expected_status', 200)
                ))
    
    return health_checker

@router.get("/", 
    summary="Basic health check",
    description="Quick health check endpoint for load balancers",
    responses={
        200: {"description": "Service is healthy"},
        503: {"description": "Service is unhealthy"},
    }
)
async def health_check():
    """
    Basic health check endpoint.
    
    Returns a simple status for load balancers and uptime monitoring.
    This endpoint is optimized for speed and minimal resource usage.
    """
    try:
        checker = get_health_checker()
        
        # Quick check with cache
        system_health = await checker.check_all(use_cache=True)
        
        if system_health.overall_status in [HealthStatus.HEALTHY, HealthStatus.DEGRADED]:
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "status": "ok",
                    "timestamp": datetime.utcnow().isoformat(),
                    "service": "trade_service"
                }
            )
        else:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={
                    "status": "unhealthy",
                    "timestamp": datetime.utcnow().isoformat(),
                    "service": "trade_service"
                }
            )
            
    except Exception as e:
        logger.error(f"Health check failed: {e}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "error",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
                "service": "trade_service"
            }
        )

@router.get("/detailed",
    summary="Detailed health check",
    description="Comprehensive health check with component details",
    response_model=Dict[str, Any]
)
async def detailed_health_check():
    """
    Detailed health check endpoint.
    
    Returns comprehensive health information including:
    - Overall system status
    - Individual component health
    - Performance metrics
    - System information
    """
    try:
        checker = get_health_checker()
        
        # Full health check without cache for accuracy
        system_health = await checker.check_all(use_cache=False)
        
        # Convert to response format
        response_data = system_health.to_dict()
        
        # Add additional metadata
        response_data.update({
            "service": "trade_service",
            "version": getattr(__import__('app'), '__version__', 'unknown'),
            "environment": get_settings().environment,
            "checks_performed": len(system_health.components),
            "healthy_components": len([
                c for c in system_health.components 
                if c.status == HealthStatus.HEALTHY
            ])
        })
        
        # Set appropriate HTTP status code
        if system_health.overall_status == HealthStatus.HEALTHY:
            status_code = status.HTTP_200_OK
        elif system_health.overall_status == HealthStatus.DEGRADED:
            status_code = status.HTTP_200_OK  # Still operational
        else:
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        
        return JSONResponse(
            status_code=status_code,
            content=response_data
        )
        
    except Exception as e:
        logger.error(f"Detailed health check failed: {e}", exc_info=True)
        
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "overall_status": "error",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
                "service": "trade_service"
            }
        )

@router.get("/component/{component_name}",
    summary="Component health check",
    description="Health check for a specific component",
    response_model=Dict[str, Any]
)
async def component_health_check(component_name: str):
    """
    Check health of a specific component.
    
    Args:
        component_name: Name of the component to check
        
    Returns:
        Health status and details for the specified component
    """
    try:
        checker = get_health_checker()
        
        # Check if component exists
        available_components = checker.get_check_names()
        if component_name not in available_components:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Component '{component_name}' not found. Available: {available_components}"
            )
        
        # Get component health
        result = await checker.get_component_health(component_name)
        
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Component '{component_name}' not found"
            )
        
        # Set status code based on component health
        if result.status == HealthStatus.HEALTHY:
            status_code = status.HTTP_200_OK
        elif result.status == HealthStatus.DEGRADED:
            status_code = status.HTTP_200_OK
        else:
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        
        return JSONResponse(
            status_code=status_code,
            content=result.to_dict()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Component health check failed for {component_name}: {e}", exc_info=True)
        
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "component": component_name,
                "status": "error",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
        )

@router.get("/components",
    summary="List available components",
    description="Get list of all available health check components",
    response_model=List[str]
)
async def list_components():
    """
    List all available health check components.
    
    Returns:
        List of component names that can be checked individually
    """
    try:
        checker = get_health_checker()
        components = checker.get_check_names()
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "components": components,
                "count": len(components),
                "timestamp": datetime.utcnow().isoformat()
            }
        )
        
    except Exception as e:
        logger.error(f"Failed to list components: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list components: {str(e)}"
        )

@router.get("/ready",
    summary="Readiness check",
    description="Kubernetes readiness probe endpoint",
    responses={
        200: {"description": "Service is ready"},
        503: {"description": "Service is not ready"},
    }
)
async def readiness_check():
    """
    Readiness check for Kubernetes deployments.
    
    Checks if the service is ready to receive traffic.
    More strict than liveness check - all critical components must be healthy.
    """
    try:
        checker = get_health_checker()
        system_health = await checker.check_all(use_cache=True)
        
        # For readiness, we're stricter - degraded is not ready
        if system_health.overall_status == HealthStatus.HEALTHY:
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "status": "ready",
                    "timestamp": datetime.utcnow().isoformat()
                }
            )
        else:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={
                    "status": "not_ready",
                    "reason": system_health.overall_status.value,
                    "timestamp": datetime.utcnow().isoformat()
                }
            )
            
    except Exception as e:
        logger.error(f"Readiness check failed: {e}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "error",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
        )

@router.get("/live",
    summary="Liveness check", 
    description="Kubernetes liveness probe endpoint",
    responses={
        200: {"description": "Service is alive"},
        503: {"description": "Service should be restarted"},
    }
)
async def liveness_check():
    """
    Liveness check for Kubernetes deployments.
    
    Checks if the service is alive and should not be restarted.
    Less strict than readiness - degraded is still alive.
    """
    try:
        checker = get_health_checker()
        system_health = await checker.check_all(use_cache=True)
        
        # For liveness, degraded is still alive
        if system_health.overall_status in [HealthStatus.HEALTHY, HealthStatus.DEGRADED]:
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "status": "alive",
                    "timestamp": datetime.utcnow().isoformat()
                }
            )
        else:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={
                    "status": "dead",
                    "reason": system_health.overall_status.value,
                    "timestamp": datetime.utcnow().isoformat()
                }
            )
            
    except Exception as e:
        logger.error(f"Liveness check failed: {e}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "error",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
        )

@router.get("/startup",
    summary="Startup check",
    description="Kubernetes startup probe endpoint", 
    responses={
        200: {"description": "Service has started successfully"},
        503: {"description": "Service is still starting"},
    }
)
async def startup_check():
    """
    Startup check for Kubernetes deployments.
    
    Checks if the service has completed its startup process.
    Used to determine when to start liveness/readiness probes.
    """
    try:
        checker = get_health_checker()
        
        # For startup, we only check critical components
        system_health = await checker.check_all(use_cache=False)
        
        # Check if database and basic components are available
        critical_components = ['database', 'application']
        critical_results = [
            c for c in system_health.components 
            if c.component in critical_components
        ]
        
        all_critical_healthy = all(
            r.status in [HealthStatus.HEALTHY, HealthStatus.DEGRADED]
            for r in critical_results
        )
        
        if all_critical_healthy:
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "status": "started",
                    "timestamp": datetime.utcnow().isoformat(),
                    "critical_components_ready": len(critical_results)
                }
            )
        else:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={
                    "status": "starting",
                    "timestamp": datetime.utcnow().isoformat(),
                    "critical_components_ready": len([
                        r for r in critical_results 
                        if r.status in [HealthStatus.HEALTHY, HealthStatus.DEGRADED]
                    ]),
                    "total_critical_components": len(critical_results)
                }
            )
            
    except Exception as e:
        logger.error(f"Startup check failed: {e}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "error",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
        )

@router.get("/metrics",
    summary="Health metrics",
    description="Health metrics for monitoring systems",
    response_model=Dict[str, Any]
)
async def health_metrics():
    """
    Health metrics endpoint for monitoring systems.
    
    Returns metrics in a format suitable for monitoring tools like Prometheus.
    """
    try:
        checker = get_health_checker()
        system_health = await checker.check_all(use_cache=True)
        
        # Calculate metrics
        total_components = len(system_health.components)
        healthy_components = len([
            c for c in system_health.components 
            if c.status == HealthStatus.HEALTHY
        ])
        degraded_components = len([
            c for c in system_health.components 
            if c.status == HealthStatus.DEGRADED
        ])
        unhealthy_components = len([
            c for c in system_health.components 
            if c.status == HealthStatus.UNHEALTHY
        ])
        
        # Response time metrics
        response_times = [
            c.response_time_ms for c in system_health.components 
            if c.response_time_ms is not None
        ]
        
        avg_response_time = sum(response_times) / len(response_times) if response_times else 0
        max_response_time = max(response_times) if response_times else 0
        
        metrics = {
            "timestamp": system_health.timestamp.isoformat(),
            "overall_status": system_health.overall_status.value,
            "total_response_time_ms": system_health.response_time_ms,
            "component_metrics": {
                "total_components": total_components,
                "healthy_components": healthy_components,
                "degraded_components": degraded_components,
                "unhealthy_components": unhealthy_components,
                "health_percentage": (healthy_components / total_components * 100) if total_components > 0 else 0
            },
            "response_time_metrics": {
                "average_ms": avg_response_time,
                "maximum_ms": max_response_time,
                "total_check_time_ms": system_health.response_time_ms
            },
            "component_details": {
                c.component: {
                    "status": c.status.value,
                    "response_time_ms": c.response_time_ms,
                    "has_error": c.error is not None
                }
                for c in system_health.components
            }
        }
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=metrics
        )
        
    except Exception as e:
        logger.error(f"Health metrics failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get health metrics: {str(e)}"
        )