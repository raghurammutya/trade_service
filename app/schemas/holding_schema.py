# trade_service/app/schemas/holding_schema.py
from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class HoldingSchema(BaseModel):
    id: Optional[int] = None
    pseudo_account: Optional[str] = None
    trading_account: Optional[str] = None
    exchange: Optional[str] = None
    symbol: Optional[str] = None
    quantity: Optional[int] = None
    product: Optional[str] = None
    isin: Optional[str] = None
    collateral_qty: Optional[int] = None
    t1_qty: Optional[int] = None
    collateral_type: Optional[str] = None
    pnl: Optional[float] = None
    haircut: Optional[float] = None
    avg_price: Optional[float] = None
    instrument_token: Optional[int] = None
    stock_broker: Optional[str] = None
    platform: Optional[str] = None
    ltp: Optional[float] = None
    currentValue: Optional[float] = None
    totalQty: Optional[int] = None
    timestamp: Optional[datetime] = None
    instrument_key: Optional[str] = None
    strategy_id: Optional[str] = None
    source_strategy_id: Optional[str] = None

    class Config:
        from_attributes = True