# trade_service/app/schemas/position_schema.py
from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class PositionSchema(BaseModel):
    id: Optional[int] = None
    account_id: Optional[str] = None
    atPnl: Optional[float] = None
    buy_avg_price: Optional[float] = None
    buy_quantity: Optional[int] = None
    buy_value: Optional[float] = None
    category: Optional[str] = None
    direction: Optional[str] = None
    exchange: Optional[str] = None
    independent_exchange: Optional[str] = None
    independent_symbol: Optional[str] = None
    ltp: Optional[float] = None
    mtm: Optional[float] = None
    multiplier: Optional[int] = None
    net_quantity: Optional[int] = None
    net_value: Optional[float] = None
    overnight_quantity: Optional[int] = None
    platform: Optional[str] = None
    pnl: Optional[float] = None
    pseudo_account: Optional[str] = None
    realised_pnl: Optional[float] = None
    sell_avg_price: Optional[float] = None
    sell_quantity: Optional[int] = None
    sell_value: Optional[float] = None
    state: Optional[str] = None
    stock_broker: Optional[str] = None
    symbol: Optional[str] = None
    trading_account: Optional[str] = None
    type: Optional[str] = None
    unrealised_pnl: Optional[float] = None
    timestamp: Optional[datetime] = None
    instrument_key: Optional[str] = None
    strategy_id: Optional[str] = None
    source_strategy_id: Optional[str] = None

    class Config:
        from_attributes = True