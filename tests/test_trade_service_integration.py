# trade_service/tests/test_trade_service_integration.py
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.models.order_model import OrderModel
from app.schemas.trade_schemas import TradeOrder
from app.core.config import settings

@pytest.mark.asyncio
async def test_execute_trade_endpoint