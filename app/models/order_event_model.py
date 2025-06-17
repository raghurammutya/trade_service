# trade_service/app/models/order_event_model.py
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class OrderEventModel(Base):
    __tablename__ = "order_events"
    __table_args__ = {'schema': 'tradingdb'}  # Add schema
    
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer)  # Remove ForeignKey for now
    event_type = Column(String)  # Change from Enum to String
    timestamp = Column(DateTime, default=datetime.utcnow)
    details = Column(String, nullable=True)