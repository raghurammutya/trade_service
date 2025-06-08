# trade_service/app/models/margin_model.py
from sqlalchemy import UniqueConstraint, Column, Integer, Float, String, Boolean, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class MarginModel(Base):
    __tablename__ = 'margins'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    adhoc = Column(Float)
    available = Column(Float)
    category = Column(String)
    collateral = Column(Float)
    exposure = Column(Float)
    funds = Column(Float)
    net = Column(Float)
    payin = Column(Float)
    payout = Column(Float)
    pseudo_account = Column(String)
    realised_mtm = Column(Float)
    span = Column(Float)
    stock_broker = Column(String)
    total = Column(Float)
    trading_account = Column(String)
    unrealised_mtm = Column(Float)
    utilized = Column(Float)
    active = Column(Boolean, default=True)
    margin_date = Column(DateTime)
    instrument_key = Column(String, ForeignKey('symbols.instrument_key'))
    __table_args__ = (UniqueConstraint('pseudo_account', 'category', 'margin_date'),)