# trade_service/tests/test_trade_service_unit.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.trade_service import TradeService
from app.core.config import settings
from app.models.order_model import OrderModel, OrderTransitionType
from app.models.position_model import PositionModel
from app.models.holding_model import HoldingModel
from app.schemas.trade_schemas import TradeOrder
from sqlalchemy.orm import Session
from fastapi import HTTPException
from datetime import datetime

# Mock the AutoTrader class and its methods
class MockAutoTrader:
    @staticmethod
    def create_instance(api_key, server_url):
        return MockAutoTraderInstance()

class MockAutoTraderInstance:
    async def place_regular_order(self, *args, **kwargs):
        return MagicMock(success=True, result={"order_id": "test_order_123", "status": "COMPLETE"})

    async def get_order_status(self, order_id):
        return {"order_id": order_id, "status": "COMPLETE"}

    async def read_platform_margins(self, pseudo_account):
        return []

    async def read_platform_positions(self, pseudo_account):
        return []

    async def read_platform_holdings(self, pseudo_account):
        return []

    async def read_platform_orders(self, pseudo_account):
        return []

    async def cancel_order_by_platform_id(self, pseudo_account, platform_id):
        return MagicMock(success=True, result={"status": "CANCELLED"})

    async def cancel_child_orders_by_platform_id(self, pseudo_account, platform_id):
        return MagicMock(success=True, result={"status": "CANCELLED"})

    async def modify_order_by_platform_id(self, pseudo_account, platform_id, order_type=None, quantity=None, price=None, trigger_price=None):
        return MagicMock(success=True, result={"status": "MODIFIED"})

    async def square_off_position(self, pseudo_account, position_category, position_type, exchange, symbol):
        return MagicMock(success=True, result={"status": "SQUARED_OFF"})

    async def square_off_portfolio(self, pseudo_account, position_category):
        return MagicMock(success=True, result={"status": "SQUARED_OFF"})

    async def cancel_all_orders(self, pseudo_account):
        return MagicMock(success=True, result={"status": "ALL_ORDERS_CANCELLED"})

# Mock the requests library
class MockRequests:
    @staticmethod
    async def get(*args, **kwargs):
        mock_response = MagicMock()
        mock_response.json.return_value = {"trading_accounts_data": []}
        mock_response.raise_for_status.return_value = None
        return mock_response

    class exceptions:
        RequestException = Exception

    class HTTPError(Exception):
        pass

# Apply the mocks
@pytest.fixture(autouse=True)
def apply_mocks(mocker):
    mocker.patch("com.dakshata.autotrader.api.AutoTrader", MockAutoTrader)
    mocker.patch("httpx.AsyncClient", MockRequests)
    mocker.patch("requests", MockRequests)

@pytest.mark.asyncio
async def test_execute_trade_order(test_db: Session, mocker):
    mocker.patch("app.utils.rate_limiter.RateLimiter.user_rate_limit", return_value=True)
    mocker.patch("app.utils.rate_limiter.RateLimiter.account_rate_limit", return_value=True)

    trade_service = TradeService(test_db)
    trade_order = TradeOrder(user_id="test_user", symbol="INFY", quantity=100, price=1000.0, side="BUY")

    order_status = await trade_service.execute_trade_order(trade_order, "test_org")

    assert order_status == {"message": "Order processing started"}
    assert test_db.query(OrderModel).count() == 1
    assert test_db.query(OrderEventModel).count() == 1
    event = test_db.query(OrderEventModel).first()
    assert event.event_type == OrderEvent.ORDER_PLACED

@pytest.mark.asyncio
async def test_get_trade_status(test_db: Session, mocker):
    mocker.patch("app.utils.rate_limiter.RateLimiter.user_rate_limit", return_value=True)
    mocker.patch("app.utils.rate_limiter.RateLimiter.account_rate_limit", return_value=True)
    mocker.patch("app.utils.rate_limiter.RateLimiter.redis_conn.get", return_value=None)
    mocker.patch("app.services.trade_service.TradeService._get_api_key", return_value="test_api_key")

    trade_service = TradeService(test_db)
    order_id = "test_order_123"

    status = await trade_service.get_trade_status(order_id, "test_org")

    assert status == {"order_id": order_id, "status": "COMPLETE"}

@pytest.mark.asyncio
async def test_fetch_and_store_data(test_db: Session, mocker):
    mocker.patch("app.utils.rate_limiter.RateLimiter.account_rate_limit", return_value=True)
    mocker.patch("app.services.trade_service.TradeService._get_api_key", return_value="test_api_key")

    trade_service = TradeService(test_db)
    pseudo_acc = "test_user"

    await trade_service.fetch_and_store_data(pseudo_acc, "test_org")

    assert test_db.query(MarginModel).count() == 0
    assert test_db.query(PositionModel).count() == 0
    assert test_db.query(HoldingModel).count() == 0
    assert test_db.query(OrderModel).count() == 0

@pytest.mark.asyncio
async def test_fetch_all_trading_accounts(test_db: Session, mocker):
    mocker.patch("app.utils.rate_limiter.RateLimiter.account_rate_limit", return_value=True)
    mocker.patch("app.services.trade_service.TradeService._get_api_key", return_value="test_api_key")

    trade_service = TradeService(test_db)

    accounts = await trade_service.fetch_all_trading_accounts("test_org")

    assert accounts == {"trading_accounts_data": []}

@pytest.mark.asyncio
async def test_place_regular_order(test_db: Session, mocker):
    mocker.patch("app.utils.rate_limiter.RateLimiter.user_rate_limit", return_value=True)
    mocker.patch("app.utils.rate_limiter.RateLimiter.account_rate_limit", return_value=True)
    mock_celery = mocker.patch("app.core.celery_config.celery_app.send_task")

    trade_service = TradeService(test_db)
    order_data = {
        "pseudo_account": "test_user",
        "exchange": "NSE",
        "symbol": "INFY",
        "tradeType": "BUY",
        "orderType": "MARKET",
        "productType": "CNC",
        "quantity": 100,
        "price": 1000.0,
        "triggerPrice": 0.0,
        "strategy_id": "test_strategy",
    }
    result = await trade_service.place_regular_order(**order_data, organization_id="test_org")

    assert test_db.query(OrderModel).count() == 1
    assert test_db.query(OrderEventModel).count() == 1
    assert result == {"message": "Order processing started"}
    mock_celery.assert_called_once()

@pytest.mark.asyncio
async def test_place_cover_order(test_db: Session, mocker):
    mocker.patch("app.utils.rate_limiter.RateLimiter.user_rate_limit", return_value=True)
    mocker.patch("app.utils.rate_limiter.RateLimiter.account_rate_limit", return_value=True)
    mock_celery = mocker.patch("app.core.celery_config.celery_app.send_task")

    trade_service = TradeService(test_db)
    order_data = {
        "pseudo_account": "test_user",
        "exchange": "NSE",
        "symbol": "INFY",
        "tradeType": "BUY",
        "orderType": "MARKET",
        "quantity": 100,
        "price": 1000.0,
        "triggerPrice": 1005.0,
        "strategy_id": "test_strategy",
    }
    result = await trade_service.place_cover_order(**order_data, organization_id="test_org")

    assert test_db.query(OrderModel).count() == 1
    assert result == {"message": "Cover Order processing started"}
    mock_celery.assert_called_once()

@pytest.mark.asyncio
async def test_place_bracket_order(test_db: Session, mocker):
    mocker.patch("app.utils.rate_limiter.RateLimiter.user_rate_limit", return_value=True)
    mocker.patch("app.utils.rate_limiter.RateLimiter.account_rate_limit", return_value=True)
    mock_celery = mocker.patch("app.core.celery_config.celery_app.send_task")

    trade_service = TradeService(test_db)
    order_data = {
        "pseudo_account": "test_user",
        "exchange": "NSE",
        "symbol": "INFY",
        "tradeType": "BUY",
        "orderType": "MARKET",
        "quantity": 100,
        "price": 1000.0,
        "triggerPrice": 1005.0,
        "target": 1010.0,
        "stoploss": 995.0,
        "trailingStoploss": 5.0,
        "strategy_id": "test_strategy",
    }
    result = await trade_service.place_bracket_order(**order_data, organization_id="test_org")

    assert test_db.query(OrderModel).count() == 1
    assert result == {"message": "Bracket Order processing started"}
    mock_celery.assert_called_once()

@pytest.mark.asyncio
async def test_place_advanced_order(test_db: Session, mocker):
    mocker.patch("app.utils.rate_limiter.RateLimiter.user_rate_limit", return_value=True)
    mocker.patch("app.utils.rate_limiter.RateLimiter.account_rate_limit", return_value=True)
    mock_celery = mocker.patch("app.core.celery_config.celery_app.send_task")

    trade_service = TradeService(test_db)
    order_data = {
        "variety": "AMO",
        "pseudo_account": "test_user",
        "exchange": "NSE",
        "symbol": "INFY",
        "tradeType": "BUY",
        "orderType": "MARKET",
        "productType": "CNC",
        "quantity": 100,
        "price": 1000.0,
        "triggerPrice": 1005.0,
        "target": 1010.0,
        "stoploss": 995.0,
        "trailingStoploss": 5.0,
        "disclosedQuantity": 90,
        "validity": "DAY",
        "amo": True,
        "strategyId": "test_strategy",
        "comments": "Test order",
        "publisherId": "test_publisher",
    }
    result = await trade_service.place_advanced_order(**order_data, organization_id="test_org")

    assert test_db.query(OrderModel).count() == 1
    assert result == {"message": "Advanced Order processing started"}
    mock_celery.assert_called_once()

@pytest.mark.asyncio
async def test_cancel_order_by_platform_id(test_db: Session, mocker):
    mocker.patch("app.utils.rate_limiter.RateLimiter.user_rate_limit", return_value=True)
    mocker.patch("app.utils.rate_limiter.RateLimiter.account_rate_limit", return_value=True)
    mock_celery = mocker.patch("app.core.celery_config.celery_app.send_task")

    trade_service = TradeService(test_db)
    pseudo_account = "test_user"
    platform_id = "test_platform_id"

    result = await trade_service.cancel_order_by_platform_id(pseudo_account, platform_id, organization_id="test_org")

    assert result == {"message": f"Cancel order request submitted for platform_id: {platform_id}"}
    mock_celery.assert_called_once()

@pytest.mark.asyncio
async def test_cancel_child_orders_by_platform_id(test_db: Session, mocker):
    mocker.patch("app.utils.rate_limiter.RateLimiter.user_rate_limit", return_value=True)
    mocker.patch("app.utils.rate_limiter.RateLimiter.account_rate_limit", return_value=True)
    mock_celery = mocker.patch("app.core.celery_config.celery_app.send_task")

    trade_service = TradeService(test_db)
    pseudo_account = "test_user"
    platform_id = "test_platform_id"

    result = await trade_service.cancel_child_orders_by_platform_id(pseudo_account, platform_id, organization_id="test_org")

    assert result == {"message": f"Cancel child orders request submitted for platform_id: {platform_id}"}
    mock_celery.assert_called_once()

@pytest.mark.asyncio
async def test_modify_order_by_platform_id(test_db: Session, mocker):
    mocker.patch("app.utils.rate_limiter.RateLimiter.user_rate_limit", return_value=True)
    mocker.patch("app.utils.rate_limiter.RateLimiter.account_rate_limit", return_value=True)
    mock_celery = mocker.patch("app.core.celery_config.celery_app.send_task")

    trade_service = TradeService(test_db)
    pseudo_account = "test_user"
    platform_id = "test_platform_id"

    result = await trade_service.modify_order_by_platform_id(pseudo_account, platform_id, order_type="LIMIT", quantity=110, price=1001.0, trigger_price=1006.0, organization_id="test_org")

    assert result == {"message": f"Modify order request submitted for platform_id: {platform_id}"}
    mock_celery.assert_called_once()

@pytest.mark.asyncio
async def test_square_off_position(test_db: Session, mocker):
    mocker.patch("app.utils.rate_limiter.RateLimiter.user_rate_limit", return_value=True)
    mocker.patch("app.utils.rate_limiter.RateLimiter.account_rate_limit", return_value=True)
    mock_celery = mocker.patch("app.core.celery_config.celery_app.send_task")

    trade_service = TradeService(test_db)
    pseudo_account = "test_user"
    position_category = "Cash"
    position_type = "Equity"
    exchange = "NSE"
    symbol = "INFY"

    result = await trade_service.square_off_position(pseudo_account, position_category, position_type, exchange, symbol, organization_id="test_org")

    assert result == {"message": f"Square off position request submitted"}
    mock_celery.assert_called_once()

@pytest.mark.asyncio
async def test_square_off_portfolio(test_db: Session, mocker):
    mocker.patch("app.utils.rate_limiter.RateLimiter.user_rate_limit", return_value=True)
    mocker.patch("app.utils.rate_limiter.RateLimiter.account_rate_limit", return_value=True)
    mock_celery = mocker.patch("app.core.celery_config.celery_app.send_task")

    trade_service = TradeService(test_db)
    pseudo_account = "test_user"
    position_category = "Cash"

    result = await trade_service.square_off_portfolio(pseudo_account, position_category, organization_id="test_org")

    assert result == {"message": f"Square off portfolio request submitted"}
    mock_celery.assert_called_once()

@pytest.mark.asyncio
async def test_cancel_all_orders(test_db: Session, mocker):
    mocker.patch("app.utils.rate_limiter.RateLimiter.user_rate_limit", return_value=True)
    mocker.patch("app.utils.rate_limiter.RateLimiter.account_rate_limit", return_value=True)
    mock_celery = mocker.patch("app.core.celery_config.celery_app.send_task")

    trade_service = TradeService(test_db)
    pseudo_account = "test_user"

    result = await trade_service.cancel_all_orders(pseudo_account, organization_id="test_org")

    assert result == {"message": f"Cancel all orders request submitted"}
    mock_celery.assert_called_once()

@pytest.mark.asyncio
async def test_get_organization_name_for_user_success(test_db: Session, mocker):
    mocker.patch.object(TradeService, "redis_conn", autospec=True)
    trade_service = TradeService(test_db)
    trade_service.redis_conn.get.return_value = b"TestOrg"

    organization_name = await trade_service._get_organization_name_for_user("test_user")

    assert organization_name == "TestOrg"
    trade_service.redis_conn.get.assert_called_once_with("user:test_user:organization")

@pytest.mark.asyncio
async def test_get_organization_name_for_user_not_found(test_db: Session, mocker):
    mocker.patch.object(TradeService, "redis_conn", autospec=True)
    trade_service = TradeService(test_db)
    trade_service.redis_conn.get.return_value = None

    with pytest.raises(ValueError, match="Organization name not found for user: test_user"):
        await trade_service._get_organization_name_for_user("test_user")

@pytest.mark.asyncio
async def test_get_orders_by_organization_and_user(test_db: Session, mocker):
    mocker.patch.object(TradeService, "_get_organization_name_for_user", autospec=True)
    mocker.patch.object(TradeService, "rate_limiter", autospec=True)
    trade_service = TradeService(test_db)
    trade_service._get_organization_name_for_user.return_value = "TestOrg"
    trade_service.rate_limiter.account_rate_limit.return_value = True

    create_test_order(test_db, pseudo_account="test_user")
    create_test_order(test_db, pseudo_account="test_user")

    orders = await trade_service.get_orders_by_organization_and_user("test_user")

    assert len(orders) == 2
    assert orders[0].pseudo_account == "test_user"

@pytest.mark.asyncio
async def test_get_positions_by_organization_and_user(test_db: Session, mocker):
    mocker.patch.object(TradeService, "_get_organization_name_for_user", autospec=True)
    mocker.patch.object(TradeService, "rate_limiter", autospec=True)
    trade_service = TradeService(test_db)
    trade_service._get_organization_name_for_user.return_value = "TestOrg"
    trade_service.rate_limiter.account_rate_limit.return_value = True

    create_test_position(test_db, pseudo_account="test_user")
    create_test_position(test_db, pseudo_account="test_user")

    positions = await trade_service.get_positions_by_organization_and_user("test_user")

    assert len(positions) == 2
    assert positions[0].pseudo_account == "test_user"

@pytest.mark.asyncio
async def test_get_holdings_by_organization_and_user(test_db: Session, mocker):
    mocker.patch.object(TradeService, "_get_organization_name_for_user", autospec=True)
    mocker.patch.object(TradeService, "rate_limiter", autospec=True)
    trade_service = TradeService(test_db)
    trade_service._get_organization_name_for_user.return_value = "TestOrg"
    trade_service.rate_limiter.account_rate_limit.return_value = True

    create_test_holding(test_db, pseudo_account="test_user")
    create_test_holding(test_db, pseudo_account="test_user")

    holdings = await trade_service.get_holdings_by_organization_and_user("test_user")

    assert len(holdings) == 2
    assert holdings[0].pseudo_account == "test_user"

@pytest.mark.asyncio
async def test_get_margins_by_organization_and_user(test_db: Session, mocker):
    mocker.patch.object(TradeService, "_get_organization_name_for_user", autospec=True)
    mocker.patch.object(TradeService, "rate_limiter", autospec=True)
    trade_service = TradeService(test_db)
    trade_service._get_organization_name_for_user.return_value = "TestOrg"
    trade_service.rate_limiter.account_rate_limit.return_value = True

    create_test_margin(test_db, pseudo_account="test_user")
    create_test_margin(test_db, pseudo_account="test_user")

    margins = await trade_service.get_margins_by_organization_and_user("test_user")

    assert len(margins) == 2
    assert margins[0].pseudo_account == "test_user"

@pytest.mark.asyncio
async def test_get_orders_by_strategy(test_db: Session):
    trade_service = TradeService(test_db)
    create_test_order(test_db, strategy_id="test_strategy_a")
    create_test_order(test_db, strategy_id="test_strategy_a")
    create_test_order(test_db, strategy_id="test_strategy_b")

    orders = await trade_service.get_orders_by_strategy("test_strategy_a")

    assert len(orders) == 2
    assert orders[0].strategy_id == "test_strategy_a"

@pytest.mark.asyncio
async def test_get_positions_by_strategy(test_db: Session):
    trade_service = TradeService(test_db)
    create_test_position(test_db, strategy_id="test_strategy_a")
    create_test_position(test_db, strategy_id="test_strategy_a")
    create_test_position(test_db, strategy_id="test_strategy_b")

    positions = await trade_service.get_positions_by_strategy("test_strategy_a")

    assert len(positions) == 2
    assert positions[0].strategy_id == "test_strategy_a"

@pytest.mark.asyncio
async def test_get_holdings_by_strategy(test_db: Session):
    trade_service = TradeService(test_db)
    create_test_holding(test_db, strategy_id="test_strategy_a")
    create_test_holding(test_db, strategy_id="test_strategy_a")
    create_test_holding(test_db, strategy_id="test_strategy_b")

    holdings = await trade_service.get_holdings_by_strategy("test_strategy_a")

    assert len(holdings) == 2
    assert holdings[0].strategy_id == "test_strategy_a"

@pytest.mark.asyncio
async def test_check_for_conflicting_orders(test_db: Session):
    trade_service = TradeService(test_db)

    # Create a position from strategy_a
    create_test_position(test_db, strategy_id="strategy_a", direction="BUY")

    # Create an order from strategy_b
    order = create_test_order(test_db, strategy_id="strategy_b", trade_type="SELL")

    # Check for conflict - should raise an exception
    with pytest.raises(HTTPException, match="Conflict: Cannot place SELL order when BUY position exists from another strategy"):
        await trade_service._check_for_conflicting_orders(
            order.pseudo_account, order.instrument_key, order.trade_type, order.strategy_id
        )

    # Clean up
    test_db.query(PositionModel).delete()
    test_db.query(OrderModel).delete()
    test_db.commit()

@pytest.mark.asyncio
async def test_handle_holding_to_position_transition_success(test_db: Session):
    trade_service = TradeService(test_db)
    create_test_holding(test_db, pseudo_account="test_user", instrument_key="test_instrument", strategy_id="test_strategy", quantity=100)

    await trade_service._handle_holding_to_position_transition(
        pseudo_account="test_user", instrument_key="test_instrument", quantity=50, strategy_id="test_strategy"
    )

    updated_holding = test_db.query(HoldingModel).filter_by(pseudo_account="test_user", instrument_key="test_instrument", strategy_id="test_strategy").first()
    new_position = test_db.query(PositionModel).filter_by(pseudo_account="test_user", instrument_key="test_instrument", strategy_id="test_strategy").first()

    assert updated_holding.quantity == 50
    assert new_position.net_quantity == -50
    assert new_position.direction == "SELL"

@pytest.mark.asyncio
async def test_handle_holding_to_position_transition_insufficient(test_db: Session):
    trade_service = TradeService(test_db)
    create_test_holding(test_db, pseudo_account="test_user", instrument_key="test_instrument", strategy_id="test_strategy", quantity=100)

    with pytest.raises(HTTPException, match="Insufficient holdings for test_instrument for strategy test_strategy"):
        await trade_service._handle_holding_to_position_transition(
            pseudo_account="test_user", instrument_key="test_instrument", quantity=150, strategy_id="test_strategy"
        )

@pytest.mark.asyncio
async def test_execute_trade_order_with_celery(test_db: Session, mocker):
    mocker.patch("app.utils.rate_limiter.RateLimiter.user_rate_limit", return_value=True)
    mocker.patch("app.utils.rate_limiter.RateLimiter.account_rate_limit", return_value=True)
    mock_celery = mocker.patch("app.core.celery_app.process_order_task.delay")

    trade_service = TradeService(test_db)
    trade_order = TradeOrder(user_id="test_user", symbol="INFY", quantity=100, price=1000.0, side="BUY")

    order_status = await trade_service.execute_trade_order(trade_order, "test_org")

    assert order_status == {"message": "Order processing started"}
    assert mock_celery.called

@pytest.mark.asyncio
async def test_place_regular_order_with_celery(test_db: Session, mocker):
    mocker.patch("app.utils.rate_limiter.RateLimiter.user_rate_limit", return_value=True)
    mocker.patch("app.utils.rate_limiter.RateLimiter.account_rate_limit", return_value=True)
    mock_celery = mocker.patch("app.core.celery_app.process_order_task.delay")

    trade_service = TradeService(test_db)
    order_data = {
        "pseudo_account": "test_user",
        "exchange": "NSE",
        "symbol": "INFY",
        "tradeType": "BUY",
        "orderType": "MARKET",
        "productType": "CNC",
        "quantity": 100,
        "price": 1000.0,
        "triggerPrice": 0.0,
        "strategy_id": "test_strategy",
    }
    result = await trade_service.place_regular_order(**order_data, organization_id="test_org")

    assert result == {"message": "Order processing started"}
    mock_celery.assert_called_once()

@pytest.mark.asyncio
async def test_place_cover_order_with_celery(test_db: Session, mocker):
    mocker.patch("app.utils.rate_limiter.RateLimiter.user_rate_limit", return_value=True)
    mocker.patch("app.utils.rate_limiter.RateLimiter.account_rate_limit", return_value=True)
    mock_celery = mocker.patch("app.core.celery_app.process_order_task.delay")

    trade_service = TradeService(test_db)
    order_data = {
        "pseudo_account": "test_user",
        "exchange": "NSE",
        "symbol": "INFY",
        "tradeType": "BUY",
        "orderType": "MARKET",
        "quantity": 100,
        "price": 1000.0,
        "triggerPrice": 1005.0,
        "strategy_id": "test_strategy",
    }
    result = await trade_service.place_cover_order(**order_data, organization_id="test_org")

    assert result == {"message": "Cover Order processing started"}
    mock_celery.assert_called_once()

@pytest.mark.asyncio
async def test_place_bracket_order_with_celery(test_db: Session, mocker):
    mocker.patch("app.utils.rate_limiter.RateLimiter.user_rate_limit", return_value=True)
    mocker.patch("app.utils.rate_limiter.RateLimiter.account_rate_limit", return_value=True)
    mock_celery = mocker.patch("app.core.celery_app.process_order_task.delay")

    trade_service = TradeService(test_db)
    order_data = {
        "pseudo_account": "test_user",
        "exchange": "NSE",
        "symbol": "INFY",
        "tradeType": "BUY",
        "orderType": "MARKET",
        "quantity": 100,
        "price": 1000.0,
        "triggerPrice": 1005.0,
        "target": 1010.0,
        "stoploss": 995.0,
        "trailingStoploss": 5.0,
        "strategy_id": "test_strategy",
    }
    result = await trade_service.place_bracket_order(**order_data, organization_id="test_org")

    assert result == {"message": "Bracket Order processing started"}
    mock_celery.assert_called_once()

@pytest.mark.asyncio
async def test_place_advanced_order_with_celery(test_db: Session, mocker):
    mocker.patch("app.utils.rate_limiter.RateLimiter.user_rate_limit", return

@pytest.mark.asyncio
async def test_cancel_order_by_platform_id(test_db: Session, mocker):
    mocker.patch("app.utils.rate_limiter.RateLimiter.user_rate_limit", return_value=True)
    mocker.patch("app.utils.rate_limiter.RateLimiter.account_rate_limit", return_value=True)

    trade_service = TradeService(test_db)
    pseudo_account = "test_user"
    platform_id = "test_platform_id"

    result = await trade_service.cancel_order_by_platform_id(pseudo_account, platform_id)

    assert result == {"status": "CANCELLED"}

@pytest.mark.asyncio
async def test_cancel_child_orders_by_platform_id(test_db: Session, mocker):
    mocker.patch("app.utils.rate_limiter.RateLimiter.user_rate_limit", return_value=True)
    mocker.patch("app.utils.rate_limiter.RateLimiter.account_rate_limit", return_value=True)

    trade_service = TradeService(test_db)
    pseudo_account = "test_user"
    platform_id = "test_platform_id"

    result = await trade_service.cancel_child_orders_by_platform_id(pseudo_account, platform_id)

    assert result == {"status": "CANCELLED"}

@pytest.mark.asyncio
async def test_modify_order_by_platform_id(test_db: Session, mocker):
    mocker.patch("app.utils.rate_limiter.RateLimiter.user_rate_limit", return_value=True)
    mocker.patch("app.utils.rate_limiter.RateLimiter.account_rate_limit", return_value=True)

    trade_service = TradeService(test_db)
    pseudo_account = "test_user"
    platform_id = "test_platform_id"

    result = await trade_service.modify_order_by_platform_id(pseudo_account, platform_id, order_type="LIMIT", quantity=110, price=1001.0, trigger_price=1006.0)

    assert result == {"status": "MODIFIED"}

@pytest.mark.asyncio
async def test_square_off_position(test_db: Session, mocker):
    mocker.patch("app.utils.rate_limiter.RateLimiter.user_rate_limit", return_value=True)
    mocker.patch("app.utils.rate_limiter.RateLimiter.account_rate_limit", return_value=True)

    trade_service = TradeService(test_db)
    pseudo_account = "test_user"
    position_category = "Cash"
    position_type = "Equity"
    exchange = "NSE"
    symbol = "INFY"

    result = await trade_service.square_off_position(pseudo_account, position_category, position_type, exchange, symbol)

    assert result == {"status": "SQUARED_OFF"}

@pytest.mark.asyncio
async def test_square_off_portfolio(test_db: Session, mocker):
    mocker.patch("app.utils.rate_limiter.RateLimiter.user_rate_limit", return_value=True)
    mocker.patch("app.utils.rate_limiter.RateLimiter.account_rate_limit", return_value=True)

    trade_service = TradeService(test_db)
    pseudo_account = "test_user"
    position_category = "Cash"

    result = await trade_service.square_off_portfolio(pseudo_account, position_category)

    assert result == {"status": "SQUARED_OFF"}

@pytest.mark.asyncio
async def test_cancel_all_orders(test_db: Session, mocker):
    mocker.patch("app.utils.rate_limiter.RateLimiter.user_rate_limit", return_value=True)
    mocker.patch("app.utils.rate_limiter.RateLimiter.account_rate_limit", return_value=True)

    trade_service = TradeService(test_db)
    pseudo_account = "test_user"

    result = await trade_service.cancel_all_orders(pseudo_account)

    assert result == {"status": "ALL_ORDERS_CANCELLED"}

@pytest.mark.asyncio
async def test_get_organization_name_for_user_success(test_db: Session, mocker):
    mocker.patch.object(TradeService, "redis_conn", autospec=True)
    trade_service = TradeService(test_db)
    trade_service.redis_conn.get.return_value = b"TestOrg"

    organization_name = await trade_service._get_organization_name_for_user("test_user")

    assert organization_name == "TestOrg"
    trade_service.redis_conn.get.assert_called_once_with("user:test_user:organization")

@pytest.mark.asyncio
async def test_get_organization_name_for_user_not_found(test_db: Session, mocker):
    mocker.patch.object(TradeService, "redis_conn", autospec=True)
    trade_service = TradeService(test_db)
    trade_service.redis_conn.get.return_value = None

    with pytest.raises(ValueError, match="Organization name not found for user: test_user"):
        await trade_service._get_organization_name_for_user("test_user")

@pytest.mark.asyncio
async def test_get_orders_by_organization_and_user(test_db: Session, mocker):
    mocker.patch.object(TradeService, "get_organization_name_for_user", autospec=True)
    mocker.patch.object(TradeService, "rate_limiter", autospec=True)
    trade_service = TradeService(test_db)
    trade_service.get_organization_name_for_user.return_value = "TestOrg"
    trade_service.rate_limiter.account_rate_limit.return_value = True

    create_test_order(test_db, pseudo_account="test_user")
    create_test_order(test_db, pseudo_account="test_user")

    orders = await trade_service.get_orders_by_organization_and_user("TestOrg", "test_user")

    assert len(orders) == 2
    assert orders[0].pseudo_account == "test_user"

@pytest.mark.asyncio
async def test_get_positions_by_organization_and_user(test_db: Session, mocker):
    mocker.patch.object(TradeService, "get_organization_name_for_user", autospec=True)
    mocker.patch.object(TradeService, "rate_limiter", autospec=True)
    trade_service = TradeService(test_db)
    trade_service.get_organization_name_for_user.return_value = "TestOrg"
    trade_service.rate_limiter.account_rate_limit.return_value = True

    create_test_position(test_db, pseudo_account="test_user")
    create_test_position(test_db, pseudo_account="test_user")

    positions = await trade_service.get_positions_by_organization_and_user("TestOrg", "test_user")

    assert len(positions) == 2
    assert positions[0].pseudo_account == "test_user"

@pytest.mark.asyncio
async def test_get_holdings_by_organization_and_user(test_db: Session, mocker):
    mocker.patch.object(TradeService, "get_organization_name_for_user", autospec=True)
    mocker.patch.object(TradeService, "rate_limiter", autospec=True)
    trade_service = TradeService(test_db)
    trade_service.get_organization_name_for_user.return_value = "TestOrg"
    trade_service.rate_limiter.account_rate_limit.return_value = True

    create_test_holding(test_db, pseudo_account="test_user")
    create_test_holding(test_db, pseudo_account="test_user")

    holdings = await trade_service.get_holdings_by_organization_and_user("TestOrg", "test_user")

    assert len(holdings) == 2
    assert holdings[0].pseudo_account == "test_user"

@pytest.mark.asyncio
async def test_get_margins_by_organization_and_user(test_db: Session, mocker):
    mocker.patch.object(TradeService, "get_organization_name_for_user", autospec=True)
    mocker.patch.object(TradeService, "rate_limiter", autospec=True)
    trade_service = TradeService(test_db)
    trade_service.get_organization_name_for_user.return_value = "TestOrg"
    trade_service.rate_limiter.account_rate_limit.return_value = True

    create_test_margin(test_db, pseudo_account="test_user")
    create_test_margin(test_db, pseudo_account="test_user")

    margins = await trade_service.get_margins_by_organization_and_user("TestOrg", "test_user")

    assert len(margins) == 2
    assert margins[0].pseudo_account == "test_user"

@pytest.mark.asyncio
async def test_get_orders_by_strategy(test_db: Session):
    trade_service = TradeService(test_db)
    create_test_order(test_db, strategy_id="test_strategy_a")
    create_test_order(test_db, strategy_id="test_strategy_a")
    create_test_order(test_db, strategy_id="test_strategy_b")

    orders = await trade_service.get_orders_by_strategy("test_strategy_a")

    assert len(orders) == 2
    assert orders[0].strategy_id == "test_strategy_a"

@pytest.mark.asyncio
async def test_get_positions_by_strategy(test_db: Session):
    trade_service = TradeService(test_db)
    create_test_position(test_db, strategy_id="test_strategy_a")
    create_test_position(test_db, strategy_id="test_strategy_a")
    create_test_position(test_db, strategy_id="test_strategy_b")

    positions = await trade_service.get_positions_by_strategy("test_strategy_a")

    assert len(positions) == 2
    assert positions[0].strategy_id == "test_strategy_a"

@pytest.mark.asyncio
async def test_get_holdings_by_strategy(test_db: Session):
    trade_service = TradeService(test_db)
    create_test_holding(test_db, strategy_id="test_strategy_a")
    create_test_holding(test_db, strategy_id="test_strategy_a")
    create_test_holding(test_db, strategy_id="test_strategy_b")

    holdings = await trade_service.get_holdings_by_strategy("test_strategy_a")

    assert len(holdings) == 2
    assert holdings[0].strategy_id == "test_strategy_a"

@pytest.mark.asyncio
async def test_check_for_conflicting_orders(test_db: Session):
    trade_service = TradeService(test_db)

    # Create a position from strategy_a
    create_test_position(test_db, strategy_id="strategy_a", direction="BUY")

    # Create an order from strategy_b
    order = create_test_order(test_db, strategy_id="strategy_b", trade_type="SELL")

    # Check for conflict - should raise an exception
    with pytest.raises(HTTPException, match="Conflict: Cannot place SELL order when BUY position exists from another strategy"):
        await trade_service._check_for_conflicting_orders(
            order.pseudo_account, order.instrument_key, order.trade_type, order.strategy_id
        )

    # Clean up
    test_db.query(PositionModel).delete()
    test_db.query(OrderModel).delete()
    test_db.commit()

@pytest.mark.asyncio
async def test_handle_holding_to_position_transition_success(test_db: Session):
    trade_service = TradeService(test_db)
    create_test_holding(test_db, pseudo_account="test_user", instrument_key="test_instrument", strategy_id="test_strategy", quantity=100)

    await trade_service._handle_holding_to_position_transition(
        pseudo_account="test_user", instrument_key="test_instrument", quantity=50, strategy_id="test_strategy"
    )

    updated_holding = test_db.query(HoldingModel).filter_by(pseudo_account="test_user", instrument_key="test_instrument", strategy_id="test_strategy").first()
    new_position = test_db.query(PositionModel).filter_by(pseudo_account="test_user", instrument_key="test_instrument", strategy_id="test_strategy").first()

    assert updated_holding.quantity == 50
    assert new_position.net_quantity == -50
    assert new_position.direction == "SELL"

@pytest.mark.asyncio
async def test_handle_holding_to_position_transition_insufficient(test_db: Session):
    trade_service = TradeService(test_db)
    create_test_holding(test_db, pseudo_account="test_user", instrument_key="test_instrument", strategy_id="test_strategy", quantity=100)

    with pytest.raises(HTTPException, match="Insufficient holdings for test_instrument for strategy test_strategy"):
        await trade_service._handle_holding_to_position_transition(
            pseudo_account="test_user", instrument_key="test_instrument", quantity=150, strategy_id="test_strategy"
        )