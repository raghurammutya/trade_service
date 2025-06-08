# trade_service/app/schemas/margin_schema.py
from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class MarginSchema(BaseModel):
    id: Optional[int] = None
    user_id: Optional[int] = None
    adhoc: Optional[float] = None
    available: Optional[float] = None
    category: Optional[str] = None
    collateral: Optional[float] = None
    exposure: Optional[float] = None
    funds: Optional[float] = None
    net: Optional[float] = None
    payin: Optional[float] = None
    payout: Optional[float] = None
    pseudo_account: Optional[str] = None
    realised_mtm: Optional[float] = None
    span: Optional[float] = None
    stock_broker: Optional[str] = None
    total: Optional[float] = None
    trading_account: Optional[str] = None
    unrealised_mtm: Optional[float] = None
    utilized: Optional[float] = None
    active: Optional[bool] = True
    margin_date: Optional[datetime] = None
    instrument_key: Optional[str] = None

    class Config:
        orm_mode = True