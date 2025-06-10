# trade_service/app/api/endpoints/trade_endpoints.py
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from app.schemas.trade_schemas import TradeOrder, TradeStatus, AdvancedOrder, ModifyOrder
from app.services.trade_service import TradeService
from shared_architecture.db import get_db
from sqlalchemy.orm import Session
from typing import Optional,List
from shared_architecture.enums import Exchange, TradeType, OrderType, ProductType, Variety, Validity
from shared_architecture.schemas.margin_schema import MarginSchema
from shared_architecture.schemas.position_schema import PositionSchema
from shared_architecture.schemas.holding_schema import HoldingSchema
from shared_architecture.schemas.order_schema import OrderSchema
from shared_architecture.schemas.trade_schemas import TradeOrder, TradeStatus
router = APIRouter()

@router.post("/execute", response_model=TradeStatus)
async def execute_trade(trade_order: TradeOrder, organization_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    try:
        trade_service = TradeService(db)
        return await trade_service.execute_trade_order(trade_order, organization_id, background_tasks)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/status/{order_id}", response_model=TradeStatus)
async def get_trade_status(order_id: str, organization_id: str, db: Session = Depends(get_db)):
    try:
        trade_service = TradeService(db)
        return await trade_service.get_trade_status(order_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/fetch_all_users")
async def fetch_all_users(organization_id: str, db: Session = Depends(get_db)):
    try:
        trade_service = TradeService(db)
        return await trade_service.fetch_all_trading_accounts()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/fetch_and_store/{pseudo_account}")
async def fetch_and_store(pseudo_account: str, organization_id: str, db: Session = Depends(get_db)):
    try:
        trade_service = TradeService(db)
        await trade_service.fetch_and_store_data(pseudo_account, organization_id)
        return {"message": f"Data fetched and stored for {pseudo_account}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/regular_order")
async def place_regular_order(
    pseudo_account: str,
    organization_id: str,
    exchange: Exchange,
    symbol: str,
    tradeType: TradeType,
    orderType: OrderType,
    productType: ProductType,
    quantity: int,
    price: float,
    background_tasks: BackgroundTasks,
    triggerPrice: Optional[float] = 0.0,
    db: Session = Depends(get_db),
    strategy_id: Optional[str] = None,
):
    try:
        trade_service = TradeService(db)
        return await trade_service.place_regular_order(
            pseudo_account,
            exchange.value,
            symbol,
            tradeType.value,
            orderType.value,
            productType.value,
            quantity,
            price,
            triggerPrice or 0.0,
            strategy_id,
            organization_id,
            background_tasks,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/cover_order")
async def place_cover_order(
    pseudo_account: str,
    exchange: Exchange,
    symbol: str,
    tradeType: TradeType,
    orderType: OrderType,
    quantity: int,
    price: float,
    triggerPrice: float,
    organization_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    strategy_id: Optional[str] = None,
):
    try:
        trade_service = TradeService(db)
        return await trade_service.place_cover_order(
            pseudo_account,
            exchange.value,
            symbol,
            tradeType.value,
            orderType.value,
            quantity,
            price,
            triggerPrice,
            strategy_id,      
            organization_id, 
            background_tasks,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/bracket_order")
async def place_bracket_order(
    pseudo_account: str,
    organization_id: str,
    exchange: Exchange,
    symbol: str,
    tradeType: TradeType,
    orderType: OrderType,
    quantity: int,
    price: float,
    triggerPrice: float,
    target: float,
    stoploss: float,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    trailingStoploss: Optional[float] = 0.0,
    strategy_id: Optional[str] = None, 

):
    try:
        trade_service = TradeService(db)
        return await trade_service.place_bracket_order(
            pseudo_account,
            exchange.value,
            symbol,
            tradeType.value,
            orderType.value,
            quantity,
            price,
            triggerPrice,
            target,
            stoploss,
            trailingStoploss or 0.0,  # Handle None value
            strategy_id,              # Add missing strategy_id
            organization_id,          # Now in correct position
            background_tasks,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/advanced_order")
async def place_advanced_order(
    order: AdvancedOrder,
    organization_id: str,
    background_tasks: BackgroundTasks, db: Session = Depends(get_db),
):
    try:
        trade_service = TradeService(db)
        return await trade_service.place_advanced_order(
        order.variety.value,
        order.pseudo_account,
        order.exchange.value,
        order.symbol,
        order.tradeType.value,
        order.orderType.value,
        order.productType.value,
        order.quantity,
        order.price,
        order.triggerPrice or 0.0,          # ✅ Handle None
        order.target or 0.0,                # ✅ Handle None
        order.stoploss or 0.0,              # ✅ Handle None
        order.trailingStoploss or 0.0,      # ✅ Handle None
        order.disclosedQuantity or 0,       # ✅ Handle None
        order.validity.value,
        order.amo or False,                 # ✅ Handle None
        order.strategyId or "N/A",          # ✅ Handle None
        order.comments or "",               # ✅ Handle None
        order.publisherId or "",            # ✅ Handle None
        organization_id,
        background_tasks,
    )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/cancel_order/{platform_id}")
async def cancel_order(
    pseudo_account: str,
    platform_id: str,
    organization_id: str,
    background_tasks: BackgroundTasks, db: Session = Depends(get_db),
):
    try:
        trade_service = TradeService(db)
        return await trade_service.cancel_order_by_platform_id(
            pseudo_account, platform_id, organization_id, background_tasks
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/cancel_child_orders/{platform_id}")
async def cancel_child_orders(
    pseudo_account: str,
    platform_id: str,
    organization_id: str,
    background_tasks: BackgroundTasks, db: Session = Depends(get_db),
):
    try:
        trade_service = TradeService(db)
        return await trade_service.cancel_child_orders_by_platform_id(
            pseudo_account, platform_id, organization_id, background_tasks
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/modify_order/{platform_id}")
async def modify_order(
    platform_id: str,
    order: ModifyOrder,
    organization_id: str,
    background_tasks: BackgroundTasks, db: Session = Depends(get_db),
):
    try:
        trade_service = TradeService(db)
        return await trade_service.modify_order_by_platform_id(
            order.pseudo_account,
            platform_id,
            order.order_type,
            order.quantity,
            order.price,
            order.trigger_price,
            organization_id,
            background_tasks,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/square_off_position")
async def square_off_position(
    pseudo_account: str,
    position_category: str,
    position_type: str,
    exchange: str,
    symbol: str,
    organization_id: str,
    background_tasks: BackgroundTasks, db: Session = Depends(get_db),
):
    try:
        trade_service = TradeService(db)
        return await trade_service.square_off_position(
            pseudo_account,
            position_category,
            position_type,
            exchange,
            symbol,
            organization_id,
            background_tasks,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/square_off_portfolio")
async def square_off_portfolio(

    pseudo_account: str,
    position_category: str,
    organization_id: str,
    background_tasks: BackgroundTasks, db: Session = Depends(get_db),
):
    try:
        trade_service = TradeService(db)
        return await trade_service.square_off_portfolio(
            pseudo_account, position_category, organization_id, background_tasks
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/cancel_all_orders")
async def cancel_all_orders(
    pseudo_account: str,
    organization_id: str,
    background_tasks: BackgroundTasks, db: Session = Depends(get_db),
):
    try:
        trade_service = TradeService(db)
        return await trade_service.cancel_all_orders(
            pseudo_account, organization_id, background_tasks
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@router.get("/orders/organization/{organization_name}/user/{user_id}", response_model=List[OrderSchema])
async def get_orders_by_organization_and_user(organization_name: str, user_id: str, db: Session = Depends(get_db)):
    try:
        trade_service = TradeService(db)
        return await trade_service.get_orders_by_organization_and_user(organization_name, user_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/positions/organization/{organization_name}/user/{user_id}", response_model=List[PositionSchema])
async def get_positions_by_organization_and_user(organization_name: str, user_id: str, db: Session = Depends(get_db)):
    try:
        trade_service = TradeService(db)
        return await trade_service.get_positions_by_organization_and_user(organization_name, user_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/holdings/organization/{organization_name}/user/{user_id}", response_model=List[HoldingSchema])
async def get_holdings_by_organization_and_user(organization_name: str, user_id: str, db: Session = Depends(get_db)):
    try:
        trade_service = TradeService(db)
        return await trade_service.get_holdings_by_organization_and_user(organization_name, user_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/margins/organization/{organization_name}/user/{user_id}", response_model=List[MarginSchema])
async def get_margins_by_organization_and_user(organization_name: str, user_id: str, db: Session = Depends(get_db)):
    try:
        trade_service = TradeService(db)
        return await trade_service.get_margins_by_organization_and_user(organization_name, user_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/orders/strategy/{strategy_name}", response_model=List[OrderSchema])
async def get_orders_by_strategy(strategy_name: str, db: Session = Depends(get_db)):
    try:
        trade_service = TradeService(db)
        return await trade_service.get_orders_by_strategy(strategy_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/positions/strategy/{strategy_name}", response_model=List[PositionSchema])
async def get_positions_by_strategy(strategy_name: str, db: Session = Depends(get_db)):
    try:
        trade_service = TradeService(db)
        return await trade_service.get_positions_by_strategy(strategy_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/holdings/strategy/{strategy_name}", response_model=List[HoldingSchema])
async def get_holdings_by_strategy(strategy_name: str, db: Session = Depends(get_db)):
    try:
        trade_service = TradeService(db)
        return await trade_service.get_holdings_by_strategy(strategy_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
