# Fixed simplified trade endpoints with proper text() wrappers
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from typing import List, Optional
import asyncio
from sqlalchemy.orm import Session
from sqlalchemy import text  # Import text for raw SQL
from shared_architecture.db import get_db

# Simple response models
from pydantic import BaseModel

class SimpleOrder(BaseModel):
    id: Optional[int] = None
    pseudo_account: Optional[str] = None
    organization_id: Optional[str] = None
    exchange: Optional[str] = None
    symbol: Optional[str] = None
    trade_type: Optional[str] = None
    quantity: Optional[int] = None
    price: Optional[float] = None
    status: Optional[str] = None
    strategy_id: Optional[str] = None

class SimplePosition(BaseModel):
    id: Optional[int] = None
    pseudo_account: Optional[str] = None
    organization_id: Optional[str] = None
    symbol: Optional[str] = None
    quantity: Optional[int] = None
    net_quantity: Optional[int] = None
    direction: Optional[str] = None

class SimpleHolding(BaseModel):
    id: Optional[int] = None
    pseudo_account: Optional[str] = None
    organization_id: Optional[str] = None
    symbol: Optional[str] = None
    quantity: Optional[int] = None
    avg_price: Optional[float] = None

class SimpleMargin(BaseModel):
    id: Optional[int] = None
    pseudo_account: Optional[str] = None
    organization_id: Optional[str] = None
    category: Optional[str] = None
    available: Optional[float] = None
    total: Optional[float] = None

router = APIRouter()

@router.get("/orders/organization/{organization_name}/user/{user_id}", response_model=List[SimpleOrder])
async def get_orders_by_organization_and_user_simple(
    organization_name: str, 
    user_id: str, 
    db: Session = Depends(get_db)
):
    """Get orders for a user in an organization - simplified version"""
    try:
        # Use text() wrapper for raw SQL
        result = db.execute(
            text("SELECT id, pseudo_account, organization_id, exchange, symbol, trade_type, quantity, price, status, strategy_id "
                 "FROM tradingdb.orders WHERE organization_id = :org AND pseudo_account = :user"),
            {"org": organization_name, "user": user_id}
        )
        
        orders = []
        for row in result:
            orders.append(SimpleOrder(
                id=row[0],
                pseudo_account=row[1], 
                organization_id=row[2],
                exchange=row[3],
                symbol=row[4],
                trade_type=row[5],
                quantity=row[6],
                price=row[7],
                status=row[8],
                strategy_id=row[9]
            ))
        
        return orders
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@router.get("/positions/organization/{organization_name}/user/{user_id}", response_model=List[SimplePosition])
async def get_positions_by_organization_and_user_simple(
    organization_name: str, 
    user_id: str, 
    db: Session = Depends(get_db)
):
    """Get positions for a user in an organization - simplified version"""
    try:
        result = db.execute(
            text("SELECT id, pseudo_account, organization_id, symbol, quantity, net_quantity, direction "
                 "FROM tradingdb.positions WHERE organization_id = :org AND pseudo_account = :user"),
            {"org": organization_name, "user": user_id}
        )
        
        positions = []
        for row in result:
            positions.append(SimplePosition(
                id=row[0],
                pseudo_account=row[1],
                organization_id=row[2], 
                symbol=row[3],
                quantity=row[4],
                net_quantity=row[5],
                direction=row[6]
            ))
        
        return positions
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@router.get("/holdings/organization/{organization_name}/user/{user_id}", response_model=List[SimpleHolding])
async def get_holdings_by_organization_and_user_simple(
    organization_name: str, 
    user_id: str, 
    db: Session = Depends(get_db)
):
    """Get holdings for a user in an organization - simplified version"""
    try:
        result = db.execute(
            text("SELECT id, pseudo_account, organization_id, symbol, quantity, avg_price "
                 "FROM tradingdb.holdings WHERE organization_id = :org AND pseudo_account = :user"),
            {"org": organization_name, "user": user_id}
        )
        
        holdings = []
        for row in result:
            holdings.append(SimpleHolding(
                id=row[0],
                pseudo_account=row[1],
                organization_id=row[2],
                symbol=row[3], 
                quantity=row[4],
                avg_price=row[5]
            ))
        
        return holdings
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@router.get("/margins/organization/{organization_name}/user/{user_id}", response_model=List[SimpleMargin])
async def get_margins_by_organization_and_user_simple(
    organization_name: str, 
    user_id: str, 
    db: Session = Depends(get_db)
):
    """Get margins for a user in an organization - simplified version"""
    try:
        result = db.execute(
            text("SELECT id, pseudo_account, organization_id, category, available, total "
                 "FROM tradingdb.margins WHERE organization_id = :org AND pseudo_account = :user"),
            {"org": organization_name, "user": user_id}
        )
        
        margins = []
        for row in result:
            margins.append(SimpleMargin(
                id=row[0],
                pseudo_account=row[1],
                organization_id=row[2],
                category=row[3],
                available=row[4], 
                total=row[5]
            ))
        
        return margins
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@router.post("/regular_order_simple")
async def place_regular_order_simple(
    pseudo_account: str = Query(...),
    organization_id: str = Query(...),
    exchange: str = Query(...),
    symbol: str = Query(...),
    tradeType: str = Query(...),
    orderType: str = Query(...),
    productType: str = Query(...),
    quantity: int = Query(...),
    price: float = Query(...),
    triggerPrice: float = Query(0.0),
    strategy_id: str = Query("default"),
    db: Session = Depends(get_db)
):
    """Place a regular order - simplified version"""
    try:
        # Insert order directly with SQL using text() wrapper
        result = db.execute(
            text("""INSERT INTO tradingdb.orders 
                    (pseudo_account, organization_id, exchange, symbol, trade_type, order_type, 
                     product_type, quantity, price, trigger_price, strategy_id, status, 
                     platform_time, variety, instrument_key) 
                    VALUES (:pseudo_account, :org_id, :exchange, :symbol, :trade_type, :order_type,
                            :product_type, :quantity, :price, :trigger_price, :strategy_id, 'PENDING',
                            NOW(), 'REGULAR', :instrument_key)
                    RETURNING id"""),
            {
                "pseudo_account": pseudo_account,
                "org_id": organization_id, 
                "exchange": exchange,
                "symbol": symbol,
                "trade_type": tradeType,
                "order_type": orderType,
                "product_type": productType,
                "quantity": quantity,
                "price": price,
                "trigger_price": triggerPrice,
                "strategy_id": strategy_id,
                "instrument_key": f"{exchange}@{symbol}@{productType}@@@"
            }
        )
        
        order_id = result.fetchone()[0]
        db.commit()
        
        return {
            "message": "Order placed successfully",
            "order_id": order_id,
            "status": "PENDING",
            "details": {
                "pseudo_account": pseudo_account,
                "symbol": symbol,
                "quantity": quantity,
                "price": price,
                "trade_type": tradeType
            }
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Order placement failed: {str(e)}")

# Add a test endpoint to verify the service is working
@router.get("/test")
async def test_endpoint():
    """Simple test endpoint"""
    return {
        "status": "ok",
        "message": "Simplified trade endpoints are working!",
        "timestamp": "2025-06-10",
        "available_endpoints": [
            "GET /trades/simple/orders/organization/{org}/user/{user}",
            "GET /trades/simple/positions/organization/{org}/user/{user}",
            "GET /trades/simple/holdings/organization/{org}/user/{user}",
            "GET /trades/simple/margins/organization/{org}/user/{user}",
            "POST /trades/simple/regular_order_simple"
        ]
    }
