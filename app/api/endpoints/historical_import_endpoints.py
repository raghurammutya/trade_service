from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Form, Query
from typing import List, Optional
from sqlalchemy.orm import Session
import tempfile
import os
import logging

from shared_architecture.db.session import get_db
from app.services.historical_trade_importer import HistoricalTradeImporter, ImportResult
from app.utils.kite_symbol_parser import KiteSymbolParser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/historical", tags=["historical_import"])

@router.post("/import-tradebook", response_model=dict)
async def import_historical_tradebook(
    file: UploadFile = File(..., description="Tradebook Excel file"),
    pseudo_account: str = Form(..., description="Trading account identifier"),
    organization_id: str = Form(..., description="Organization identifier"),
    create_strategy: bool = Form(default=True, description="Create historical strategy"),
    strategy_name: Optional[str] = Form(None, description="Custom strategy name"),
    db: Session = Depends(get_db)
):
    """
    Import historical trades from Zerodha tradebook Excel file
    
    **Features:**
    - Parses Kite symbols to internal instrument_key format
    - Creates missing instruments automatically
    - Reconstructs orders from individual trades
    - Calculates final positions and holdings
    - Creates historical strategy for tracking
    - Stores data in TimescaleDB only
    
    **Supported Formats:**
    - Zerodha tradebook Excel files (EQ, FO, COM)
    - Data should start from row 15
    
    **Returns:**
    - Import summary with counts and date range
    """
    try:
        # Validate file type
        if not file.filename.endswith(('.xlsx', '.xls')):
            raise HTTPException(
                status_code=400,
                detail="Only Excel files (.xlsx, .xls) are supported"
            )
        
        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp_file:
            content = await file.read()
            tmp_file.write(content)
            tmp_file_path = tmp_file.name
        
        try:
            # Import tradebook
            importer = HistoricalTradeImporter(db)
            result = await importer.import_tradebook_file(
                tmp_file_path, pseudo_account, organization_id,
                create_strategy, strategy_name
            )
            
            return {
                "status": "success",
                "message": f"Successfully imported {result.orders_imported} orders from {result.trades_imported} trades",
                "details": result.to_dict()
            }
            
        finally:
            # Clean up temporary file
            if os.path.exists(tmp_file_path):
                os.unlink(tmp_file_path)
                
    except Exception as e:
        logger.error(f"Error importing tradebook: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/import-multiple-tradebooks", response_model=dict)
async def import_multiple_tradebooks(
    files: List[UploadFile] = File(..., description="Multiple tradebook Excel files"),
    pseudo_account: str = Form(..., description="Trading account identifier"),
    organization_id: str = Form(..., description="Organization identifier"),
    create_strategy: bool = Form(default=True, description="Create combined historical strategy"),
    strategy_name: Optional[str] = Form(None, description="Custom strategy name"),
    db: Session = Depends(get_db)
):
    """
    Import multiple tradebook files for the same account
    
    **Use Cases:**
    - Import EQ, FO, and COM tradebooks together
    - Import tradebooks from different time periods
    - Combine multiple segments into single import
    
    **Features:**
    - Combines all trades chronologically
    - Creates single strategy for all imports
    - Handles cross-segment positions
    """
    try:
        temp_files = []
        
        # Save all uploaded files
        for file in files:
            if not file.filename.endswith(('.xlsx', '.xls')):
                raise HTTPException(
                    status_code=400,
                    detail=f"File {file.filename} is not an Excel file"
                )
            
            with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp_file:
                content = await file.read()
                tmp_file.write(content)
                temp_files.append(tmp_file.name)
        
        try:
            # Import all tradebooks
            importer = HistoricalTradeImporter(db)
            result = await importer.import_multiple_tradebooks(
                temp_files, pseudo_account, organization_id,
                create_strategy, strategy_name
            )
            
            return {
                "status": "success",
                "message": f"Successfully imported {result.orders_imported} orders from {len(files)} files",
                "details": result.to_dict()
            }
            
        finally:
            # Clean up temporary files
            for tmp_path in temp_files:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                    
    except Exception as e:
        logger.error(f"Error importing multiple tradebooks: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/preview-import", response_model=dict)
async def preview_tradebook_import(
    file: UploadFile = File(..., description="Tradebook Excel file to preview"),
    db: Session = Depends(get_db)
):
    """
    Preview what will be imported without actually importing
    
    **Returns:**
    - Summary statistics
    - Sample symbol parsing results
    - Data validation results
    """
    try:
        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp_file:
            content = await file.read()
            tmp_file.write(content)
            tmp_file_path = tmp_file.name
        
        try:
            importer = HistoricalTradeImporter(db)
            preview = importer.get_import_preview(tmp_file_path)
            
            return {
                "status": "success",
                "preview": preview
            }
            
        finally:
            if os.path.exists(tmp_file_path):
                os.unlink(tmp_file_path)
                
    except Exception as e:
        logger.error(f"Error generating preview: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/parse-symbol", response_model=dict)
async def parse_kite_symbol(
    symbol: str = Query(..., description="Kite symbol to parse"),
    exchange: str = Query(..., description="Exchange (NSE, BSE, MCX)"),
    segment: str = Query(..., description="Segment (EQ, FO, COM)"),
    expiry_date: Optional[str] = Query(None, description="Expiry date for derivatives (YYYY-MM-DD)")
):
    """
    Parse a Kite symbol to internal instrument_key format
    
    **Examples:**
    - Equity: `RELIANCE` → `NSE@RELIANCE@equities`
    - Option: `NIFTY24620223300PE` → `NSE@NIFTY@options@20-Jun-2024@put@23300`
    - Future: `NIFTY25FEBFUT` → `NSE@NIFTY@futures@27-Feb-2025`
    """
    try:
        parser = KiteSymbolParser()
        details = parser.parse_symbol(symbol, exchange, segment, expiry_date)
        
        return {
            "status": "success",
            "parsed_details": details.to_dict(),
            "instrument_key": details.instrument_key
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Error parsing symbol: {str(e)}"
        )

@router.post("/validate-instrument-key", response_model=dict)
async def validate_instrument_key(
    instrument_key: str = Query(..., description="Instrument key to validate")
):
    """
    Validate if an instrument key follows the correct format
    
    **Valid Formats:**
    - Equities: `exchange@symbol@equities`
    - Bonds: `exchange@symbol@bonds`
    - Futures: `exchange@symbol@futures@dd-mmm-yyyy`
    - Options: `exchange@symbol@options@dd-mmm-yyyy@put/call@strike`
    """
    try:
        parser = KiteSymbolParser()
        is_valid = parser.validate_instrument_key(instrument_key)
        
        response = {"instrument_key": instrument_key, "is_valid": is_valid}
        
        if is_valid:
            details = parser.extract_details_from_instrument_key(instrument_key)
            response["details"] = details
        else:
            response["error"] = "Invalid instrument key format"
            
        return response
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/symbol-parsing-examples", response_model=dict)
async def get_symbol_parsing_examples():
    """
    Get examples of Kite symbol to instrument_key conversions
    
    **Returns:**
    Examples for different instrument types showing the conversion pattern
    """
    examples = {
        "equities": [
            {"kite": "RELIANCE", "exchange": "NSE", "instrument_key": "NSE@RELIANCE@equities"},
            {"kite": "TATAMOTORS", "exchange": "NSE", "instrument_key": "NSE@TATAMOTORS@equities"},
            {"kite": "NIFTYBEES", "exchange": "NSE", "instrument_key": "NSE@NIFTYBEES@equities"}
        ],
        "index_options_weekly": [
            {"kite": "NIFTY24620223300PE", "instrument_key": "NSE@NIFTY@options@20-Jun-2024@put@23300"},
            {"kite": "BANKNIFTY2461950000PE", "instrument_key": "NSE@BANKNIFTY@options@19-Jun-2024@put@50000"}
        ],
        "index_options_monthly": [
            {"kite": "NIFTY24JUN23900CE", "instrument_key": "NSE@NIFTY@options@27-Jun-2024@call@23900"},
            {"kite": "BANKNIFTY24JUL52100CE", "instrument_key": "NSE@BANKNIFTY@options@25-Jul-2024@call@52100"}
        ],
        "stock_options": [
            {"kite": "ICICIBANK24AUG1160PE", "instrument_key": "NSE@ICICIBANK@options@29-Aug-2024@put@1160"},
            {"kite": "RELIANCE24SEP2900PE", "instrument_key": "NSE@RELIANCE@options@26-Sep-2024@put@2900"}
        ],
        "futures": [
            {"kite": "NIFTY25FEBFUT", "instrument_key": "NSE@NIFTY@futures@27-Feb-2025"},
            {"kite": "TATAMOTORS25FEBFUT", "instrument_key": "NSE@TATAMOTORS@futures@27-Feb-2025"}
        ],
        "commodities": [
            {"kite": "GOLD24DEC73000PE", "instrument_key": "MCX@GOLD@options@31-Dec-2024@put@73000"},
            {"kite": "GOLD25AUGFUT", "instrument_key": "MCX@GOLD@futures@28-Aug-2025"}
        ],
        "bonds": [
            {"kite": "735GS2024", "exchange": "NSE", "instrument_key": "NSE@735GS2024@bonds"},
            {"kite": "91DTB050924", "exchange": "NSE", "instrument_key": "NSE@91DTB050924@bonds"}
        ]
    }
    
    return {
        "description": "Examples of Kite symbol to instrument_key conversion",
        "note": "Monthly options expire on last Thursday of the month",
        "examples": examples
    }

@router.get("/import-status/{pseudo_account}", response_model=dict)
async def get_import_status(
    pseudo_account: str,
    organization_id: str = Query(..., description="Organization identifier"),
    db: Session = Depends(get_db)
):
    """
    Get historical import status for an account
    
    **Returns:**
    - List of historical strategies created from imports
    - Summary of imported data
    """
    try:
        from shared_architecture.db.models.strategy_model import StrategyModel
        
        # Find historical import strategies
        strategies = db.query(StrategyModel).filter(
            StrategyModel.pseudo_account == pseudo_account,
            StrategyModel.organization_id == organization_id,
            StrategyModel.strategy_id.like('HIST_%')
        ).order_by(StrategyModel.created_at.desc()).all()
        
        import_history = []
        for strategy in strategies:
            config = strategy.configuration or {}
            import_summary = config.get('import_summary', {})
            
            import_history.append({
                'strategy_id': strategy.strategy_id,
                'strategy_name': strategy.strategy_name,
                'created_at': strategy.created_at.isoformat() if strategy.created_at else None,
                'date_range': import_summary.get('date_range', {}),
                'total_trades': import_summary.get('total_trades', 0),
                'unique_symbols': import_summary.get('unique_symbols', 0),
                'source_files': config.get('source_files', [])
            })
        
        return {
            "pseudo_account": pseudo_account,
            "total_imports": len(strategies),
            "import_history": import_history
        }
        
    except Exception as e:
        logger.error(f"Error getting import status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))