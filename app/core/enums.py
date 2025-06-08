# trade_service/app/core/enums.py
import enum

class Exchange(str, enum.Enum):
    NSE = "NSE"
    BSE = "BSE"
    MCX = "MCX"
    NFO = "NFO"
    CDS = "CDS"
    BFO = "BFO"

class TradeType(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"

class OrderType(str, enum.Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_LOSS_MARKET = "SL-M"
    STOP_LOSS_LIMIT = "SL"

class ProductType(str, enum.Enum):
    CNC = "CNC"  # Cash and Carry
    NRML = "NRML" # Normal
    MIS = "MIS"  # Margin Intraday Squareoff
    CO = "CO"   # Cover Order
    BO = "BO"   # Bracket Order

class Variety(str, enum.Enum):
    REGULAR = "REGULAR"
    CO = "CO"
    BO = "BO"
    AMO = "AMO"

class Validity(str, enum.Enum):
    DAY = "DAY"
    IOC = "IOC"

class OrderTransitionType(str, enum.Enum):
    NONE = "NONE"
    POSITION_TO_HOLDING = "POSITION_TO_HOLDING"
    HOLDING_TO_POSITION = "HOLDING_TO_POSITION"

class OrderEvent(str, enum.Enum):
    ORDER_PLACED = "ORDER_PLACED"
    ORDER_ACCEPTED = "ORDER_ACCEPTED"
    ORDER_PARTIALLY_FILLED = "ORDER_PARTIALLY_FILLED"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_REJECTED = "ORDER_REJECTED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    ORDER_MODIFIED = "ORDER_MODIFIED" 