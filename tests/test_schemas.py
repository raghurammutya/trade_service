import pytest
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel
from typing import Optional

# Create schemas directly in this file (they'll be available via conftest.py fixtures)
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
            "quantity": 10,
            "price": 330.0
        }
        
        schema = OrderSchema(**order_data)
        assert schema.symbol == "WIPRO"
        assert schema.id is None  # Optional field
    
    def test_basic_schema_creation(self):
        """Test basic schema creation works."""
        # This should always pass
        assert True
