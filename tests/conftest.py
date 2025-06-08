# trade_service/tests/conftest.py
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from shared_architecture.db import Base, get_db
from app.core.config import settings
from app.main import app as main_app  # Import your main FastAPI app
from app.models.order_model import OrderModel
from app.models.position_model import PositionModel
from app.models.holding_model import HoldingModel
from app.models.margin_model import MarginModel

# Override settings for testing (e.g., use an in-memory database)
settings.timescaledb_url = "sqlite:///:memory:"
settings.redis_url = "redis://localhost:6379/1"  # Use a separate Redis DB for testing

@pytest.fixture(scope="session")
def test_app() -> FastAPI:
    """
    Overrides the database dependency to use an in-memory SQLite database for testing.
    """
    # Create a new FastAPI application instance for testing
    test_app = FastAPI()

    # Create an in-memory SQLite database engine
    engine = create_engine(
        settings.timescaledb_url,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # Override the get_db dependency
    def override_get_db():
        try:
            db = TestingSessionLocal()
            yield db
        finally:
            db.close()

    test_app.dependency_overrides[get_db] = override_get_db

    # Include the main app's routers (assuming you have them in main_app)
    test_app.include_router(main_app.trades_router)  # Adjust based on your router names

    # Create tables
    Base.metadata.create_all(bind=engine)

    yield test_app  # Provide the test app to tests

    # Clean up (drop tables) - optional, but good for isolation
    Base.metadata.drop_all(bind=engine)

@pytest.fixture(scope="function")
def test_client(test_app: FastAPI) -> TestClient:
    """
    Creates a TestClient for interacting with the test FastAPI app.
    """
    with TestClient(test_app) as client:
        yield client

@pytest.fixture(scope="function")
def test_db(test_app: FastAPI) -> Session:
    """
    Provides a database session for testing.
    """
    engine = create_engine(
        settings.timescaledb_url,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

def create_test_order(db: Session, **kwargs) -> OrderModel:
    """
    Helper function to create a test order.
    """
    defaults = {
        "pseudo_account": "test_user",
        "exchange": "NSE",
        "symbol": "INFY",
        "trade_type": "BUY",
        "order_type": "MARKET",
        "product_type": "CNC",
        "quantity": 100,
        "price": 1000.0,
        "instrument_key": "NSE@INFY@CNC@@@",
        "strategy_id": "test_strategy",
    }
    defaults.update(kwargs)
    order = OrderModel(**defaults)
    db.add(order)
    db.commit()
    db.refresh(order)  # Get the generated ID
    return order

def create_test_position(db: Session, **kwargs) -> PositionModel:
    """
    Helper function to create a test position.
    """
    defaults = {
        "account_id": "test_account",
        "direction": "BUY",
        "instrument_key": "NSE@INFY@CNC@@@",
        "pseudo_account": "test_user",
        "strategy_id": "test_strategy",
        "net_quantity": 100,
    }
    defaults.update(kwargs)
    position = PositionModel(**defaults)
    db.add(position)
    db.commit()
    return position

def create_test_holding(db: Session, **kwargs) -> HoldingModel:
    """
    Helper function to create a test holding.
    """
    defaults = {
        "pseudo_account": "test_user",
        "instrument_key": "NSE@INFY@CNC@@@",
        "strategy_id": "test_strategy",
        "quantity": 100,
        "product": "CNC",
    }
    defaults.update(kwargs)
    holding = HoldingModel(**defaults)
    db.add(holding)
    db.commit()
    return holding

def create_test_margin(db: Session, **kwargs) -> MarginModel:
    """
    Helper function to create a test margin.
    """
    defaults = {
        "user_id": 1,
        "pseudo_account": "test_user",
        "category": "Cash",
        "instrument_key": "NSE@INFY@CNC@@@",
        "margin_date": datetime.now(),
    }
    defaults.update(kwargs)
    margin = MarginModel(**defaults)
    db.add(margin)
    db.commit()
    return margin