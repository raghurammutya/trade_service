import os
from typing import Dict, List
from sqlalchemy.orm import Session
from datetime import datetime, date
from shared_architecture.db.models.ledger_entry_model import LedgerEntryModel
from shared_architecture.db.models.ledger_entry_model import LedgerEntryModel
from app.utils.ledger_parsers import get_ledger_parser,ZerodhaLedgerParser as parser
from shared_architecture.errors.ledger_exceptions import UnsupportedBrokerError, LedgerFileParsingError,LedgerProcessingError
from shared_architecture.schemas.ledger_schema import LedgerEntrySchema
from typing import Optional

class LedgerProcessingService:
    def __init__(self, db: Session):
        self.db = db
    
    async def process_ledger_file(self, file_path: str, broker_name: str, 
                                pseudo_account: str) -> Dict:
        """Process broker ledger file"""
        try:
            # Get parser using factory function
            parser  = get_ledger_parser(broker_name)

            # Parse file
            raw_entries = parser.parse_file(file_path)
        
            # Process entries (same logic as before)
            processed_entries = []
            skipped_entries = 0
            
            for raw_entry in raw_entries:
                try:
                    standardized = parser.standardize_entry(raw_entry)
                    standardized.update({
                        'pseudo_account': pseudo_account,
                        'source_file': os.path.basename(file_path),
                        'processed_at': datetime.utcnow()
                    })
                    processed_entries.append(standardized)
                except Exception as e:
                    print(f"Error processing entry: {e}")
                    skipped_entries += 1
                    continue
            
            # Insert logic remains the same...
            inserted_count = await self._upsert_ledger_entries(processed_entries)
            
            return {
                'total_entries': len(raw_entries),
                'processed_entries': len(processed_entries),
                'inserted_entries': inserted_count,
                'skipped_entries': skipped_entries,
                'date_range': self._get_date_range(processed_entries)
            }
            
        except UnsupportedBrokerError as e:
            raise LedgerProcessingError(f"Broker not supported: {broker_name}")
        except Exception as e:
            raise LedgerProcessingError(f"Failed to process ledger file: {str(e)}")
    
    async def _upsert_ledger_entries(self, entries: List[Dict]) -> int:
        """Insert ledger entries with deduplication"""
        inserted_count = 0
        
        for entry in entries:
            # Check for existing entry (basic deduplication)
            existing = self.db.query(LedgerEntryModel).filter_by(
                pseudo_account=entry['pseudo_account'],
                transaction_date=entry['transaction_date'],
                particulars=entry['particulars'],
                debit_amount=entry['debit_amount'],
                credit_amount=entry['credit_amount']
            ).first()
            
            if not existing:
                ledger_entry = LedgerEntryModel(**entry)
                self.db.add(ledger_entry)
                inserted_count += 1
        
        self.db.commit()
        return inserted_count
    
    def _get_date_range(self, entries: List[Dict]) -> Dict:
        """Get date range from processed entries"""
        if not entries:
            return {}
        
        dates = [entry['transaction_date'] for entry in entries if entry.get('transaction_date')]
        if dates:
            return {
                'from_date': min(dates).isoformat(),
                'to_date': max(dates).isoformat()
            }
        return {}
    
    async def get_charges_summary(self, pseudo_account: str, from_date: date, 
                                  to_date: date, charge_category: Optional[str] = None) -> List[Dict]:
        """Get charges summary by category and date range"""
        query = self.db.query(LedgerEntryModel).filter_by(pseudo_account=pseudo_account)
        query = query.filter(LedgerEntryModel.transaction_date.between(from_date, to_date))
        
        if charge_category:
            query = query.filter_by(charge_category=charge_category)
        
        entries = query.all()
        
        # Group by charge category
        summary = {}
        for entry in entries:
            category = entry.charge_category or 'OTHER'
            if category not in summary:
                summary[category] = {
                    'total_debit': 0.0,
                    'total_credit': 0.0,
                    'net_amount': 0.0,
                    'entry_count': 0
                }
            
            summary[category]['total_debit'] += entry.debit_amount or 0
            summary[category]['total_credit'] += entry.credit_amount or 0
            summary[category]['net_amount'] = summary[category]['total_credit'] - summary[category]['total_debit']
            summary[category]['entry_count'] += 1
        
        return [{'category': k, **v} for k, v in summary.items()]