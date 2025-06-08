# trade_service/app/models/holding_model.py
from sqlalchemy import Column, Integer, Float, String, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class HoldingModel(Base):
    __tablename__ = 'holdings'
    id = Column(Integer, primary_key=True)
    pseudo_account = Column(String)
    trading_account = Column(String)
    exchange = Column(String)
    symbol = Column(String)
    quantity = Column(Integer)
    product = Column(String)
    isin = Column(String)
    collateral_qty = Column(Integer)
    t1_qty = Column(Integer)
    collateral_type = Column(String)
    pnl = Column(Float)
    haircut = Column(Float)
    avg_price = Column(Float)
    instrument_token = Column(Integer)
    stock_broker = Column(String)
    platform = Column(String)
    ltp = Column(Float)
    currentValue = Column(Float)
    totalQty = Column(Integer)
    timestamp = Column(DateTime, default=datetime.utcnow)
    instrument_key = Column(String, ForeignKey('symbols.instrument_key'))
    strategy_id = Column(String)
    source_strategy_id = Column(String, nullable=True)