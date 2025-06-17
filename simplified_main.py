# trade_service/simplified_main.py
"""
Simplified trade service main.py using the comprehensive service utility.
This demonstrates how much simpler microservice initialization becomes
when all infrastructure concerns are handled by shared_architecture.
"""

import sys
import os
from fastapi import BackgroundTasks

# Ensure shared_architecture is in path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "shared_architecture"))

# Import the comprehensive service utility
from shared_architecture.utils.comprehensive_service_utils import (
    start_service, 
    ServiceConfig, 
    ServiceType
)

# Import business logic routers
from app.api.endpoints import (
    trade_endpoints,
    ledger_endpoints,
    redis_data_endpoints,
    management_endpoints,
    strategy_endpoints,
    historical_import_endpoints,
    external_order_endpoints,
    position_generation_endpoints
)

# Import any custom startup/shutdown tasks
from app.core.dependencies import setup_trade_service_dependencies
from app.services.strategy_service import initialize_strategy_cache

# Custom startup tasks for trade service
async def setup_database_tables(app):
    """Ensure all required database tables exist."""
    from shared_architecture.db.models.holding_model import Base as HoldingBase
    from shared_architecture.db.models.position_model import Base as PositionBase
    from shared_architecture.db.models.order_model import Base as OrderBase
    from shared_architecture.db.models.margin_model import Base as MarginBase
    from shared_architecture.db.models.order_event_model import Base as OrderEventBase
    from shared_architecture.db.models.strategy_model import Base as StrategyBase
    from shared_architecture.db.session import sync_engine
    from shared_architecture.utils.logging_utils import log_info, log_exception
    
    try:
        # Create all tables
        for base in [HoldingBase, PositionBase, OrderBase, MarginBase, OrderEventBase, StrategyBase]:
            base.metadata.create_all(bind=sync_engine)
        log_info("✅ Database tables created/verified")
    except Exception as e:
        log_exception(f"❌ Failed to create database tables: {e}")
        raise

async def initialize_trade_components(app):
    """Initialize trade service specific components."""
    from shared_architecture.utils.logging_utils import log_info
    from app.core.config import settings
    
    # Store trade service settings
    app.state.trade_settings = settings
    
    # Initialize strategy cache
    await initialize_strategy_cache(app)
    
    # Setup any other trade-specific components
    log_info("✅ Trade service components initialized")

# Custom shutdown tasks
async def cleanup_trade_resources(app):
    """Clean up trade service specific resources."""
    from shared_architecture.utils.logging_utils import log_info
    
    # Cleanup any trade-specific resources
    # Example: close market data feeds, flush pending orders, etc.
    log_info("✅ Trade service resources cleaned up")

# Periodic background task example
async def update_strategy_performance_metrics(app):
    """Update strategy performance metrics periodically."""
    from shared_architecture.utils.logging_utils import log_info
    try:
        # This would update strategy performance metrics
        log_info("📊 Strategy performance metrics updated")
    except Exception as e:
        log_info(f"❌ Error updating strategy metrics: {e}")

# Configuration for the trade service
trade_service_config = ServiceConfig(
    service_name="trade_service",
    service_type=ServiceType.TRADE,
    
    # Infrastructure requirements
    required_services=["timescaledb", "redis"],
    optional_services=["rabbitmq", "mongodb"],
    
    # API configuration
    title="Trade Service API",
    description="Comprehensive trading operations and strategy management",
    version="2.0.0",
    
    # Server settings
    port=8004,
    debug=False,
    
    # Security and performance
    enable_cors=True,
    cors_origins=["http://localhost:3000", "http://localhost:8080"],  # Frontend origins
    enable_rate_limiting=True,
    rate_limit_default="1000/minute",  # High throughput for trading
    enable_compression=True,
    
    # Observability
    enable_request_logging=True,
    enable_metrics=True,
    enable_health_checks=True,
    
    # Background tasks
    periodic_tasks={
        "strategy_metrics": {
            "func": update_strategy_performance_metrics,
            "interval": 300  # Every 5 minutes
        }
    },
    
    # Circuit breaker config for external APIs
    enable_circuit_breakers=True,
    
    # Graceful shutdown timeout
    shutdown_timeout=45  # Allow time for order processing to complete
)

# Business logic routers
business_routers = [
    trade_endpoints.router,
    ledger_endpoints.router,
    redis_data_endpoints.router,
    management_endpoints.router,
    strategy_endpoints.router,
    historical_import_endpoints.router,
    external_order_endpoints.router,
    position_generation_endpoints.router
]

# Startup tasks (run once during startup)
startup_tasks = [
    setup_database_tables,
    setup_trade_service_dependencies,
    initialize_trade_components
]

# Shutdown tasks (run during graceful shutdown)
shutdown_tasks = [
    cleanup_trade_resources
]

# Create the FastAPI application with comprehensive infrastructure
app = start_service(
    service_name="trade_service",
    service_config=trade_service_config,
    business_routers=business_routers,
    startup_tasks=startup_tasks,
    shutdown_tasks=shutdown_tasks
)

# Add any service-specific endpoints that aren't in the business routers
@app.get("/trade-service/status")
async def trade_service_status():
    """Trade service specific status endpoint."""
    return {
        "service": "trade_service",
        "status": "operational",
        "features": [
            "order_management",
            "strategy_execution", 
            "portfolio_tracking",
            "risk_management"
        ],
        "version": trade_service_config.version
    }

# Optional: Add custom middleware if needed
@app.middleware("http")
async def trade_specific_middleware(request, call_next):
    """Example of service-specific middleware."""
    # Add any trade-service specific request processing
    response = await call_next(request)
    response.headers["X-Trade-Service"] = "v2.0.0"
    return response

# The app is now fully configured and ready to run!
# All infrastructure concerns are handled automatically:
# ✅ Database connections with health monitoring
# ✅ Redis caching with circuit breakers  
# ✅ Structured logging with request tracing
# ✅ Prometheus metrics collection
# ✅ Comprehensive health checks (/health, /health/detailed, /health/ready, /health/live)
# ✅ CORS and security middleware
# ✅ Rate limiting protection
# ✅ Graceful shutdown handling
# ✅ Background task management
# ✅ Error handling and recovery
# ✅ Service discovery registration

if __name__ == "__main__":
    # For development - use uvicorn directly
    import uvicorn
    uvicorn.run(
        "simplified_main:app", 
        host="0.0.0.0", 
        port=8004, 
        reload=True
    )