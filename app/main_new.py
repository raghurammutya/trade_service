import sys
import os
import asyncio
import time
from fastapi import HTTPException, Response
import json

# Ensure the parent folder (trade_service/) is in the PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi import FastAPI, Request
from sqlalchemy import text
from shared_architecture.utils.service_utils import start_service, stop_service
from shared_architecture.utils.logging_utils import log_info, log_exception

# Imports for your specific microservice components
from app.api.endpoints import trade_endpoints # Your API routes
from app.api.endpoints import ledger_endpoints
from app.api.endpoints import redis_data_endpoints # Redis data API
from app.api.endpoints import management_endpoints # Management and monitoring
from app.api.endpoints import strategy_endpoints # Strategy management
from app.api.endpoints import historical_import_endpoints # Historical trade import
from app.api.endpoints import external_order_endpoints # External order detection
from app.api.endpoints import position_generation_endpoints # Position/Holdings generation
# from app.api.endpoints import strategy_retagging_endpoints # Strategy retagging - temporarily disabled
from app.context.global_app import set_app # For global app state
from app.core.config import settings as tradeServiceSettings # Your custom settings class

# Import your Celery tasks module to ensure tasks are registered for auto-discovery
from app.tasks import create_order_event
from app.tasks import get_api_key_task
from app.tasks import process_order_task
from app.tasks import update_order_status
from app.tasks import update_positions_and_holdings_task

# Database models and table creation
from shared_architecture.db.models.holding_model import Base as HoldingBase
from shared_architecture.db.models.position_model import Base as PositionBase
from shared_architecture.db.models.order_model import Base as OrderBase
from shared_architecture.db.models.margin_model import Base as MarginBase
from shared_architecture.db.models.order_event_model import Base as OrderEventBase
from shared_architecture.db.models.strategy_model import Base as StrategyBase
from shared_architecture.db.session import sync_engine

# Create tables (you might want to move this to a migration script)
try:
    HoldingBase.metadata.create_all(bind=sync_engine)
    PositionBase.metadata.create_all(bind=sync_engine)
    OrderBase.metadata.create_all(bind=sync_engine)
    MarginBase.metadata.create_all(bind=sync_engine)
    OrderEventBase.metadata.create_all(bind=sync_engine)
    StrategyBase.metadata.create_all(bind=sync_engine)
    log_info("✅ Database tables created/verified")
except Exception as e:
    log_exception(f"❌ Failed to create database tables: {e}")

# Start the service with new service discovery system
app: FastAPI = start_service("trade_service")
set_app(app) # Set the app globally if needed by other parts of your shared architecture

# Include your API routers
app.include_router(trade_endpoints.router, prefix="/trades", tags=["trades"])
app.include_router(ledger_endpoints.router, prefix="/ledger", tags=["ledger"])
app.include_router(redis_data_endpoints.router, prefix="/data", tags=["redis_data"])
app.include_router(management_endpoints.router, prefix="/management", tags=["management"])
app.include_router(strategy_endpoints.router, prefix="/strategies", tags=["strategy_management"])
app.include_router(historical_import_endpoints.router, prefix="/historical", tags=["historical_import"])
app.include_router(external_order_endpoints.router, tags=["external_orders"])
app.include_router(position_generation_endpoints.router, prefix="/generate", tags=["position_generation"])
# app.include_router(strategy_retagging_endpoints.router, prefix="/strategies", tags=["strategy_retagging"]) # temporarily disabled


@app.on_event("startup")
async def custom_startup():
    """
    Custom startup logic for trade service - runs after shared_architecture's infrastructure setup.
    Updated to work with new service discovery system.
    """
    log_info("🚀 trade_service custom startup logic started.")
    
    # 1. Wait for infrastructure connections to be ready (populated by start_service)
    max_wait = 30 # seconds
    wait_interval = 1 # second
    waited = 0
    
    while waited < max_wait:
        # Check for connection manager initialization
        if (hasattr(app.state, 'connection_manager') and 
            hasattr(app.state, 'connections') and 
            app.state.connections.get("timescaledb")):
            log_info("✅ Infrastructure is ready, proceeding with service initialization")
            break
        log_info(f"⏳ Waiting for infrastructure... ({waited}s/{max_wait}s)")
        await asyncio.sleep(wait_interval)
        waited += wait_interval
    else:
        log_exception("❌ Infrastructure startup timeout - connections not ready.")
        raise Exception("Infrastructure startup timeout - connections not ready")
    
    # 2. Load microservice-specific settings
    max_retries = 3
    retry_delay = 2
    
    for attempt in range(max_retries):
        try:
            log_info(f"📝 Loading trade service settings attempt {attempt + 1}/{max_retries}")
            
            # Use the settings instance directly (simplified approach)
            app.state.settings = tradeServiceSettings
            log_info("✅ Trade service settings loaded successfully.")

            # Get session factory with validation
            session_factory = app.state.connections.get("timescaledb")
            if not session_factory:
                raise Exception("TimescaleDB session factory not available in app.state.connections.")
            
            log_info(f"🔍 Database verification attempt {attempt + 1}/{max_retries}")
            
            # Test database connection
            async with session_factory() as session:
                try:
                    result = await session.execute(text("SELECT 1 as test"))
                    test_row = result.fetchone()
                    log_info(f"✅ Database connection test successful: {test_row[0]}")
                except Exception as conn_test_error:
                    log_exception(f"❌ Database connection test failed: {conn_test_error}")
                    raise # Re-raise to trigger retry logic
                
                # Database is working, continue with service-specific initialization
                log_info("📊 Performing service-specific database checks...")
                
                # Example: Check if required tables exist
                try:
                    tables_check = await session.execute(text("""
                        SELECT table_name 
                        FROM information_schema.tables 
                        WHERE table_schema = 'public' 
                        AND table_name IN ('orders', 'positions', 'holdings', 'margins')
                    """))
                    existing_tables = [row[0] for row in tables_check.fetchall()]
                    log_info(f"📋 Found existing tables: {existing_tables}")
                except Exception as table_check_error:
                    log_exception(f"⚠️  Table check failed: {table_check_error}")
                
                break # Success, exit retry loop
                    
        except Exception as e:
            if attempt < max_retries - 1:
                log_exception(f"❌ Startup attempt {attempt + 1} failed, retrying in {retry_delay}s: {e}")
                await asyncio.sleep(retry_delay)
                retry_delay *= 1.5 # Gradual backoff
                continue
            else:
                log_exception(f"❌ trade_service initialization failed after {max_retries} attempts: {e}")
                raise

    # 3. Service health check and logging
    try:
        health_status = await app.state.connection_manager.health_check()
        healthy_services = [k for k, v in health_status.items() if v["status"] == "healthy"]
        degraded_services = [k for k, v in health_status.items() if v["status"] == "unavailable"]
        
        log_info(f"🟢 Healthy services: {healthy_services}")
        if degraded_services:
            log_info(f"🟡 Unavailable services (graceful degradation): {degraded_services}")
            
    except Exception as e:
        log_exception(f"❌ Health check failed: {e}")

    # 4. Initialize service-specific components
    try:
        log_info("🔧 Initializing trade service components...")
        
        # Initialize any service-specific managers, caches, etc.
        # Example: symbol service, rate limiters, etc.
        
        log_info("✅ Trade service components initialized")
    except Exception as e:
        log_exception(f"❌ Component initialization failed: {e}")
        # Depending on criticality, you might raise here to prevent startup

    log_info("✅ trade_service custom startup complete.")


@app.get("/health")
async def health_check():
    """
    Comprehensive health check endpoint using the new connection manager.
    """
    try:
        # Get health status from connection manager
        connection_health = await app.state.connection_manager.health_check()
        
        # Determine overall status
        overall_status = "healthy"
        for service, status in connection_health.items():
            if status["status"] == "unhealthy":
                overall_status = "unhealthy"
                break
            elif status["status"] == "unavailable" and overall_status != "unhealthy":
                overall_status = "degraded"
        
        # Add service-specific health checks
        health_status = {
            "overall_status": overall_status,
            "service": "trade_service",
            "connections": connection_health,
            "custom_checks": {}
        }
        
        # Add custom microservice health checks
        try:
            if hasattr(app.state, 'market_data_manager'):
                health_status["custom_checks"]["market_data_manager"] = await app.state.market_data_manager.health_check()
        except Exception as e:
            health_status["custom_checks"]["market_data_manager"] = {"status": "unhealthy", "message": str(e)}
            if overall_status == "healthy":
                overall_status = "degraded"

        # Update overall status based on custom checks
        health_status["overall_status"] = overall_status

        # Return appropriate HTTP status code
        if overall_status == "unhealthy":
            raise HTTPException(status_code=500, detail=health_status)
        elif overall_status == "degraded":
            return Response(
                content=json.dumps(health_status),
                status_code=503,
                media_type="application/json"
            )

        return health_status
        
    except HTTPException:
        raise  # Re-raise HTTP exceptions
    except Exception as e:
        log_exception(f"❌ Health check failed: {e}")
        error_response = {
            "overall_status": "error",
            "service": "trade_service", 
            "message": str(e)
        }
        raise HTTPException(status_code=500, detail=error_response)


@app.get("/health/detailed")
async def detailed_health_check():
    """
    Detailed health check with more information about service discovery
    """
    try:
        from shared_architecture.connections.service_discovery import service_discovery,ServiceType
        
        connection_health = await app.state.connection_manager.health_check()
        
        detailed_health = {
            "service": "trade_service",
            "environment": service_discovery.environment.value,
            "connections": connection_health,
            "service_discovery": {
                "redis": service_discovery.get_connection_info("redis", ServiceType.REDIS),
                "timescaledb": service_discovery.get_connection_info("timescaledb", ServiceType.TIMESCALEDB),
                "rabbitmq": service_discovery.get_connection_info("rabbitmq", ServiceType.RABBITMQ),
                "mongodb": service_discovery.get_connection_info("mongo", ServiceType.MONGODB),
            }
        }
        
        return detailed_health
        
    except Exception as e:
        log_exception(f"❌ Detailed health check failed: {e}")
        raise HTTPException(status_code=500, detail={"error": str(e)})


# Request Logging Middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    
    # Log request details (you can customize this)
    log_info(f"📥 {request.method} {request.url.path} - {response.status_code} - {process_time:.3f}s")
    
    return response


# Shutdown Event
@app.on_event("shutdown")
async def shutdown_event():
    """
    Handles shutdown events: gracefully stops the service and closes connections.
    """
    log_info("🛑 Trade Service shutting down...")
    try:
        await stop_service("trade_service")
        log_info("✅ Trade Service shutdown complete.")
    except Exception as e:
        log_exception(f"❌ Error during shutdown: {e}")


# Main Runner (for local development or explicit run)
def run_uvicorn():
    import uvicorn
    log_info("🚀 Starting uvicorn server on 0.0.0.0:8004")
    uvicorn.run(
        app="app.main:app",
        host="0.0.0.0",
        port=8004,
        reload=False,  # Disabled for container compatibility and production
        access_log=True,
        log_level="info"
    )


# MINIMAL FIX: Only run uvicorn startup logic when NOT being imported by uvicorn
if __name__ == "__main__":
    try:
        # Check if we should start uvicorn based on config
        should_run_uvicorn = app.state.config.get("private", {}).get("RUN_UVICORN", False)
        if should_run_uvicorn:
            log_info('🎯 RUN_UVICORN is true. Starting uvicorn...')
            # Retry loop for uvicorn startup
            max_retries = 3
            retry_delay = 5
            for attempt in range(max_retries):
                try:
                    log_info(f"🔁 Attempt {attempt + 1} to start trade_service via uvicorn...")
                    run_uvicorn()
                    break
                except Exception as e:
                    log_exception(f"❌ Uvicorn failed to start on attempt {attempt + 1}: {e}")
                    if attempt < max_retries - 1:
                        log_info(f"⏳ Waiting {retry_delay} seconds before retry...")
                        time.sleep(retry_delay)
                        retry_delay *= 1.5
                    else:
                        log_info("❌ All uvicorn startup attempts failed.")
        else:
            log_info('🎯 RUN_UVICORN is false or not set. Starting uvicorn directly...')
            import uvicorn
            uvicorn.run(
                "app.main:app",
                host="0.0.0.0", 
                port=8004,
                reload=True,
                log_level="info"
            )
    except (KeyError, AttributeError, TypeError) as e:
        log_info(f'⚙️  Config not available, starting uvicorn with defaults: {e}')
        import uvicorn
        uvicorn.run(
            "app.main:app",
            host="0.0.0.0", 
            port=8004,
            reload=True,
            log_level="info"
        )
else:
    # When imported by uvicorn (production), just log that we're ready
    log_info('✅ Trade service app created and ready for uvicorn startup.')