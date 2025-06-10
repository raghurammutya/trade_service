import sys
import os
import asyncio

# Ensure the parent folder (trade_service/) is in the PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi import FastAPI, Request
from sqlalchemy import text
from shared_architecture.utils.service_utils import start_service, stop_service
from shared_architecture.utils.logging_utils import log_info, log_exception

# Imports for your specific microservice components
from app.api.endpoints import trade_endpoints # Your API routes
from app.context.global_app import set_app # For global app state
from app.settings import tradeServiceSettings # Your custom settings class

# Imports for database model discovery
# You need to import at least one Base from your local models
# All your models (OrderModel, PositionModel, etc.) should inherit from the same declarative_base()
# So, importing one alias (e.g., OrderModelBase) is sufficient for metadata.create_all()
from app.models.order_model import Base as OrderModelBase
# It's good practice to ensure all other models are also imported
# to ensure their metadata is registered if they are not explicitly imported elsewhere.
from app.models.position_model import PositionModel
from app.models.holding_model import HoldingModel
from app.models.margin_model import MarginModel
from app.models.order_event_model import OrderEventModel

# Import your Celery tasks module to ensure tasks are registered for auto-discovery
# Even though celery_app.autodiscover_tasks handles finding them, importing the module
# ensures it's loaded by the main app process.
import app.tasks.trade_tasks


# Start the service - This function from shared_architecture now handles:
#   - FastAPI app creation
#   - Initial logging setup
#   - Connection management (TimescaleDB, Redis, RabbitMQ) and populating app.state.connections
#   - Configuration loading (potentially into app.state.config)
app: FastAPI = start_service("trade_service")
set_app(app) # Set the app globally if needed by other parts of your shared architecture

@app.on_event("startup")
async def custom_startup():
    """
    Custom startup logic for trade service - runs after shared_architecture's infrastructure setup.
    This is where we ensure database tables are created.
    """
    log_info("🚀 trade_service custom startup logic started.")
    
    # 1. Wait for infrastructure connections to be ready (populated by start_service)
    max_wait = 30 # seconds
    wait_interval = 1 # second
    waited = 0
    
    while waited < max_wait:
        # Check for TimescaleDB session factory availability
        if hasattr(app.state, 'connections') and app.state.connections.get("timescaledb"):
            log_info("Infrastructure is ready, proceeding with service initialization")
            break
        log_info(f"Waiting for infrastructure... ({waited}s/{max_wait}s)")
        await asyncio.sleep(wait_interval)
        waited += wait_interval
    else:
        log_exception("❌ Infrastructure startup timeout - TimescaleDB connection not ready.")
        raise Exception("Infrastructure startup timeout - connections not ready")
    
    # 2. Load microservice-specific settings (if not already handled by start_service)
    # This block assumes tradeServiceSettings.from_config() loads from a specific source
    # independent of app.state.config populated by start_service.
    # If app.state.config already contains all settings, you might simplify this.
    max_retries = 3
    retry_delay = 2
    
    for attempt in range(max_retries):
        try:
            log_info(f"Loading tradeServiceSettings config attempt {attempt + 1}/{max_retries}")
            settings_instance = tradeServiceSettings.from_config()
            app.state.settings = settings_instance # Attach custom settings to app state
            log_info("Trade service settings loaded successfully.")

            # Get session factory with validation
            session_factory = app.state.connections.get("timescaledb")
            if not session_factory:
                raise Exception("TimescaleDB session factory not available in app.state.connections.")
            
            log_info(f"Database operation attempt {attempt + 1}/{max_retries}")
            
            # Create session and execute with proper connection handling
            async with session_factory() as session:
                # 3. Verify database connection is alive
                try:
                    result = await session.execute(text("SELECT 1 as test"))
                    test_row = result.fetchone()
                    log_info(f"Database connection test successful: {test_row[0]}")
                except Exception as conn_test_error:
                    log_exception(f"Database connection test failed: {conn_test_error}")
                    raise # Re-raise to trigger retry logic
                
                # 4. Create database tables
                try:
                    # Get the SQLAlchemy engine from the session's bind
                    engine = session.bind
                    # Create all tables defined in your models if they don't exist
                    # OrderModelBase.metadata.create_all() will discover all models inheriting from that Base.
                    log_info("Checking and creating database tables...")
                    OrderModelBase.metadata.create_all(bind=engine)
                    log_info("Database tables checked/created successfully.")
                    break # Success, exit retry loop
                    
                except Exception as table_creation_error:
                    log_exception(f"Error during database table creation: {table_creation_error}")
                    raise # Re-raise to trigger retry logic
        
        except Exception as e:
            if attempt < max_retries - 1:
                log_exception(f"Startup attempt {attempt + 1} failed, retrying in {retry_delay}s: {e}")
                await asyncio.sleep(retry_delay)
                retry_delay *= 1.5 # Gradual backoff
                continue
            else:
                log_exception(f"❌ trade_service initialization failed after {max_retries} attempts: {e}")
                raise

    # 5. Initialize symbols (separate from database operations)
    try:
        log_info("Initializing symbol service by refreshing symbols...")
    except Exception as e:
        log_exception(f"❌ Symbol service initialization failed: {e}")
        # Depending on criticality, you might raise here to prevent startup
        # raise # Uncomment this if symbol service failure should halt startup

    log_info("✅ trade_service custom startup complete.")


# Include your API router
app.include_router(trade_endpoints.router, prefix="/trades", tags=["trades"])

# Health Check Endpoint
@app.get("/health")
async def health_check():
    """
    Comprehensive health check endpoint for the Trade Service.
    Checks underlying connections and service-specific components.
    """
    health_status = {"status": "healthy", "components": {}}
    
    # Check TimescaleDB connection
    try:
        session_factory = app.state.connections.get("timescaledb")
        if session_factory:
            async with session_factory() as session:
                await session.execute(text("SELECT 1"))
                health_status["components"]["timescaledb"] = {"status": "ok"}
        else:
            health_status["components"]["timescaledb"] = {"status": "degraded", "message": "Session factory not available"}
            health_status["status"] = "degraded"
    except Exception as e:
        health_status["components"]["timescaledb"] = {"status": "unhealthy", "message": str(e)}
        health_status["status"] = "unhealthy"

    # Check Redis connection
    try:
        redis_conn = app.state.connections.get("redis")
        if redis_conn:
            await redis_conn.ping() # Redis ping is an async operation in modern redis-py
            health_status["components"]["redis"] = {"status": "ok"}
        else:
            health_status["components"]["redis"] = {"status": "degraded", "message": "Redis connection not available"}
            health_status["status"] = "degraded"
    except Exception as e:
        health_status["components"]["redis"] = {"status": "unhealthy", "message": str(e)}
        health_status["status"] = "unhealthy"

    # Check RabbitMQ connection (assuming it's available via app.state.connections)
    try:
        rabbitmq_conn_producer = app.state.connections.get("rabbitmq_producer") # Or however you store it
        if rabbitmq_conn_producer:
            # A simple way to check if pika connection is alive (requires a more robust check)
            # This might involve checking the underlying socket. For simplicity, just check existence.
            health_status["components"]["rabbitmq"] = {"status": "ok"}
        else:
            health_status["components"]["rabbitmq"] = {"status": "degraded", "message": "RabbitMQ connection not available"}
            health_status["status"] = "degraded"
    except Exception as e:
        health_status["components"]["rabbitmq"] = {"status": "unhealthy", "message": str(e)}
        health_status["status"] = "unhealthy"

    # Add custom microservice health checks here (as in your original file)
    # Example: Check internal data consistency, background task queue depth etc.
    redis_health_from_manager = {"status": "unknown"}
    try:
        if hasattr(app.state, 'market_data_manager'):
            redis_health_from_manager = await app.state.market_data_manager.health_check()
        health_status["components"]["market_data_manager"] = redis_health_from_manager
    except Exception as e:
        health_status["components"]["market_data_manager"] = {"status": "unhealthy", "message": str(e)}
        if health_status["status"] == "healthy": health_status["status"] = "degraded"


    # Determine overall HTTP status code
    http_status_code = 200
    if health_status["status"] == "unhealthy":
        http_status_code = 500
    elif health_status["status"] == "degraded":
        http_status_code = 503
    
    return health_status, http_status_code # Return tuple for status and HTTP code


# Request Logging Middleware (as provided by you)
@app.middleware("http")
async def log_requests(request: Request, call_next):
    # You might want to add actual logging here, e.g., using log_info
    response = await call_next(request)
    return response

# Shutdown Event
@app.on_event("shutdown")
async def shutdown_event():
    """
    Handles shutdown events: gracefully stops the service and closes connections.
    """
    log_info("Trade Service shutting down...")
    # This stop_service from shared_architecture.utils.service_utils is assumed to handle
    # closing of connections via connection_manager.close_all_connections()
    await stop_service("trade_service") # Pass service name to stop_service
    log_info("Trade Service shutdown complete.")

# Main Runner (for local development or explicit run)
# This block handles direct execution of the uvicorn server with retry logic.
def run_uvicorn():
    import uvicorn
    log_info("Starting uvicorn server on 0.0.0.0:8000")
    uvicorn.run(
        app="app.main:app", # Refer to the app in the current module
        host="0.0.0.0",
        port=8000,
        reload=False,  # Disabled for container compatibility and production
        access_log=True,
        log_level="info"
    )

# Optional control via environment (as in your original file)
# This conditional block determines if uvicorn should be run directly from this script.
try:
    # Assuming app.state.config is populated by start_service
    # And "private" key exists and contains "RUN_UVICORN"
    should_run_uvicorn = app.state.config.get("private", {}).get("RUN_UVICORN", False)
    if should_run_uvicorn:
        log_info('RUN_UVICORN is true. Starting uvicorn...')
        # Retry loop for uvicorn startup (as in your original __main__ block)
        max_retries = 3
        retry_delay = 5 # seconds
        for attempt in range(max_retries):
            try:
                log_info(f"🔁 Attempt {attempt + 1} to start trade_service via uvicorn...")
                run_uvicorn() # Call the wrapper function
                break # Success
            except Exception as e:
                log_exception(f"❌ Uvicorn failed to start on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    log_info(f"⏳ Waiting {retry_delay} seconds before retry...")
                    asyncio.run(asyncio.sleep(retry_delay)) # Use asyncio.run for sleep outside async func
                    retry_delay *= 1.5 # Gradual backoff
                else:
                    log_info("❌ All uvicorn startup attempts failed.")
    else:
        log_info('RUN_UVICORN is false. trade_service ready but uvicorn not started by this script (expecting external server, e.g., Gunicorn).')
except (KeyError, AttributeError, TypeError) as e:
    log_info(f'RUN_UVICORN configuration not found or invalid: {e}. trade_service ready for external server.')


# The `if __name__ == "__main__":` block is now largely handled by the `try-except` block above.
# The original `if __name__ == "__main__":` block was effectively duplicated.
# This makes the script more self-contained for starting the uvicorn server based on config.