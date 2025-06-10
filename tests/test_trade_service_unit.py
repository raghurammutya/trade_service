import pytest
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime

# CORRECT IMPORTS BASED ON YOUR ACTUAL STRUCTURE
from app.services.trade_service import TradeService
from shared_architecture.db.models.order_model import OrderModel
from shared_architecture.db.models.position_model import PositionModel
from shared_architecture.db.models.holding_model import HoldingModel
from shared_architecture.db.models.margin_model import MarginModel

class TestTradeServiceUnit:
    """Unit tests for TradeService - using your actual implementation."""
    
    def test_trade_service_initialization(self):
        """Test TradeService can be initialized."""
        trade_service = TradeService()
        assert trade_service is not None
        assert hasattr(trade_service, 'stocksdeveloper_conn')
    
    @patch('com.dakshata.autotrader.api.AutoTrader.create_instance')
    async def test_get_margins_with_mock(self, mock_create_instance, trade_service, mock_autotrader):
        """Test get_margins with mocked AutoTrader."""
        mock_create_instance.return_value = mock_autotrader
        
        # Test get_margins method from your actual trade_service.py
        result = await trade_service.get_margins(
            organization_id="test_org",
            pseudo_account="test_account"
        )
        
        # Verify the call was made
        mock_autotrader.read_platform_margins.assert_called_once()
        assert isinstance(result, dict)
    
    @patch('com.dakshata.autotrader.api.AutoTrader.create_instance')
    async def test_get_positions_with_mock(self, mock_create_instance, trade_service, mock_autotrader):
        """Test get_positions with mocked AutoTrader."""
        mock_create_instance.return_value = mock_autotrader
        
        # Test get_positions method from your actual trade_service.py
        result = await trade_service.get_positions(
            organization_id="test_org",
            pseudo_account="test_account"
        )
        
        mock_autotrader.read_platform_positions.assert_called_once()
        assert isinstance(result, list)
    
    def test_order_model_creation_shared_architecture(self, sample_order_data):
        """Test OrderModel creation from shared_architecture."""
        order = OrderModel(
            user_id=sample_order_data["user_id"],
            organization_id=sample_order_data["organization_id"],
            strategy_id=sample_order_data["strategy_id"],
            exchange=sample_order_data["exchange"],
            symbol=sample_order_data["symbol"],
            transaction_type=sample_order_data["transaction_type"],
            order_type=sample_order_data["order_type"],
            product_type=sample_order_data["product_type"],
            quantity=sample_order_data["quantity"],
            price=sample_order_data["price"]
        )
        
        assert order.user_id == "test_user_123"
        assert order.strategy_id == "strategy_alpha_001"
        assert order.quantity == 10
        assert order.price == 330.35
    
    def test_position_model_creation_shared_architecture(self):
        """Test PositionModel creation from shared_architecture."""
        position = PositionModel(
            user_id="test_user",
            organization_id="test_org",
            strategy_id="test_strategy",
            exchange="NSE",
            symbol="WIPRO",
            product_type="INTRADAY",
            quantity=10,
            average_price=100.0
        )
        
        assert position.quantity == 10
        assert position.average_price == 100.0