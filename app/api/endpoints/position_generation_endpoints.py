"""
Position and Holdings Generation API Endpoints

Provides endpoints to regenerate positions and holdings from order data.
This is crucial for historical data reconstruction and reducing AutoTrader API calls.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from typing import Optional
from datetime import date, datetime
from sqlalchemy.orm import Session

from shared_architecture.db.session import get_db
from app.services.position_holdings_generator import PositionHoldingsGenerator

router = APIRouter(prefix="/position-generation", tags=["position_generation"])

@router.post("/regenerate")
async def regenerate_positions_and_holdings(
    pseudo_account: str = Query(..., description="Account to regenerate data for"),
    target_date: Optional[str] = Query(None, description="Target date (YYYY-MM-DD), default: today"),
    include_intraday: bool = Query(True, description="Include intraday positions"),
    db: Session = Depends(get_db)
):
    """
    Regenerate positions and holdings from order data for a specific account and date
    
    **Use Cases:**
    - Historical data reconstruction when AutoTrader data unavailable
    - Daily position/holdings calculation to reduce API calls
    - Data validation and reconciliation
    - End-of-day conversion of equity positions to holdings
    
    **Business Logic:**
    - Processes all completed orders chronologically
    - Uses FIFO method for realized PnL calculation
    - Converts equity/bond positions to holdings
    - Handles derivatives as positions only
    - Updates database with calculated values
    
    **Returns:**
    - Summary of positions and holdings generated
    - Statistics on orders processed
    - Database update counts
    """
    
    try:
        # Parse target date
        target_date_obj = None
        if target_date:
            try:
                target_date_obj = datetime.strptime(target_date, "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
        
        # Initialize generator
        generator = PositionHoldingsGenerator(db)
        
        # Regenerate data
        result = generator.regenerate_positions_and_holdings(
            pseudo_account=pseudo_account,
            target_date=target_date_obj,
            include_intraday=include_intraday
        )
        
        return {
            "status": "success",
            "message": f"Successfully regenerated positions and holdings for {pseudo_account}",
            "data": result
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to regenerate data: {str(e)}")

@router.post("/regenerate-range")
async def regenerate_for_date_range(
    pseudo_account: str = Query(..., description="Account to regenerate data for"),
    start_date: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="End date (YYYY-MM-DD)"),
    db: Session = Depends(get_db)
):
    """
    Regenerate positions and holdings for a date range
    
    **Use Cases:**
    - Bulk historical data reconstruction
    - Monthly/quarterly data recalculation
    - Data migration and validation
    
    **Warning:** Large date ranges may take significant time to process
    """
    
    try:
        # Parse dates
        try:
            start_date_obj = datetime.strptime(start_date, "%Y-%m-%d").date()
            end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
        
        if start_date_obj > end_date_obj:
            raise HTTPException(status_code=400, detail="Start date must be before end date")
        
        # Check date range size
        date_diff = (end_date_obj - start_date_obj).days
        if date_diff > 90:  # Limit to 90 days
            raise HTTPException(status_code=400, detail="Date range too large. Maximum 90 days allowed")
        
        # Initialize generator
        generator = PositionHoldingsGenerator(db)
        
        # Regenerate data for range
        result = generator.regenerate_for_date_range(
            pseudo_account=pseudo_account,
            start_date=start_date_obj,
            end_date=end_date_obj
        )
        
        return {
            "status": "success",
            "message": f"Successfully processed date range {start_date} to {end_date}",
            "data": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to regenerate range: {str(e)}")

@router.get("/validate")
async def validate_generated_data(
    pseudo_account: str = Query(..., description="Account to validate"),
    target_date: Optional[str] = Query(None, description="Target date (YYYY-MM-DD), default: today"),
    db: Session = Depends(get_db)
):
    """
    Validate generated positions and holdings against order data
    
    **Returns:**
    - Consistency check results
    - Discrepancies found
    - Data quality metrics
    """
    
    try:
        # Parse target date
        target_date_obj = None
        if target_date:
            try:
                target_date_obj = datetime.strptime(target_date, "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
        
        # Initialize generator
        generator = PositionHoldingsGenerator(db)
        
        # Get orders for validation
        orders = generator._get_orders_for_account(pseudo_account, target_date_obj or date.today())
        
        # Calculate expected positions and holdings
        expected_positions = generator._calculate_positions_from_orders(orders, target_date_obj or date.today(), True)
        expected_holdings = generator._calculate_holdings_from_orders(orders, target_date_obj or date.today())
        
        # Get current database positions and holdings
        from shared_architecture.db.models.position_model import PositionModel
        from shared_architecture.db.models.holding_model import HoldingModel
        
        current_positions = db.query(PositionModel).filter_by(pseudo_account=pseudo_account).all()
        current_holdings = db.query(HoldingModel).filter_by(pseudo_account=pseudo_account).all()
        
        # Compare and find discrepancies
        position_discrepancies = []
        holding_discrepancies = []
        
        # Check positions
        for pos in current_positions:
            symbol = pos.symbol
            if symbol in expected_positions:
                expected = expected_positions[symbol]
                if abs(pos.net_quantity - expected.get('net_quantity', 0)) > 0.001:
                    position_discrepancies.append({
                        "symbol": symbol,
                        "field": "net_quantity",
                        "current": pos.net_quantity,
                        "expected": expected.get('net_quantity', 0),
                        "difference": pos.net_quantity - expected.get('net_quantity', 0)
                    })
        
        # Check holdings
        for holding in current_holdings:
            symbol = holding.symbol
            if symbol in expected_holdings:
                expected = expected_holdings[symbol]
                if abs(holding.quantity - expected.get('quantity', 0)) > 0.001:
                    holding_discrepancies.append({
                        "symbol": symbol,
                        "field": "quantity",
                        "current": holding.quantity,
                        "expected": expected.get('quantity', 0),
                        "difference": holding.quantity - expected.get('quantity', 0)
                    })
        
        validation_result = {
            "pseudo_account": pseudo_account,
            "validation_date": (target_date_obj or date.today()).isoformat(),
            "orders_analyzed": len(orders),
            "current_positions": len(current_positions),
            "expected_positions": len(expected_positions),
            "current_holdings": len(current_holdings),
            "expected_holdings": len(expected_holdings),
            "position_discrepancies": position_discrepancies,
            "holding_discrepancies": holding_discrepancies,
            "validation_status": "PASS" if not position_discrepancies and not holding_discrepancies else "FAIL",
            "total_discrepancies": len(position_discrepancies) + len(holding_discrepancies)
        }
        
        return {
            "status": "success",
            "data": validation_result
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to validate data: {str(e)}")

@router.get("/preview")
async def preview_regeneration(
    pseudo_account: str = Query(..., description="Account to preview"),
    target_date: Optional[str] = Query(None, description="Target date (YYYY-MM-DD), default: today"),
    include_intraday: bool = Query(True, description="Include intraday positions"),
    db: Session = Depends(get_db)
):
    """
    Preview what positions and holdings would be generated without updating database
    
    **Use Cases:**
    - Data validation before regeneration
    - Understanding impact of regeneration
    - Debugging position calculation logic
    """
    
    try:
        # Parse target date
        target_date_obj = None
        if target_date:
            try:
                target_date_obj = datetime.strptime(target_date, "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
        
        # Initialize generator
        generator = PositionHoldingsGenerator(db)
        
        # Get orders for preview
        orders = generator._get_orders_for_account(pseudo_account, target_date_obj or date.today())
        
        # Calculate positions and holdings without DB update
        preview_positions = generator._calculate_positions_from_orders(orders, target_date_obj or date.today(), include_intraday)
        preview_holdings = generator._calculate_holdings_from_orders(orders, target_date_obj or date.today())
        
        # Create summary
        preview_result = {
            "pseudo_account": pseudo_account,
            "target_date": (target_date_obj or date.today()).isoformat(),
            "include_intraday": include_intraday,
            "orders_processed": len(orders),
            "preview_summary": {
                "positions_to_generate": len(preview_positions),
                "holdings_to_generate": len(preview_holdings),
                "total_position_value": sum(p.get('net_value', 0) for p in preview_positions.values()),
                "total_holdings_value": sum(h.get('current_value', 0) for h in preview_holdings.values()),
                "active_positions": len([p for p in preview_positions.values() if p.get('net_quantity', 0) != 0])
            },
            "positions_preview": [
                {
                    "symbol": k,
                    "net_quantity": v.get('net_quantity', 0),
                    "net_value": v.get('net_value', 0),
                    "realized_pnl": v.get('realized_pnl', 0),
                    "direction": v.get('direction', 'NONE')
                }
                for k, v in preview_positions.items()
            ],
            "holdings_preview": [
                {
                    "symbol": k,
                    "quantity": v.get('quantity', 0),
                    "avg_price": v.get('avg_price', 0),
                    "current_value": v.get('current_value', 0)
                }
                for k, v in preview_holdings.items()
            ]
        }
        
        return {
            "status": "success",
            "message": "Preview generated successfully (no database changes made)",
            "data": preview_result
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate preview: {str(e)}")

@router.get("/stats")
async def get_generation_stats(
    pseudo_account: str = Query(..., description="Account to get stats for"),
    db: Session = Depends(get_db)
):
    """
    Get statistics about order data and potential for position/holdings generation
    
    **Returns:**
    - Order counts by type and date range
    - Symbol analysis
    - Data completeness metrics
    """
    
    try:
        from shared_architecture.db.models.order_model import OrderModel
        from sqlalchemy import func
        
        # Get order statistics
        total_orders = db.query(OrderModel).filter_by(pseudo_account=pseudo_account).count()
        completed_orders = db.query(OrderModel).filter(
            OrderModel.pseudo_account == pseudo_account,
            OrderModel.status == 'COMPLETE'
        ).count()
        
        # Get date range
        date_range = db.query(
            func.min(OrderModel.timestamp).label('earliest'),
            func.max(OrderModel.timestamp).label('latest')
        ).filter_by(pseudo_account=pseudo_account).first()
        
        # Get trade type breakdown
        trade_type_stats = db.query(
            OrderModel.trade_type,
            func.count(OrderModel.id).label('count')
        ).filter_by(
            pseudo_account=pseudo_account
        ).group_by(OrderModel.trade_type).all()
        
        # Get unique symbols
        unique_symbols = db.query(OrderModel.symbol).filter_by(
            pseudo_account=pseudo_account
        ).distinct().count()
        
        stats_result = {
            "pseudo_account": pseudo_account,
            "order_statistics": {
                "total_orders": total_orders,
                "completed_orders": completed_orders,
                "completion_rate": (completed_orders / total_orders * 100) if total_orders > 0 else 0,
                "unique_symbols": unique_symbols
            },
            "date_range": {
                "earliest_order": date_range.earliest.isoformat() if date_range.earliest else None,
                "latest_order": date_range.latest.isoformat() if date_range.latest else None,
                "days_span": (date_range.latest - date_range.earliest).days if date_range.earliest and date_range.latest else 0
            },
            "trade_type_breakdown": [
                {"trade_type": stat.trade_type, "count": stat.count}
                for stat in trade_type_stats
            ],
            "regeneration_feasibility": {
                "can_regenerate": completed_orders > 0,
                "recommended": completed_orders > 10,
                "data_quality": "GOOD" if completed_orders > 100 else "FAIR" if completed_orders > 10 else "LIMITED"
            }
        }
        
        return {
            "status": "success",
            "data": stats_result
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")