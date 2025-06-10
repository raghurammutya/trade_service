# trade_service/app/models/order_event_model.py
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime
import enum
from shared_architecture.enums import OrderEvent

Base = declarative_base()

class OrderEventModel(Base):
    __tablename__ = "order_events"
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    event_type = Column(Enum(OrderEvent))
    timestamp = Column(DateTime, default=datetime.utcnow)
    details = Column(String, nullable=True)  # Store any relevant event details (e.g., rejection reason)