# trade_service/app/schemas/order_schema.py
from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class OrderSchema(BaseModel):
    id: Optional[int] = None
    amo: Optional[bool] = None
    average_price: Optional[float] = None
    client_id: Optional[str] = None
    disclosed_quantity: Optional[int] = None
    exchange: Optional[str] = None
    exchange_order_id: Optional[str] = None
    exchange_time: Optional[datetime] = None
    filled_quantity: Optional[int] = None
    independent_exchange: Optional[str] = None
    independent_symbol: Optional[str] = None
    modified_time: Optional[datetime] = None
    nest_request_id: Optional[str] = None
    order_type: Optional[str] = None
    parent_order_id: Optional[int] = None
    pending_quantity: Optional[int] = None
    platform: Optional[str] = None
    platform_time: Optional[datetime] = None
    price: Optional[float] = None
    pseudo_account: Optional[str] = None
    publisher_id: Optional[str] = None
    status: Optional[str] = None
    status_message: Optional[str] = None
    stock_broker: Optional[str] = None
    symbol: Optional[str] = None
    trade_type: Optional[str] = None
    trading_account: Optional[str] = None
    trigger_price: Optional[float] = None
    validity: Optional[str] = None
    variety: Optional[str] = None
    timestamp: Optional[datetime] = None
    instrument_key: Optional[str] = None
    strategy_id: Optional[str] = None
    transition_type: Optional[str] = None

    class Config:
        orm_mode = True