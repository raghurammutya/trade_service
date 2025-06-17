import re
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from typing import Dict, Optional, Tuple
import calendar

class InstrumentDetails:
    """Details of a parsed instrument"""
    def __init__(self, 
                 symbol: str,
                 exchange: str,
                 segment: str,
                 instrument_type: str,
                 instrument_key: str,
                 strike_price: Optional[float] = None,
                 option_type: Optional[str] = None,
                 expiry_date: Optional[str] = None):
        self.symbol = symbol
        self.exchange = exchange
        self.segment = segment
        self.instrument_type = instrument_type
        self.instrument_key = instrument_key
        self.strike_price = strike_price
        self.option_type = option_type
        self.expiry_date = expiry_date

    def to_dict(self):
        return {
            'symbol': self.symbol,
            'exchange': self.exchange,
            'segment': self.segment,
            'instrument_type': self.instrument_type,
            'instrument_key': self.instrument_key,
            'strike_price': self.strike_price,
            'option_type': self.option_type,
            'expiry_date': self.expiry_date
        }


class KiteSymbolParser:
    """Parser for Zerodha/Kite symbols to internal instrument_key format"""
    
    # Symbol patterns
    INDEX_WEEKLY_OPT = re.compile(r'^(NIFTY|BANKNIFTY|FINNIFTY|MIDCPNIFTY|SENSEX)(\d{2})(\d{2})(\d{2})(\d+)(CE|PE)$')
    INDEX_MONTHLY_OPT = re.compile(r'^(NIFTY|BANKNIFTY|FINNIFTY|MIDCPNIFTY|SENSEX)(\d{2})([A-Z]{3})(\d+)(CE|PE)$')
    INDEX_SINGLE_MONTH_OPT = re.compile(r'^(NIFTY|BANKNIFTY|FINNIFTY|MIDCPNIFTY|SENSEX)(\d{2})([A-Z])(\d{2})(\d+)(CE|PE)$')
    STOCK_MONTHLY_OPT = re.compile(r'^([A-Z0-9\-]+)(\d{2})([A-Z]{3})(\d+)(CE|PE)$')
    FUTURES = re.compile(r'^([A-Z0-9\-]+)(\d{2})([A-Z]{3})FUT$')
    COMMODITY_OPT = re.compile(r'^([A-Z]+M?)(\d{2})([A-Z]{3})(\d+)(CE|PE)$')
    COMMODITY_FUT = re.compile(r'^([A-Z]+M?)(\d{2})([A-Z]{3})FUT$')
    
    # Month mapping
    MONTH_MAP = {
        'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
        'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12
    }
    
    # Single-letter month mapping (common in some derivatives)
    SINGLE_MONTH_MAP = {
        'A': 1, 'B': 2, 'C': 3, 'D': 4, 'E': 5, 'F': 6,
        'G': 7, 'H': 8, 'I': 9, 'J': 10, 'K': 11, 'L': 12,
        # Alternative mapping that might be used
        'N': 1, 'O': 10, 'S': 9, 'D': 12  # Common single-letter codes
    }
    
    def __init__(self):
        self._last_thursday_cache = {}
    
    def parse_symbol(self, symbol: str, exchange: str, segment: str, 
                     expiry_str: Optional[str] = None) -> InstrumentDetails:
        """
        Main entry point for parsing Kite symbols
        
        Args:
            symbol: Kite symbol (e.g., 'NIFTY24620223300PE')
            exchange: Exchange code (NSE, BSE, MCX)
            segment: Segment (EQ, FO, COM)
            expiry_str: Expiry date string from tradebook (YYYY-MM-DD format)
            
        Returns:
            InstrumentDetails object with parsed information
        """
        if segment == "EQ":
            return self._parse_equity(symbol, exchange)
        elif segment == "FO":
            return self._parse_fo(symbol, exchange, expiry_str)
        elif segment == "COM":
            return self._parse_commodity(symbol, exchange, expiry_str)
        else:
            raise ValueError(f"Unknown segment: {segment}")
    
    def _parse_equity(self, symbol: str, exchange: str) -> InstrumentDetails:
        """Parse equity symbols"""
        # Check if it's a bond (contains numbers at start or end)
        if re.match(r'^\d+[A-Z]+\d*$|^[A-Z]+\d+$', symbol):
            product_type = "bonds"
        else:
            product_type = "equities"
            
        instrument_key = f"{exchange}@{symbol}@{product_type}"
        
        return InstrumentDetails(
            symbol=symbol,
            exchange=exchange,
            segment="EQ",
            instrument_type=product_type.upper()[:-1],  # EQUITY or BOND
            instrument_key=instrument_key
        )
    
    def _parse_fo(self, symbol: str, exchange: str, expiry_str: Optional[str]) -> InstrumentDetails:
        """Parse F&O symbols"""
        # Try weekly index options first
        if match := self.INDEX_WEEKLY_OPT.match(symbol):
            underlying, year, month, day, strike, option_type = match.groups()
            
            # Use provided expiry date if available, otherwise try to parse from symbol
            if expiry_str:
                # Convert expiry_str (e.g., "2024-06-20") to our format
                from datetime import datetime
                expiry_dt = datetime.strptime(expiry_str, '%Y-%m-%d')
                expiry_date = expiry_dt.strftime('%d-%b-%Y')
            else:
                # Fallback to parsing from symbol (though this may not work for all formats)
                try:
                    expiry_date = self._format_date(f"20{year}", month, day)
                except ValueError:
                    # If parsing fails, use a placeholder
                    expiry_date = f"20{year}-XX-XX"
            
            instrument_key = f"{exchange}@{underlying}@options@{expiry_date}@{option_type.lower()}@{strike}"
            
            return InstrumentDetails(
                symbol=underlying,
                exchange=exchange,
                segment="FO",
                instrument_type="OPTION",
                instrument_key=instrument_key,
                strike_price=float(strike),
                option_type=option_type,
                expiry_date=expiry_date
            )
        
        # Try monthly index options
        elif match := self.INDEX_MONTHLY_OPT.match(symbol):
            underlying, year, month_abbr, strike, option_type = match.groups()
            expiry_date = self._get_monthly_expiry_date(year, month_abbr, expiry_str)
            
            instrument_key = f"{exchange}@{underlying}@options@{expiry_date}@{option_type.lower()}@{strike}"
            
            return InstrumentDetails(
                symbol=underlying,
                exchange=exchange,
                segment="FO",
                instrument_type="OPTION",
                instrument_key=instrument_key,
                strike_price=float(strike),
                option_type=option_type,
                expiry_date=expiry_date
            )
        
        # Try single-letter monthly index options  
        elif match := self.INDEX_SINGLE_MONTH_OPT.match(symbol):
            underlying, year, month_letter, day, strike, option_type = match.groups()
            
            # Use provided expiry date if available
            if expiry_str:
                from datetime import datetime
                expiry_dt = datetime.strptime(expiry_str, '%Y-%m-%d')
                expiry_date = expiry_dt.strftime('%d-%b-%Y')
            else:
                # Try to map single letter to month
                month_num = self.SINGLE_MONTH_MAP.get(month_letter, 1)
                expiry_date = self._format_date(f"20{year}", str(month_num).zfill(2), day)
            
            instrument_key = f"{exchange}@{underlying}@options@{expiry_date}@{option_type.lower()}@{strike}"
            
            return InstrumentDetails(
                symbol=underlying,
                exchange=exchange,
                segment="FO",
                instrument_type="OPTION",
                instrument_key=instrument_key,
                strike_price=float(strike),
                option_type=option_type,
                expiry_date=expiry_date
            )
        
        # Try stock monthly options
        elif match := self.STOCK_MONTHLY_OPT.match(symbol):
            underlying, year, month_abbr, strike, option_type = match.groups()
            expiry_date = self._get_monthly_expiry_date(year, month_abbr, expiry_str)
            
            instrument_key = f"{exchange}@{underlying}@options@{expiry_date}@{option_type.lower()}@{strike}"
            
            return InstrumentDetails(
                symbol=underlying,
                exchange=exchange,
                segment="FO",
                instrument_type="OPTION",
                instrument_key=instrument_key,
                strike_price=float(strike),
                option_type=option_type,
                expiry_date=expiry_date
            )
        
        # Try futures
        elif match := self.FUTURES.match(symbol):
            underlying, year, month_abbr = match.groups()
            expiry_date = self._get_monthly_expiry_date(year, month_abbr, expiry_str)
            
            instrument_key = f"{exchange}@{underlying}@futures@{expiry_date}"
            
            return InstrumentDetails(
                symbol=underlying,
                exchange=exchange,
                segment="FO",
                instrument_type="FUTURE",
                instrument_key=instrument_key,
                expiry_date=expiry_date
            )
        
        else:
            raise ValueError(f"Could not parse F&O symbol: {symbol}")
    
    def _parse_commodity(self, symbol: str, exchange: str, expiry_str: Optional[str]) -> InstrumentDetails:
        """Parse commodity symbols"""
        # Try commodity options
        if match := self.COMMODITY_OPT.match(symbol):
            underlying, year, month_abbr, strike, option_type = match.groups()
            expiry_date = self._get_commodity_expiry_date(year, month_abbr, expiry_str)
            
            instrument_key = f"{exchange}@{underlying}@options@{expiry_date}@{option_type.lower()}@{strike}"
            
            return InstrumentDetails(
                symbol=underlying,
                exchange=exchange,
                segment="COM",
                instrument_type="OPTION",
                instrument_key=instrument_key,
                strike_price=float(strike),
                option_type=option_type,
                expiry_date=expiry_date
            )
        
        # Try commodity futures
        elif match := self.COMMODITY_FUT.match(symbol):
            underlying, year, month_abbr = match.groups()
            expiry_date = self._get_commodity_expiry_date(year, month_abbr, expiry_str)
            
            instrument_key = f"{exchange}@{underlying}@futures@{expiry_date}"
            
            return InstrumentDetails(
                symbol=underlying,
                exchange=exchange,
                segment="COM",
                instrument_type="FUTURE",
                instrument_key=instrument_key,
                expiry_date=expiry_date
            )
        
        else:
            raise ValueError(f"Could not parse commodity symbol: {symbol}")
    
    def _format_date(self, year: str, month: str, day: str) -> str:
        """Format date to dd-mmm-yyyy format"""
        date_obj = datetime(int(year), int(month), int(day))
        return date_obj.strftime("%d-%b-%Y")
    
    def _get_monthly_expiry_date(self, year: str, month_abbr: str, expiry_str: Optional[str]) -> str:
        """
        Get monthly expiry date (last Thursday for NSE/BSE)
        If expiry_str is provided, use it; otherwise calculate last Thursday
        """
        if expiry_str:
            # Convert YYYY-MM-DD to dd-mmm-yyyy
            date_obj = datetime.strptime(expiry_str, "%Y-%m-%d")
            return date_obj.strftime("%d-%b-%Y")
        
        # Calculate last Thursday
        return self._get_last_thursday(year, month_abbr)
    
    def _get_commodity_expiry_date(self, year: str, month_abbr: str, expiry_str: Optional[str]) -> str:
        """
        Get commodity expiry date
        MCX has different expiry patterns, so use provided expiry_str if available
        """
        if expiry_str:
            date_obj = datetime.strptime(expiry_str, "%Y-%m-%d")
            return date_obj.strftime("%d-%b-%Y")
        
        # For commodities, if no expiry provided, use last day of month as fallback
        month_num = self.MONTH_MAP[month_abbr]
        year_full = int(f"20{year}")
        last_day = calendar.monthrange(year_full, month_num)[1]
        
        date_obj = datetime(year_full, month_num, last_day)
        return date_obj.strftime("%d-%b-%Y")
    
    def _get_last_thursday(self, year: str, month_abbr: str) -> str:
        """Calculate last Thursday of the month"""
        cache_key = f"{year}_{month_abbr}"
        if cache_key in self._last_thursday_cache:
            return self._last_thursday_cache[cache_key]
        
        month_num = self.MONTH_MAP[month_abbr]
        year_full = int(f"20{year}")
        
        # Get last day of month
        last_day = calendar.monthrange(year_full, month_num)[1]
        
        # Find last Thursday
        for day in range(last_day, 0, -1):
            date_obj = datetime(year_full, month_num, day)
            if date_obj.weekday() == 3:  # Thursday is 3
                result = date_obj.strftime("%d-%b-%Y")
                self._last_thursday_cache[cache_key] = result
                return result
        
        raise ValueError(f"Could not find last Thursday for {month_abbr} 20{year}")
    
    def validate_instrument_key(self, instrument_key: str) -> bool:
        """Validate if instrument key follows the correct format"""
        parts = instrument_key.split('@')
        
        if len(parts) < 3:
            return False
        
        exchange, symbol, product_type = parts[0], parts[1], parts[2]
        
        # Validate exchange
        if exchange not in ['NSE', 'BSE', 'MCX', 'NFO', 'CDS', 'BFO']:
            return False
        
        # Validate product type and additional parts
        if product_type == 'equities' or product_type == 'bonds':
            return len(parts) == 3
        elif product_type == 'futures':
            return len(parts) == 4  # exchange@symbol@futures@expiry
        elif product_type == 'options':
            return len(parts) == 6  # exchange@symbol@options@expiry@type@strike
        else:
            return False
    
    def extract_details_from_instrument_key(self, instrument_key: str) -> Dict:
        """Extract details from instrument key"""
        parts = instrument_key.split('@')
        
        details = {
            'exchange': parts[0],
            'symbol': parts[1],
            'product_type': parts[2]
        }
        
        if len(parts) > 3:
            details['expiry_date'] = parts[3]
        
        if len(parts) > 4:
            details['option_type'] = parts[4]
            details['strike_price'] = float(parts[5])
        
        return details