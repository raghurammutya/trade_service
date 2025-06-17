# trade_service/app/models/order_model.py
from sqlalchemy import Column, Integer, Float, String, Boolean, DateTime
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class OrderModel(Base):
    __tablename__ = 'orders'
    __table_args__ = {'schema': 'tradingdb'}
    
    id = Column(Integer, primary_key=True)
    amo = Column(Boolean)
    average_price = Column(Float)
    client_id = Column(String)
    disclosed_quantity = Column(Integer)
    exchange = Column(String)
    exchange_order_id = Column(String)
    exchange_time = Column(DateTime(timezone=True))
    filled_quantity = Column(Integer)
    independent_exchange = Column(String, nullable=True)
    independent_symbol = Column(String, nullable=True)
    modified_time = Column(DateTime(timezone=True), nullable=True)
    nest_request_id = Column(String, nullable=True)
    order_type = Column(String)
    parent_order_id = Column(Integer, nullable=True)
    pending_quantity = Column(Integer)
    platform = Column(String)
    platform_time = Column(DateTime(timezone=True))
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
    timestamp = Column(DateTime(timezone=True), default=datetime.utcnow)
    instrument_key = Column(String)
    strategy_id = Column(String)
    transition_type = Column(String, default='NONE')
    
    # Add missing columns
    product_type = Column(String)
    quantity = Column(Integer)
    target = Column(Float, nullable=True)
    stoploss = Column(Float, nullable=True)
    trailing_stoploss = Column(Float, nullable=True)
    position_category = Column(String, nullable=True)
    position_type = Column(String, nullable=True)
    comments = Column(String, nullable=True)
    
    # Remove the relationship for now - we'll add it back later
    # events = relationship("OrderEventModel", backref="order", cascade="all, delete-orphan")
    
    def to_dict(self):
        """Convert OrderModel instance to dictionary for Celery serialization."""
        return {
            'id': self.id,
            'pseudo_account': self.pseudo_account,
            'exchange': self.exchange,
            'symbol': self.symbol,
            'trade_type': self.trade_type,
            'order_type': self.order_type,
            'product_type': self.product_type,
            'quantity': self.quantity,
            'price': self.price,
            'trigger_price': self.trigger_price,
            'strategy_id': self.strategy_id,
            'instrument_key': self.instrument_key,
            'status': self.status,
            'variety': self.variety,
            'platform_time': self.platform_time.isoformat() if self.platform_time is not None else None,
            'target': self.target,
            'stoploss': self.stoploss,
            'trailing_stoploss': self.trailing_stoploss,
            'disclosed_quantity': self.disclosed_quantity,
            'validity': self.validity,
            'amo': self.amo,
            'comments': self.comments,
            'publisher_id': self.publisher_id,
            'transition_type': self.transition_type,
            'platform': self.platform,
            'position_category': self.position_category,
            'position_type': self.position_type
        }