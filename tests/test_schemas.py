import pytest
from datetime import datetime
from decimal import Decimal

# Import your actual schemas
from app.schemas.order_schema import OrderSchema, OrderCreateSchema, OrderResponseSchema
from app.schemas.position_schema import PositionSchema, PositionResponseSchema
from app.schemas.holding_schema import HoldingSchema, HoldingResponseSchema
from app.schemas.margin_schema import MarginSchema, MarginResponseSchema
from app.schemas.order_event_schema import OrderEventSchema

class TestOrderSchemas:
    """Test order schema validation."""
    
    def test_order_create_schema_validation(self, sample_order_create_data):
        """Test OrderCreateSchema validation."""
        schema = OrderCreateSchema(**sample_order_create_data)
        
        assert schema.user_id == "test_user_123"
        assert schema.strategy_id == "strategy_alpha_001"
        assert schema.quantity == 10
        assert schema.price == Decimal("330.35")
    
    def test_order_schema_with_optional_fields(self):
        """Test OrderSchema with optional fields."""
        order_data = {
            "symbol": "WIPRO",
            "exchange": "NSE",
            "order_type": "LIMIT",
            "status": "COMPLETE",
            "filled_quantity": 10
        }
        
        schema = OrderSchema(**order_data)
        assert schema.symbol == "WIPRO"
        assert schema.filled_quantity == 10
        assert schema.id is None  # Optional field
    
    def test_order_response_schema_serialization(self):
        """Test OrderResponseSchema JSON serialization."""
        response_data = {
            "id": 1,
            "user_id": "test_user",
            "organization_id": "test_org",
            "strategy_id": "test_strategy",
            "exchange": "NSE",
            "symbol": "WIPRO",
            "transaction_type": "BUY",
            "order_type": "LIMIT",
            "product_type": "INTRADAY",
            "quantity": 10,
            "status": "COMPLETE",
            "created_at": datetime.now(),
            "updated_at": datetime.now()
        }
        
        schema = OrderResponseSchema(**response_data)
        json_data = schema.dict()
        
        assert json_data["id"] == 1
        assert json_data["symbol"] == "WIPRO"

class TestMarginSchemas:
    """Test margin schema validation."""
    
    def test_margin_schema_validation(self, sample_margin_data):
        """Test MarginSchema validation."""
        schema = MarginSchema(**sample_margin_data)
        
        assert schema.available == 50000.0
        assert schema.category == "equity"
        assert schema.pseudo_account == "test_account"
    
    def test_margin_response_schema(self):
        """Test MarginResponseSchema."""
        response_data = {
            "id": 1,
            "user_id": "test_user",
            "organization_id": "test_org",
            "pseudo_account": "test_account",
            "available_margin": Decimal("50000.0"),
            "used_margin": Decimal("15000.0"),
            "total_margin": Decimal("65000.0"),
            "created_at": datetime.now(),
            "updated_at": datetime.now()
        }
        
        schema = MarginResponseSchema(**response_data)
        assert schema.available_margin == Decimal("50000.0")
        assert schema.pseudo_account == "test_account"

class TestPositionSchemas:
    """Test position schema validation."""
    
    def test_position_schema_validation(self, sample_position_data):
        """Test PositionSchema validation."""
        schema = PositionSchema(**sample_position_data)
        
        assert schema.symbol == "WIPRO"
        assert schema.net_quantity == 10
        assert schema.pnl == 50.0
    
    def test_position_response_schema(self):
        """Test PositionResponseSchema."""
        response_data = {
            "id": 1,
            "user_id": "test_user",
            "organization_id": "test_org",
            "strategy_id": "test_strategy",
            "exchange": "NSE",
            "symbol": "WIPRO",
            "product_type": "INTRADAY",
            "quantity": 10,
            "average_price": Decimal("330.0"),
            "created_at": datetime.now(),
            "updated_at": datetime.now()
        }
        
        schema = PositionResponseSchema(**response_data)
        assert schema.symbol == "WIPRO"
        assert schema.quantity == 10

class TestHoldingSchemas:
    """Test holding schema validation."""
    
    def test_holding_schema_validation(self, sample_holding_data):
        """Test HoldingSchema validation."""
        schema = HoldingSchema(**sample_holding_data)
        
        assert schema.symbol == "INFY"
        assert schema.quantity == 50
        assert schema.avg_price == 1500.0
    
    def test_holding_response_schema(self):
        """Test HoldingResponseSchema."""
        response_data = {
            "id": 1,
            "user_id": "test_user",
            "organization_id": "test_org",
            "strategy_id": "test_strategy",
            "exchange": "NSE",
            "symbol": "INFY",
            "quantity": 50,
            "average_price": Decimal("1500.0"),
            "created_at": datetime.now(),
            "updated_at": datetime.now()
        }
        
        schema = HoldingResponseSchema(**response_data)
        assert schema.symbol == "INFY"
        assert schema.quantity == 50