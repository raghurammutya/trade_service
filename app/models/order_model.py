# trade_service/app/models/order_model.py
from sqlalchemy import Column, Integer, Float, String, Boolean, DateTime, ForeignKey, Enum
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime
import enum
from sqlalchemy.orm import relationship

Base = declarative_base()

class OrderModel(Base):
    __tablename__ = 'orders'
    id = Column(Integer, primary_key=True)
    amo = Column(Boolean)
    average_price = Column(Float)
    client_id = Column(String)
    disclosed_quantity = Column(Integer)
    exchange = Column(String)
    exchange_order_id = Column(String)
    exchange_time = Column(DateTime)
    filled_quantity = Column(Integer)
    independent_exchange = Column(String, nullable=True)
    independent_symbol = Column(String, nullable=True)
    modified_time = Column(DateTime, nullable=True)
    nest_request_id = Column(String, nullable=True)
    order_type = Column(String)
    parent_order_id = Column(Integer, nullable=True)
    pending_quantity = Column(Integer)
    platform = Column(String)
    platform_time = Column(DateTime)
    price = Column(Float)
    pseudo_account = Column(String)
    publisher_id = Column(String, nullable=True)
    status = Column(String)
    status_message = Column(String, nullable=True)
    stock_broker = Column(String)
    symbol = Column(String)
    trade_type = Column(String)
    trading_account = Column(String)
    trigger_price = Column(Float, nullable=True)
    validity = Column(String)
    variety = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)
    instrument_key = Column(String, ForeignKey('symbols.instrument_key'))
    strategy_id = Column(String)
    transition_type = Column(Enum('OrderTransitionType'), default='NONE')
    events = relationship("OrderEventModel", backref="order", cascade="all, delete-orphan")  # NEW: Relationship