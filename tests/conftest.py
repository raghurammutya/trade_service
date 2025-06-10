import pytest
import asyncio
import asyncpg
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import redis
import aio_pika
from unittest.mock import Mock, AsyncMock, patch
import os
import sys

# =============================================================================
# CORRECT IMPORTS BASED ON YOUR ACTUAL STRUCTURE
# =============================================================================

# FastAPI app import - YOUR ACTUAL STRUCTURE
from app.main import app

# Settings import - YOUR ACTUAL STRUCTURE  
from app.settings import tradeServiceSettings as settings

# Service imports - YOUR ACTUAL STRUCTURE
from app.services.trade_service import TradeService

# Model imports - YOUR ACTUAL STRUCTURE (from shared_architecture)
from shared_architecture.db.models.order_model import OrderModel
from shared_architecture.db.models.position_model import PositionModel
from shared_architecture.db.models.holding_model import HoldingModel
from shared_architecture.db.models.margin_model import MarginModel
from shared_architecture.db.models.order_event_model import OrderEventModel

# Schema imports - YOUR ACTUAL SCHEMAS (currently in app/schemas)
from app.schemas.order_schema import (
    OrderSchema, OrderCreateSchema, OrderResponseSchema, OrderListResponseSchema
)
from app.schemas.position_schema import (
    PositionSchema, PositionResponseSchema, PositionListResponseSchema
)
from app.schemas.holding_schema import (
    HoldingSchema, HoldingResponseSchema, HoldingListResponseSchema
)
from app.schemas.margin_schema import (
    MarginSchema, MarginResponseSchema
)
from app.schemas.order_event_schema import OrderEventSchema

# Shared architecture imports
from shared_architecture.connections.connection_manager import connection_manager
from shared_architecture.utils.logging_utils import log_info, log_exception

# Enums import
try:
    from shared_architecture.enums import OrderEvent
except ImportError:
    # Fallback if not available
    class OrderEvent:
        ORDER_PLACED = "ORDER_PLACED"
        ORDER_ACCEPTED = "ORDER_ACCEPTED"
        ORDER_REJECTED = "ORDER_REJECTED"
        ORDER_CANCELLED = "ORDER_CANCELLED"
        ORDER_MODIFIED = "ORDER_MODIFIED"
        ORDER_FILLED = "ORDER_FILLED"
        ORDER_PARTIALLY_FILLED = "ORDER_PARTIALLY_FILLED"

# AutoTrader import - YOUR ACTUAL STRUCTURE
try:
    from com.dakshata.autotrader.api.AutoTrader import AutoTrader
except ImportError:
    print("⚠️ AutoTrader not available, using mock")
    class AutoTraderResponse:
        def __init__(self, success=False, result=None, message=""):
            self.success = success
            self.result = result if result is not None else []
            self.message = message

    class AutoTrader:
        @staticmethod
        def create_instance(api_key, server_url):
            return AutoTraderMock()

    class AutoTraderMock:
        def read_platform_margins(self, **kwargs):
            return AutoTraderResponse(success=False, result=[], message="Mock: AutoTrader not available")
        
        def read_platform_positions(self, **kwargs):
            return AutoTraderResponse(success=False, result=[], message="Mock: AutoTrader not available")
        
        def read_platform_holdings(self, **kwargs):
            return AutoTraderResponse(success=False, result=[], message="Mock: AutoTrader not available")
        
        def read_platform_orders(self, **kwargs):
            return AutoTraderResponse(success=False, result=[], message="Mock: AutoTrader not available")

# =============================================================================
# TEST CONFIGURATION
# =============================================================================

# Test database URL
TEST_DATABASE_URL = "postgresql://tradmin:tradpass@timescaledb:5432/tradingdb_test"

@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
def client():
    """FastAPI test client using your actual app."""
    return TestClient(app)

@pytest.fixture
async def db_connection():
    """Test database connection."""
    try:
        conn = await asyncpg.connect(TEST_DATABASE_URL)
        
        # Clean up tables before test - YOUR ACTUAL TABLE STRUCTURE
        tables_to_clean = [
            'tradingdb.orders',
            'tradingdb.positions', 
            'tradingdb.holdings',
            'tradingdb.margins',
            'tradingdb.order_events'
        ]
        
        for table in tables_to_clean:
            try:
                await conn.execute(f"TRUNCATE TABLE {table} CASCADE")
            except Exception:
                pass
        
        yield conn
        
        # Clean up after test
        for table in tables_to_clean:
            try:
                await conn.execute(f"TRUNCATE TABLE {table} CASCADE")
            except Exception:
                pass
        
        await conn.close()
    except Exception as e:
        pytest.skip(f"Database connection failed: {e}")

@pytest.fixture
def redis_client():
    """Test Redis client."""
    try:
        client = redis.Redis(host='redis', port=6379, db=1)
        client.ping()
        client.flushdb()
        yield client
        client.flushdb()
        client.close()
    except Exception as e:
        pytest.skip(f"Redis connection failed: {e}")

@pytest.fixture
def trade_service():
    """Create TradeService instance for testing."""
    return TradeService()

@pytest.fixture
def mock_autotrader():
    """Mock AutoTrader for safe testing."""
    mock_autotrader = Mock()
    
    # Mock margins response - LIST OF SEGMENTS (as you mentioned)
    mock_autotrader.read_platform_margins.return_value = AutoTraderResponse(
        success=True,
        result=[
            {
                "category": "equity",
                "adhoc": 0.0,
                "available": 50000.0,
                "collateral": 10000.0,
                "exposure": 25000.0,
                "funds": 60000.0,
                "net": 45000.0,
                "span": 15000.0,
                "total": 60000.0,
                "utilized": 15000.0,
                "pseudo_account": "test_account",
                "trading_account": "test_trading_account"
            },
            {
                "category": "commodity",
                "adhoc": 0.0,
                "available": 20000.0,
                "collateral": 5000.0,
                "exposure": 10000.0,
                "funds": 25000.0,
                "net": 20000.0,
                "span": 5000.0,
                "total": 25000.0,
                "utilized": 5000.0,
                "pseudo_account": "test_account",
                "trading_account": "test_trading_account"
            }
        ],
        message="Success"
    )
    
    # Mock positions response
    mock_autotrader.read_platform_positions.return_value = AutoTraderResponse(
        success=True,
        result=[
            {
                "symbol": "WIPRO",
                "exchange": "NSE",
                "net_quantity": 10,
                "buy_avg_price": 330.0,
                "sell_avg_price": 0.0,
                "ltp": 335.0,
                "pnl": 50.0,
                "unrealised_pnl": 50.0,
                "realised_pnl": 0.0,
                "platform": "StocksDeveloper",
                "pseudo_account": "test_account"
            }
        ],
        message="Success"
    )
    
    # Mock holdings response
    mock_autotrader.read_platform_holdings.return_value = AutoTraderResponse(
        success=True,
        result=[
            {
                "symbol": "INFY",
                "exchange": "NSE",
                "quantity": 50,
                "avg_price": 1500.0,
                "ltp": 1520.0,
                "pnl": 1000.0,
                "platform": "StocksDeveloper",
                "pseudo_account": "test_account"
            }
        ],
        message="Success"
    )
    
    # Mock orders response
    mock_autotrader.read_platform_orders.return_value = AutoTraderResponse(
        success=True,
        result=[
            {
                "exchange_order_id": "mock_order_1",
                "symbol": "WIPRO",
                "exchange": "NSE",
                "filled_quantity": 10,
                "pending_quantity": 0,
                "price": 330.0,
                "average_price": 330.5,
                "status": "COMPLETE",
                "order_type": "LIMIT",
                "trade_type": "BUY",
                "platform": "StocksDeveloper"
            }
        ],
        message="Success"
    )
    
    # Mock WRITE operations (SAFE - no real orders)
    mock_autotrader.place_regular_order.return_value = AutoTraderResponse(
        success=True,
        result={"exchange_order_id": "mock_123456"},
        message="Order placed successfully (MOCK)"
    )
    
    return mock_autotrader

@pytest.fixture
def sample_order_create_data():
    """Sample order creation data using your OrderCreateSchema structure."""
    return {
        "user_id": "test_user_123",
        "organization_id": "test_org_456",
        "strategy_id": "strategy_alpha_001",
        "exchange": "NSE",
        "symbol": "WIPRO",
        "transaction_type": "BUY",
        "order_type": "LIMIT",
        "product_type": "INTRADAY",
        "quantity": 10,
        "price": 330.35,
        "trigger_price": 0.0,
        "validity": "DAY"
    }

@pytest.fixture
def sample_margin_data():
    """Sample margin data using your MarginSchema structure."""
    return {
        "user_id": 1,
        "adhoc": 0.0,
        "available": 50000.0,
        "category": "equity",
        "collateral": 10000.0,
        "exposure": 25000.0,
        "funds": 60000.0,
        "net": 45000.0,
        "pseudo_account": "test_account",
        "span": 15000.0,
        "total": 60000.0,
        "utilized": 15000.0,
        "trading_account": "test_trading_account"
    }

@pytest.fixture
def sample_position_data():
    """Sample position data using your PositionSchema structure."""
    return {
        "symbol": "WIPRO",
        "exchange": "NSE",
        "net_quantity": 10,
        "buy_avg_price": 330.0,
        "ltp": 335.0,
        "pnl": 50.0,
        "unrealised_pnl": 50.0,
        "platform": "StocksDeveloper",
        "pseudo_account": "test_account",
        "strategy_id": "strategy_alpha_001"
    }

@pytest.fixture
def sample_holding_data():
    """Sample holding data using your HoldingSchema structure."""
    return {
        "symbol": "INFY",
        "exchange": "NSE",
        "quantity": 50,
        "avg_price": 1500.0,
        "ltp": 1520.0,
        "pnl": 1000.0,
        "platform": "StocksDeveloper",
        "pseudo_account": "test_account",
        "strategy_id": "strategy_alpha_001"
    }

@pytest.fixture
async def celery_app():
    """Celery app for testing async tasks."""
    try:
        from app.core.celery_config import celery_app
        celery_app.conf.update(task_always_eager=True)
        return celery_app
    except ImportError:
        pytest.skip("Celery not configured")

# Print test setup info
print("🔧 Test Setup Complete:")
print(f"   📱 FastAPI App: {type(app).__name__}")
print(f"   ⚙️  Trade Service: {TradeService.__name__}")
print(f"   📊 Models: OrderModel, PositionModel, HoldingModel, MarginModel")
print(f"   📋 Schemas: OrderSchema, PositionSchema, HoldingSchema, MarginSchema")
print(f"   🔗 Connection Manager: {connection_manager.__class__.__name__}")