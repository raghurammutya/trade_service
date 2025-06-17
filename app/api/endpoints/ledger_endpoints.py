from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from typing import Optional
from datetime import date
import tempfile
import os

from shared_architecture.db import get_db
from shared_architecture.schemas.ledger_schema import LedgerUploadResponse, LedgerEntrySchema
from app.services.ledger_service import LedgerProcessingService
from shared_architecture.errors.ledger_exceptions import LedgerProcessingError
router = APIRouter()

@router.post("/upload/{broker_name}", response_model=LedgerUploadResponse)
async def upload_ledger_file(
    broker_name: str,
    pseudo_account: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Upload and process broker ledger file"""
    try:
        # Validate file type
        if not file.filename or not file.filename.endswith(('.xlsx', '.xls')):
            raise HTTPException(status_code=400, detail="Only Excel files are supported")
        
        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp_file:
            content = await file.read()
            tmp_file.write(content)
            tmp_file_path = tmp_file.name
        
        try:
            # Process the file
            ledger_service = LedgerProcessingService(db)
            result = await ledger_service.process_ledger_file(
                tmp_file_path, broker_name.upper(), pseudo_account
            )
            
            return LedgerUploadResponse(
                total_entries=result['total_entries'],
                processed_entries=result['processed_entries'],
                skipped_entries=result['skipped_entries'],
                date_range=result['date_range'],
                message=f"Successfully processed {result['processed_entries']} entries"
            )
            
        finally:
            # Clean up temporary file
            os.unlink(tmp_file_path)
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/charges/{pseudo_account}")
async def get_charges_summary(
    pseudo_account: str,
    from_date: date,
    to_date: date,
    charge_category: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Get charges summary by category and date range"""
    try:
        ledger_service = LedgerProcessingService(db)
        summary = await ledger_service.get_charges_summary(
            pseudo_account, from_date, to_date, charge_category
        )
        return {"charges_summary": summary}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/margin-movements/{pseudo_account}")
async def get_margin_movements(
    pseudo_account: str,
    from_date: date,
    to_date: date,
    db: Session = Depends(get_db)
):
    """Get margin block/release movements"""
    try:
        ledger_service = LedgerProcessingService(db)
        # Filter for margin-related entries
        movements = await ledger_service.get_charges_summary(
            pseudo_account, from_date, to_date, 'MARGIN'
        )
        return {"margin_movements": movements}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))