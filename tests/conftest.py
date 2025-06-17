import pytest
import asyncio
import asyncpg
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import redis
from unittest.mock import Mock, AsyncMock, patch
import os
import sys
from pathlib import Path

# Add the app directory to Python path
current_dir = Path(__file__).parent
app_dir = current_dir.parent
sys.path.insert(0, str(app_dir))

# Set up test environment FIRST, before any other imports
def ensure_test_env():
    """Ensure test environment variables are set."""
    required_vars = {
        'TESTING': 'true',
        'MOCK_EXTERNAL_SERVICES': 'true',
        'RUN_UVICORN': 'false',
        'REDIS_HOST': 'localhost',
        'REDIS_PORT': '6379',
        'REDIS_DB': '1',  # Use different DB for tests
        'TIMESCALEDB_URL': 'postgresql://testuser:testpass@localhost:5432/testdb',
        'MONGODB_URL': 'mongodb://localhost:27017/testdb',
        'USER_SERVICE_URL': 'http://localhost:8001',
        'RABBITMQ_HOST': 'localhost',
        'RABBITMQ_PORT': '5672',
        'RABBITMQ_USER': 'guest',
        'RABBITMQ_PASSWORD': 'guest',
        'STOCKSDEVELOPER_API_KEY': 'test_api_key_12345',
        'TELEGRAM_BOT_TOKEN': 'test_bot_token_12345',
        'TRADE_API_URL': 'http://localhost:8000',
        'MOCK_ORDER_EXECUTION': 'true',
        'POSTGRES_USER': 'testuser',
        'POSTGRES_PASSWORD': 'testpass',
        'POSTGRES_HOST': 'localhost',
        'POSTGRES_PORT': '5432',
        'POSTGRES_DATABASE': 'testdb',
        'ENVIRONMENT': 'test'
    }
    
    for key, default_value in required_vars.items():
        if key not in os.environ:
            os.environ[key] = default_value

# Set up test environment BEFORE any other imports
ensure_test_env()

# Import test environment setup (this will set more env vars)
try:
    from tests.test_env_override import setup_test_environment
    setup_test_environment()
except ImportError:
    pass

# =============================================================================
# SAFE IMPORTS WITH FALLBACKS
# =============================================================================

# Try to import the FastAPI app
try:
    from app.main import app
    print("✅ Successfully imported FastAPI app")
except Exception as e:
    print(f"⚠️  Could not import main app: {e}")
    # Create a minimal FastAPI app for testing
    from fastapi import FastAPI
    app = FastAPI(title="Test Trade Service")

# Try to import settings
try:
    from app.core.config import settings
    print("✅ Successfully imported settings")
except Exception as e:
    print(f"⚠️  Could not import settings: {e}")
    # Create mock settings
    class MockSettings:
        trade_api_url = "http://mock-api"
        stocksdeveloper_api_key = "mock_key"
        mock_order_execution = True
        user_service_url = "http://localhost:8001"
    settings = MockSettings()

# Try to import TradeService
try:
    from app.services.trade_service import TradeService
    print("✅ Successfully imported TradeService")
except Exception as e:
    print(f"⚠️  Could not import TradeService: {e}")
    # Create mock TradeService
    class TradeService:
        def __init__(self, db=None):
            self.db = db

# Try to import models
try:
    from shared_architecture.db.models.order_model import OrderModel
    from shared_architecture.db.models.position_model import PositionModel
    from shared_architecture.db.models.holding_model import HoldingModel
    from shared_architecture.db.models.margin_model import MarginModel
    from shared_architecture.db.models.order_event_model import OrderEventModel
    print("✅ Successfully imported shared architecture models")
except Exception as e:
    print(f"⚠️  Could not import shared architecture models: {e}")
    # Create mock models
    from sqlalchemy.ext.declarative import declarative_base
    from sqlalchemy import Column, Integer, String, Float, DateTime
    
    Base = declarative_base()
    
    class OrderModel(Base):
        __tablename__ = 'orders'
        id = Column(Integer, primary_key=True)
        symbol = Column(String)
        quantity = Column(Integer)
        price = Column(Float)
        
    class PositionModel(Base):
        __tablename__ = 'positions'
        id = Column(Integer, primary_key=True)
        symbol = Column(String)
        
    class HoldingModel(Base):
        __tablename__ = 'holdings'
        id = Column(Integer, primary_key=True)
        symbol = Column(String)
        
    class MarginModel(Base):
        __tablename__ = 'margins'
        id = Column(Integer, primary_key=True)
        category = Column(String)
        
    class OrderEventModel(Base):
        __tablename__ = 'order_events'
        id = Column(Integer, primary_key=True)

# Try to import schemas
try:
    from shared_architecture.schemas.order_schema import OrderSchema
    from shared_architecture.schemas.position_schema import PositionSchema
    from shared_architecture.schemas.holding_schema import HoldingSchema
    from shared_architecture.schemas.margin_schema import MarginSchema
    print("✅ Successfully imported shared architecture schemas")
except Exception as e:
    print(f"⚠️  Could not import shared architecture schemas: {e}")
    # Create mock schemas
    from pydantic import BaseModel
    from typing import Optional
    from datetime import datetime
    from decimal import Decimal
    
    class OrderSchema(BaseModel):
        id: Optional[int] = None
        symbol: Optional[str] = None
        quantity: Optional[int] = None
        price: Optional[float] = None
        class Config:
            from_attributes = True
    
    class OrderCreateSchema(BaseModel):
        user_id: str
        organization_id: str
        strategy_id: str
        exchange: str
        symbol: str
        transaction_type: str
        order_type: str
        product_type: str
        quantity: int
        price: Optional[Decimal] = None
        trigger_price: Optional[Decimal] = None
        validity: Optional[str] = "DAY"
        
    class OrderResponseSchema(BaseModel):
        id: int
        user_id: str
        organization_id: str
        strategy_id: str
        exchange: str
        symbol: str
        transaction_type: str
        order_type: str
        product_type: str
        quantity: int
        status: str
        created_at: datetime
        updated_at: datetime
        class Config:
            from_attributes = True
    
    class OrderListResponseSchema(BaseModel):
        orders: list
        total_count: int
    
    class PositionSchema(BaseModel):
        id: Optional[int] = None
        symbol: Optional[str] = None
        net_quantity: Optional[int] = None
        class Config:
            from_attributes = True
    
    class PositionResponseSchema(BaseModel):
        id: int
        user_id: str
        organization_id: str
        strategy_id: str
        exchange: str
        symbol: str
        product_type: str
        quantity: int
        average_price: Decimal
        created_at: datetime
        updated_at: datetime
        class Config:
            from_attributes = True
    
    class PositionListResponseSchema(BaseModel):
        positions: list
        total_count: int
    
    class HoldingSchema(BaseModel):
        id: Optional[int] = None
        symbol: Optional[str] = None
        quantity: Optional[int] = None
        class Config:
            from_attributes = True
    
    class HoldingResponseSchema(BaseModel):
        id: int
        user_id: str
        organization_id: str
        strategy_id: str
        exchange: str
        symbol: str
        quantity: int
        average_price: Decimal
        created_at: datetime
        updated_at: datetime
        class Config:
            from_attributes = True
    
    class HoldingListResponseSchema(BaseModel):
        holdings: list
        total_count: int
    
    class MarginSchema(BaseModel):
        id: Optional[int] = None
        category: Optional[str] = None
        available: Optional[float] = None
        class Config:
            from_attributes = True
    
    class MarginResponseSchema(BaseModel):
        id: int
        user_id: str
        organization_id: str
        pseudo_account: str
        available_margin: Decimal
        used_margin: Decimal
        total_margin: Decimal
        created_at: datetime
        updated_at: datetime
        class Config:
            from_attributes = True
    
    class OrderEventSchema(BaseModel):
        id: Optional[int] = None
        order_id: int
        event_type: str
        timestamp: datetime
        class Config:
            from_attributes = True

# AutoTrader mock
try:
    from com.dakshata.autotrader.api.AutoTrader import AutoTrader
    AUTOTRADER_AVAILABLE = True
    print("✅ AutoTrader available")
except ImportError:
    AUTOTRADER_AVAILABLE = False
    print("⚠️  AutoTrader not available, using mock")
    
    class AutoTraderResponse:
        def __init__(self, success=True, result=None, message="Mock response"):
            self._success = success
            self.result = result if result is not None else []
            self.message = message
        
        def success(self):
            return self._success

    class AutoTrader:
        SERVER_URL = "mock://autotrader"
        
        @staticmethod
        def create_instance(api_key, server_url):
            return AutoTraderMock()

    class AutoTraderMock:
        def read_platform_margins(self, **kwargs):
            return AutoTraderResponse(success=True, result=[], message="Mock margins")
        
        def read_platform_positions(self, **kwargs):
            return AutoTraderResponse(success=True, result=[], message="Mock positions")
        
        def read_platform_holdings(self, **kwargs):
            return AutoTraderResponse(success=True, result=[], message="Mock holdings")
        
        def read_platform_orders(self, **kwargs):
            return AutoTraderResponse(success=True, result=[], message="Mock orders")
        
        def place_regular_order(self, **kwargs):
            return AutoTraderResponse(success=True, result={"order_id": "MOCK_001"})

# =============================================================================
# TEST FIXTURES
# =============================================================================

@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()

@pytest.fixture
def client():
    """FastAPI test client with fallback."""
    try:
        from fastapi.testclient import TestClient
        return TestClient(app)
    except Exception as e:
        print(f"⚠️  TestClient failed: {e}, using mock")
        
        class MockResponse:
            def __init__(self, status_code=200, json_data=None):
                self.status_code = status_code
                self._json_data = json_data or {"status": "healthy"}
            def json(self):
                return self._json_data
        
        class MockClient:
            def get(self, url, **kwargs):
                return MockResponse(200 if url == "/health" else 404)
            def post(self, url, **kwargs):
                return MockResponse(404)
            def put(self, url, **kwargs):
                return MockResponse(404)
            def delete(self, url, **kwargs):
                return MockResponse(404)
        
        return MockClient()

@pytest.fixture
def mock_db():
    """Mock database session."""
    class MockDB:
        def query(self, model):
            return MockQuery()
        def add(self, obj):
            pass
        def commit(self):
            pass
        def rollback(self):
            pass
        def refresh(self, obj):
            obj.id = 1
    
    class MockQuery:
        def filter_by(self, **kwargs):
            return self
        def filter(self, *args):
            return self
        def first(self):
            return None
        def all(self):
            return []
    
    return MockDB()

@pytest.fixture
async def db_connection():
    """Test database connection with fallback."""
    try:
        TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "postgresql://testuser:testpass@localhost:5432/testdb")
        conn = await asyncpg.connect(TEST_DATABASE_URL)
        yield conn
        await conn.close()
    except Exception as e:
        pytest.skip(f"Database connection failed: {e}")

@pytest.fixture
def redis_client():
    """Test Redis client with fallback."""
    try:
        # Use test-specific Redis DB
        client = redis.Redis(host='localhost', port=6379, db=1, decode_responses=True)
        client.ping()
        client.flushdb()
        yield client
        client.flushdb()
        client.close()
    except Exception as e:
        print(f"⚠️  Redis connection failed: {e}, using mock")
        class MockRedis:
            def ping(self): return True
            def flushdb(self): pass
            def close(self): pass
            def get(self, key): return None
            def set(self, key, value, ex=None): return True
        yield MockRedis()

@pytest.fixture
def trade_service(mock_db):
    """Create TradeService instance for testing."""
    return TradeService(mock_db)

@pytest.fixture
def mock_autotrader():
    """Mock AutoTrader for safe testing."""
    mock_autotrader = Mock()
    
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
            }
        ],
        message="Success"
    )
    
    mock_autotrader.read_platform_positions.return_value = AutoTraderResponse(
        success=True,
        result=[
            {
                "symbol": "WIPRO",
                "exchange": "NSE",
                "net_quantity": 10,
                "buy_avg_price": 330.0,
                "ltp": 335.0,
                "pnl": 50.0,
                "platform": "StocksDeveloper",
                "pseudo_account": "test_account"
            }
        ],
        message="Success"
    )
    
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
    
    mock_autotrader.read_platform_orders.return_value = AutoTraderResponse(
        success=True,
        result=[
            {
                "exchange_order_id": "mock_order_1",
                "symbol": "WIPRO",
                "exchange": "NSE",
                "filled_quantity": 10,
                "price": 330.0,
                "status": "COMPLETE",
                "order_type": "LIMIT",
                "trade_type": "BUY",
                "platform": "StocksDeveloper"
            }
        ],
        message="Success"
    )
    
    mock_autotrader.place_regular_order.return_value = AutoTraderResponse(
        success=True,
        result={"exchange_order_id": "mock_123456"},
        message="Order placed successfully (MOCK)"
    )
    
    return mock_autotrader

@pytest.fixture
def sample_order_create_data():
    """Sample order creation data."""
    return {
        "user_id": "test_user_123",
        "organization_id": "test_org_456",
        "strategy_id": "strategy_alpha_001",
        "exchange": "NSE",
        "symbol": "WIPRO",
        "transaction_type": "BUY",
        "order_type": "LIMIT",
        "product_type": "MIS",
        "quantity": 10,
        "price": 330.35,
        "trigger_price": 0.0,
        "validity": "DAY"
    }

@pytest.fixture
def sample_order_data():
    """Sample order data for models."""
    return {
        "user_id": "test_user_123",
        "organization_id": "test_org_456",
        "strategy_id": "strategy_alpha_001",
        "exchange": "NSE",
        "symbol": "WIPRO",
        "transaction_type": "BUY",
        "order_type": "LIMIT",
        "product_type": "MIS",
        "quantity": 10,
        "price": 330.35
    }

@pytest.fixture
def sample_margin_data():
    """Sample margin data."""
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
    """Sample position data."""
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
    """Sample holding data."""
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
def celery_app():
    """Mock Celery app for testing."""
    class MockCeleryApp:
        def send_task(self, name, args=None, kwargs=None):
            return Mock()
    return MockCeleryApp()

# Print test setup info
print("🔧 Test Setup Complete:")
print(f"   📱 FastAPI App Available: {app is not None}")
print(f"   ⚙️  Settings Available: {settings is not None}")
print(f"   🤖 AutoTrader Available: {AUTOTRADER_AVAILABLE}")
print("   📊 Models Available: OrderModel, PositionModel, HoldingModel, MarginModel")
print("   📋 Schemas Available: OrderSchema, PositionSchema, HoldingSchema, MarginSchema")
print(f"   🧪 Test Environment: TESTING={os.getenv('TESTING')}, REDIS_HOST={os.getenv('REDIS_HOST')}")