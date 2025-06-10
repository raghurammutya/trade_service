# trade_service/app/schemas/order_event_schema.py
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from shared_architecture.enums import OrderEvent

class OrderEventSchema(BaseModel):
    id: Optional[int] = None
    order_id: int
    event_type: OrderEvent
    timestamp: datetime
    details: Optional[str] = None

    class Config:
        from_attributes = True