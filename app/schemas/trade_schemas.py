# trade_service/app/schemas/trade_schemas.py
from pydantic import BaseModel, Field
from typing import Optional
from shared_architecture.enums import Exchange, TradeType, OrderType, ProductType, Variety, Validity

class TradeOrder(BaseModel):
    user_id: str
    symbol: str
    quantity: int = Field(gt=0)
    price: float = Field(gt=0)
    side: TradeType

class AdvancedOrder(BaseModel):
    variety: Variety
    pseudo_account: str
    exchange: Exchange
    symbol: str
    tradeType: TradeType
    orderType: OrderType
    productType: ProductType
    quantity: int = Field(gt=0)
    price: float = Field(gt=0)
    triggerPrice: Optional[float] = Field(default=0.0, ge=0)
    target: Optional[float] = Field(default=0.0, ge=0)
    stoploss: Optional[float] = Field(default=0.0, ge=0)
    trailingStoploss: Optional[float] = Field(default=0.0, ge=0)
    disclosedQuantity: Optional[int] = Field(default=0, ge=0)
    validity: Validity
    amo: Optional[bool] = False
    strategyId: Optional[str] = None
    comments: Optional[str] = None
    publisherId: Optional[str] = None

class ModifyOrder(BaseModel):
    pseudo_account: str
    order_type: Optional[OrderType] = None
    quantity: Optional[int] = Field(default=None, gt=0)
    price: Optional[float] = Field(default=None, gt=0)
    trigger_price: Optional[float] = Field(default=None, ge=0)

class TradeStatus(BaseModel):
    order_id: str
    status: str
    filled_quantity: Optional[int] = None
    average_price: Optional[float] = None