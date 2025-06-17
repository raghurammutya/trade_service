"""
Deprecated: Use shared_architecture.connections.enhanced_connection_manager instead.

This module is kept for backward compatibility.
"""

import warnings
from shared_architecture.connections.enhanced_connection_manager import (
    enhanced_connection_manager,
    ServiceStatus,
    MockRedis
)

warnings.warn(
    "app.utils.resilient_connection_manager is deprecated. "
    "Use shared_architecture.connections.enhanced_connection_manager instead.",
    DeprecationWarning,
    stacklevel=2
)

# Backward compatibility aliases
ResilientConnectionManager = type(enhanced_connection_manager)
resilient_manager = enhanced_connection_manager

def get_resilient_redis():
    """Get Redis connection with full resilience (backward compatibility)."""
    return enhanced_connection_manager.get_redis_connection()

def get_infrastructure_health():
    """Get comprehensive infrastructure health status (backward compatibility)."""
    import asyncio
    return asyncio.run(enhanced_connection_manager.health_check())

# Re-export for backward compatibility
__all__ = [
    'ResilientConnectionManager',
    'resilient_manager',
    'ServiceStatus',
    'MockRedis',
    'get_resilient_redis',
    'get_infrastructure_health'
]