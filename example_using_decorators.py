# trade_service/example_using_decorators.py
"""
Example showing how to use the comprehensive service utilities and decorators
in a real microservice implementation.
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, List, Optional
import asyncio

# Import the comprehensive service utilities
from shared_architecture.utils.comprehensive_service_utils import (
    start_service,
    ServiceConfig,
    ServiceType
)

# Import the decorators
from shared_architecture.utils.service_decorators import (
    with_circuit_breaker,
    with_retry,
    with_metrics,
    with_timeout,
    api_endpoint,
    background_task
)

# Import existing schemas and models
from shared_architecture.schemas.order_schema import OrderCreate, OrderResponse
from shared_architecture.schemas.position_schema import PositionResponse

# Create business logic router
enhanced_trade_router = APIRouter()

# Example: Order processing with comprehensive protection
@enhanced_trade_router.post("/orders", response_model=OrderResponse)
@api_endpoint(
    rate_limit="500/minute",  # High throughput for trading
    timeout=30.0,
    circuit_breaker_name="order_processing",
    metrics_name="create_order"
)
async def create_order(order_data: OrderCreate):
    """
    Create a new order with comprehensive protection:
    - Rate limiting
    - Timeout protection
    - Circuit breaker for external broker API
    - Automatic metrics collection
    """
    # This endpoint is now automatically protected with:
    # ✅ Rate limiting (500 requests per minute)
    # ✅ Timeout (30 seconds max)
    # ✅ Circuit breaker protection
    # ✅ Metrics collection
    # ✅ Request/response logging
    
    return await process_order_with_broker(order_data)

@with_circuit_breaker(
    "broker_api",
    fallback=lambda order: {"status": "pending", "message": "Broker temporarily unavailable"}
)
@with_retry(max_attempts=3, delay=1.0, exceptions=(ConnectionError, TimeoutError))
@with_metrics("broker_api_call")
async def process_order_with_broker(order_data: OrderCreate):
    """
    Process order with external broker API.
    Protected by circuit breaker with fallback, retry logic, and metrics.
    """
    # Simulate broker API call
    await asyncio.sleep(0.1)  # Simulate network delay
    
    # This would make actual broker API call
    return {
        "order_id": "12345",
        "status": "submitted",
        "symbol": order_data.symbol,
        "quantity": order_data.quantity
    }

# Example: Position retrieval with caching
@enhanced_trade_router.get("/positions/{user_id}", response_model=List[PositionResponse])
@api_endpoint(
    rate_limit="1000/minute",
    cache_ttl=60,  # Cache for 1 minute
    metrics_name="get_positions"
)
async def get_user_positions(user_id: str):
    """
    Get user positions with caching and protection.
    """
    return await fetch_positions_from_database(user_id)

@with_circuit_breaker("database")
@with_timeout(10.0)
@with_metrics("database_query")
async def fetch_positions_from_database(user_id: str):
    """
    Fetch positions from database with protection.
    """
    # This would query the actual database
    await asyncio.sleep(0.05)  # Simulate DB query
    return [
        {
            "symbol": "AAPL",
            "quantity": 100,
            "average_price": 150.25,
            "current_value": 15025.00
        }
    ]

# Example: Background task for strategy execution
@background_task(
    retry_attempts=5,
    circuit_breaker_name="strategy_engine",
    metrics_name="strategy_execution"
)
async def execute_trading_strategy(strategy_id: str, app):
    """
    Background task for executing trading strategies.
    Protected with retries, circuit breaker, and metrics.
    """
    # This would contain actual strategy execution logic
    await asyncio.sleep(2.0)  # Simulate strategy processing
    
    # The task is automatically protected with:
    # ✅ Retry logic (5 attempts with exponential backoff)
    # ✅ Circuit breaker for strategy engine
    # ✅ Metrics collection
    # ✅ Error handling and logging
    
    return {"strategy_id": strategy_id, "status": "executed", "orders_placed": 3}

# Example: Real-time market data processing
@background_task(
    retry_attempts=10,  # High retry for critical data
    circuit_breaker_name="market_data_feed",
    metrics_name="market_data_processing"
)
async def process_market_data_feed(app):
    """
    Background task for processing real-time market data.
    """
    while True:
        try:
            # Process market data
            await asyncio.sleep(0.1)  # Simulate high-frequency processing
            
            # This would contain actual market data processing
            # The task automatically handles:
            # ✅ Connection failures with retries
            # ✅ Circuit breaker for market data provider
            # ✅ Performance metrics
            # ✅ Error recovery
            
        except Exception as e:
            # Let the decorator handle retries and circuit breaking
            raise

# Example: Data validation endpoint
from pydantic import BaseModel

class TradeAnalysisRequest(BaseModel):
    symbol: str
    start_date: str
    end_date: str
    strategy_type: str

@enhanced_trade_router.post("/analysis")
@api_endpoint(
    rate_limit="100/minute",  # Lower rate for heavy analysis
    timeout=60.0,  # Longer timeout for analysis
    circuit_breaker_name="analysis_engine",
    metrics_name="trade_analysis"
)
async def analyze_trades(request: TradeAnalysisRequest):
    """
    Analyze trading performance with comprehensive protection.
    """
    return await run_trade_analysis(request)

@with_circuit_breaker("analytics_service")
@with_timeout(45.0)
@with_metrics("analytics_computation")
async def run_trade_analysis(request: TradeAnalysisRequest):
    """
    Run complex trade analysis with protection.
    """
    # Simulate complex analysis
    await asyncio.sleep(5.0)
    
    return {
        "symbol": request.symbol,
        "total_trades": 150,
        "win_rate": 0.65,
        "profit_loss": 12500.75,
        "sharpe_ratio": 1.45
    }

# Custom startup task for trade service
async def initialize_trading_strategies(app):
    """Custom startup task to initialize trading strategies."""
    from shared_architecture.utils.logging_utils import log_info
    
    # Load active strategies
    strategies = await load_active_strategies()
    app.state.active_strategies = strategies
    
    log_info(f"✅ Initialized {len(strategies)} trading strategies")

@with_circuit_breaker("database")
async def load_active_strategies():
    """Load active strategies from database."""
    # Simulate database query
    await asyncio.sleep(0.2)
    return ["momentum_strategy", "mean_reversion", "pairs_trading"]

# Custom shutdown task
async def save_strategy_state(app):
    """Save strategy state during shutdown."""
    from shared_architecture.utils.logging_utils import log_info
    
    if hasattr(app.state, 'active_strategies'):
        # Save strategy state
        await save_strategies_to_database(app.state.active_strategies)
        log_info("✅ Strategy state saved")

@with_circuit_breaker("database")
async def save_strategies_to_database(strategies):
    """Save strategies to database."""
    await asyncio.sleep(0.1)
    # This would save actual strategy state

# Configuration for enhanced trade service
enhanced_config = ServiceConfig(
    service_name="enhanced_trade_service",
    service_type=ServiceType.TRADE,
    title="Enhanced Trade Service",
    description="High-performance trading service with comprehensive protection",
    version="2.1.0",
    
    # Infrastructure
    required_services=["timescaledb", "redis"],
    optional_services=["rabbitmq", "mongodb"],
    
    # Performance settings
    port=8004,
    enable_compression=True,
    enable_rate_limiting=True,
    rate_limit_default="1000/minute",
    
    # Observability
    enable_request_logging=True,
    enable_metrics=True,
    enable_health_checks=True,
    
    # Background tasks
    periodic_tasks={
        "strategy_execution": {
            "func": lambda app: execute_trading_strategy("momentum_1", app),
            "interval": 60  # Execute every minute
        },
        "market_data_processing": {
            "func": process_market_data_feed,
            "interval": 1  # Process every second
        }
    },
    
    # Circuit breakers
    enable_circuit_breakers=True,
    
    # Graceful shutdown
    shutdown_timeout=60  # Allow time for strategy completion
)

# Create the enhanced service
if __name__ == "__main__":
    app = start_service(
        service_name="enhanced_trade_service",
        service_config=enhanced_config,
        business_routers=[enhanced_trade_router],
        startup_tasks=[initialize_trading_strategies],
        shutdown_tasks=[save_strategy_state]
    )
    
    # The service now has:
    # 🚀 Comprehensive infrastructure setup
    # 🛡️ Circuit breaker protection for all external calls
    # ⚡ Automatic retry logic with exponential backoff
    # 📊 Comprehensive metrics collection
    # 🔄 Rate limiting protection
    # ⏱️ Timeout protection
    # 💾 Automatic caching for expensive operations
    # 🔍 Detailed health checks and monitoring
    # 📝 Structured logging with request tracing
    # 🏃 Background task management
    # 🛑 Graceful shutdown handling
    # 🔧 Service discovery integration
    
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8004)