import pandas as pd
import re
from typing import List, Dict, Optional
from datetime import datetime, date
from abc import ABC, abstractmethod
from shared_architecture.enums import ChargeCategory, TransactionType, ExchangeSegment
from shared_architecture.utils.safe_converters import safe_convert_float, safe_parse_datetime, safe_parse_str
# Charge taxonomy
CHARGE_KEYWORDS = {
    ChargeCategory.MARGIN: ['span margin', 'exposure margin', 'var margin', 'elm margin'],
    ChargeCategory.SETTLEMENT: ['net obligation', 'mark to market', 'premium settlement'],
    ChargeCategory.BROKERAGE: ['brokerage', 'transaction charges'],
    ChargeCategory.TAX: ['stt', 'ctt', 'stamp duty'],
    ChargeCategory.REGULATORY: ['sebi fee', 'exchange fee', 'clearing fee'],
    ChargeCategory.FUND: ['fund transfer', 'interest credit', 'penalty'],
    ChargeCategory.OTHER: ['dp charges', 'sms charges', 'annual charges']
}

class LedgerParser(ABC):
    def __init__(self, broker_name: str):
        self.broker_name = broker_name
    
    @abstractmethod
    def parse_file(self, file_path: str) -> List[Dict]:
        pass
    
    @abstractmethod
    def standardize_entry(self, raw_entry: Dict) -> Dict:
        pass

class ZerodhaLedgerParser(LedgerParser):
    def parse_file(self, file_path: str) -> List[Dict]:
        """Parse Zerodha Excel ledger file"""
        try:
            # Read the entire Excel file first to examine structure
            df_raw = pd.read_excel(file_path, engine='openpyxl', header=None)
            
            # Find header row by searching all columns for 'Particulars'
            header_row = None
            for idx, row in df_raw.iterrows():
                for col_idx in range(len(row)):
                    cell_value = safe_parse_str(row.iloc[col_idx] if col_idx < len(row) else '')
                    if 'Particulars' in cell_value:
                        header_row = idx
                        break
                if header_row is not None:
                    break
            
            if header_row is None:
                raise ValueError("Could not find header row with 'Particulars'")
            
            # Re-read with correct parameters based on discovered structure
            # For Zerodha files, data typically starts at row 15 (skiprows=14) in columns B:H
            df = pd.read_excel(file_path, engine='openpyxl', skiprows=header_row, usecols='B:H')
            
            # Clean column names and handle potential issues
            expected_columns = ['Particulars', 'Posting Date', 'Cost Center', 'Voucher Type', 'Debit', 'Credit', 'Net Balance']
            if len(df.columns) == len(expected_columns):
                df.columns = expected_columns
            
            # Filter out empty rows and irrelevant entries
            df = df.dropna(how='all')  # Remove completely empty rows
            df = df[df['Particulars'].notna()]  # Remove rows without particulars
            df = df[~df['Particulars'].str.contains('Opening Balance|Closing Balance', na=False)]
            
            # Convert to list of dictionaries
            entries = []
            for _, row in df.iterrows():
                particulars = safe_parse_str(row.get('Particulars', ''))
                if particulars.strip():
                    entries.append(row.to_dict())
            
            print(f"Successfully parsed {len(entries)} entries from Zerodha ledger file")
            return entries
            
        except Exception as e:
            print(f"Error parsing Zerodha file: {e}")
            return []
    
    def standardize_entry(self, raw_entry: Dict) -> Dict:
        """Convert Zerodha entry to standard format"""
        particulars = safe_parse_str(raw_entry.get('Particulars', ''))
        
        # Parse date using shared utility
        posting_date_raw = raw_entry.get('Posting Date')
        parsed_date = None
        if posting_date_raw:
            parsed_date_dt = safe_parse_datetime(posting_date_raw)
            if parsed_date_dt:
                parsed_date = parsed_date_dt.date()
        
        return {
            'transaction_date': parsed_date or date.today(),
            'posting_date': parsed_date,
            'transaction_type': self._extract_transaction_type(particulars).value,
            'particulars': particulars,
            'debit_amount': safe_convert_float(raw_entry.get('Debit'), 0.0),
            'credit_amount': safe_convert_float(raw_entry.get('Credit'), 0.0),
            'net_balance': safe_convert_float(raw_entry.get('Net Balance'), 0.0),
            'cost_center': safe_parse_str(raw_entry.get('Cost Center')),
            'voucher_type': safe_parse_str(raw_entry.get('Voucher Type')),
            'charge_category': self._categorize_charge(particulars).value,
            'charge_subcategory': self._extract_subcategory(particulars),
            'exchange': self._extract_exchange(particulars),
            'segment': self._extract_segment(particulars),
            'broker_name': self.broker_name,
            'raw_data': safe_parse_str(raw_entry)
        }
    
    def _extract_transaction_type(self, particulars: str) -> TransactionType:
        """Extract transaction type from particulars"""
        particulars_lower = particulars.lower()
        
        if 'span margin' in particulars_lower:
            return TransactionType.SPAN_MARGIN_BLOCKED if 'blocked' in particulars_lower else TransactionType.SPAN_MARGIN_REVERSED
        elif 'exposure margin' in particulars_lower:
            return TransactionType.EXPOSURE_MARGIN_BLOCKED if 'blocked' in particulars_lower else TransactionType.EXPOSURE_MARGIN_REVERSED
        elif 'net obligation' in particulars_lower:
            return TransactionType.NET_OBLIGATION
        elif 'brokerage' in particulars_lower:
            return TransactionType.BROKERAGE_CHARGE
        elif 'stt' in particulars_lower:
            return TransactionType.STT_CHARGE
        else:
            return TransactionType.OTHER
    
    def _categorize_charge(self, particulars: str) -> ChargeCategory:
        """Categorize the charge type"""
        particulars_lower = particulars.lower()
        
        for category, keywords in CHARGE_KEYWORDS.items():
            for keyword in keywords:
                if keyword in particulars_lower:
                    return category
        
        return ChargeCategory.OTHER
    
    def _extract_subcategory(self, particulars: str) -> Optional[str]:
        """Extract subcategory from particulars"""
        particulars_lower = particulars.lower()
        
        if 'span margin' in particulars_lower:
            return 'SPAN_MARGIN'
        elif 'exposure margin' in particulars_lower:
            return 'EXPOSURE_MARGIN'
        elif 'net obligation' in particulars_lower:
            return 'NET_OBLIGATION'
        
        return None
    
    def _extract_exchange(self, particulars: str) -> Optional[str]:
        """Extract exchange from particulars"""
        if 'NSE' in particulars:
            return 'NSE'
        elif 'BSE' in particulars:
            return 'BSE'
        elif 'MCX' in particulars:
            return 'MCX'
        
        return None
    
    def _extract_segment(self, particulars: str) -> Optional[str]:
        """Extract segment from particulars"""
        if 'F&O' in particulars:
            return ExchangeSegment.FO.value
        elif 'Equity' in particulars:
            return ExchangeSegment.EQUITY.value
        elif 'Commodity' in particulars:
            return ExchangeSegment.COMMODITY.value
        
        return None

# Broker parser registry
def get_ledger_parser(broker_name: str) -> LedgerParser:
    """Factory function to get appropriate parser"""
    if broker_name.upper() == 'ZERODHA':
        return ZerodhaLedgerParser(broker_name.upper())
    else:
        raise ValueError(f"Unsupported broker: {broker_name}")