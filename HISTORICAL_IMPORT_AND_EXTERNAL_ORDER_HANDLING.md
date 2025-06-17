# Historical Import & External Order Handling System

## Overview

This document describes the comprehensive system for:
1. **Historical Trade Import**: Loading past trades from broker tradebooks
2. **External Order Detection**: Handling orders placed outside our system
3. **Dual Storage**: Synchronized storage in both TimescaleDB and Redis
4. **Symbol Management**: Automatic instrument creation and mapping

## Architecture Components

### 1. Historical Trade Import System

#### **Purpose**
Import historical trades from Zerodha tradebook Excel files to:
- Reconstruct past trading activity
- Calculate positions and holdings
- Create audit trail for compliance
- Enable backtesting and analysis

#### **Components**

##### **KiteSymbolParser** (`app/utils/kite_symbol_parser.py`)
Converts Zerodha/Kite symbols to internal instrument_key format:

```python
# Examples:
RELIANCE → NSE@RELIANCE@equities
NIFTY24620223300PE → NSE@NIFTY@options@20-Jun-2024@put@23300
NIFTY24JUN23900CE → NSE@NIFTY@options@27-Jun-2024@call@23900
NIFTY25FEBFUT → NSE@NIFTY@futures@27-Feb-2025
GOLD24DEC73000PE → MCX@GOLD@options@31-Dec-2024@put@73000
```

**Key Features:**
- Pattern-based parsing for different instrument types
- Automatic last Thursday calculation for monthly options
- Support for equities, F&O, commodities, and bonds
- Validation of instrument key format

##### **TradebookParser** (`app/utils/tradebook_parser.py`)
Parses Zerodha Excel tradebook files:

**File Structure:**
- Data starts at row 15 (header at row 14)
- 13 columns for equities, 15 for derivatives
- Columns: Symbol, ISIN, Trade Date, Exchange, Segment, etc.

**Features:**
- Validates tradebook integrity
- Handles multiple file imports
- Filters by date range
- Generates import summaries

##### **HistoricalOrderReconstructor** (`app/utils/historical_order_reconstructor.py`)
Reconstructs orders from individual trades:

**Process:**
1. Groups trades by Order ID
2. Calculates order-level metrics (avg price, total quantity)
3. Creates position timeline showing evolution
4. Calculates final positions and holdings
5. Generates order events for audit trail

**Key Algorithms:**
- FIFO-based PnL calculation
- Position tracking with buy/sell values
- Holdings calculation for T+1 settled equities

##### **HistoricalTradeImporter** (`app/services/historical_trade_importer.py`)
Main service orchestrating the import:

**Workflow:**
1. Parse tradebook Excel file
2. Parse symbols and create instrument keys
3. Ensure all instruments exist in database
4. Reconstruct orders from trades
5. Calculate positions and holdings
6. Create historical strategy
7. Store in TimescaleDB

### 2. External Order Detection System

#### **Design for Future Implementation**

##### **ExternalEntityDetector**
Detects orders/positions created outside our system:

```python
class ExternalEntityDetector:
    async def detect_external_orders(self, fetched_orders: List[Dict]) -> List[Dict]:
        """Compare fetched orders with internal order log"""
        
    async def classify_external_entity(self, entity: Dict) -> ExternalEntityType:
        """Classify source: MANUAL_ORDER, CORPORATE_ACTION, TRANSFER, etc."""
```

##### **StrategyAssignmentEngine**
Intelligently assigns external entities to strategies:

**Assignment Logic:**
1. **Exact Symbol Match** (90% confidence)
   - Strategy actively trading same symbol
2. **Symbol Group Match** (70% confidence)
   - Same sector/similar assets
3. **Pattern Match** (60% confidence)
   - Similar order sizes/timing
4. **Default Strategy** (40% confidence)
   - Single active strategy
5. **Manual Review Queue** (0% confidence)
   - Multiple possible strategies

##### **DualStorageManager**
Manages synchronized storage to both databases:

```python
class DualStorageManager:
    async def store_strategy(self, strategy: StrategyModel):
        """Store in both TimescaleDB and Redis atomically"""
        
    async def update_strategy_metrics(self, strategy_id: str):
        """Update metrics in both storage systems"""
```

### 3. API Endpoints

#### **Historical Import Endpoints**

##### **Import Single Tradebook**
```http
POST /historical/import-tradebook
Content-Type: multipart/form-data

file: tradebook.xlsx
pseudo_account: "Raghu"
organization_id: "stocksblitz"
create_strategy: true
strategy_name: "Historical Q2 2024"
```

##### **Import Multiple Tradebooks**
```http
POST /historical/import-multiple-tradebooks
Content-Type: multipart/form-data

files: [tradebook-EQ.xlsx, tradebook-FO.xlsx, tradebook-COM.xlsx]
pseudo_account: "Raghu"
organization_id: "stocksblitz"
```

##### **Preview Import**
```http
POST /historical/preview-import
Content-Type: multipart/form-data

file: tradebook.xlsx
```

##### **Parse Symbol**
```http
GET /historical/parse-symbol?symbol=NIFTY24620223300PE&exchange=NSE&segment=FO
```

#### **Strategy Management Endpoints**
See `STRATEGY_MANAGEMENT_API.md` for complete strategy API documentation.

### 4. Data Models

#### **Enhanced Order Model**
```sql
-- Additional columns for external orders
source_type VARCHAR(20) DEFAULT 'INTERNAL' -- INTERNAL, EXTERNAL, HISTORICAL_IMPORT
external_order_id VARCHAR(100)
discovery_timestamp TIMESTAMP
assignment_method VARCHAR(20)
assignment_confidence FLOAT
external_metadata JSON
```

#### **External Entity Audit Trail**
```sql
CREATE TABLE tradingdb.external_entity_log (
    id SERIAL PRIMARY KEY,
    entity_type VARCHAR(20),
    entity_id VARCHAR(100),
    discovery_method VARCHAR(50),
    classification VARCHAR(50),
    strategy_assignment VARCHAR(50),
    assignment_method VARCHAR(20),
    confidence_score FLOAT,
    metadata JSON,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### 5. Redis Storage Schema

#### **Strategy Data in Redis**
```python
# Key patterns
strategy:{org}:{account}:{strategy_id}:meta     # Metadata
strategy:{org}:{account}:{strategy_id}:positions # Positions
strategy:{org}:{account}:{strategy_id}:orders   # Orders
strategy:{org}:{account}:{strategy_id}:holdings # Holdings
strategy:{org}:{account}:{strategy_id}:metrics  # Real-time metrics
```

### 6. Usage Examples

#### **Import Historical Trades**
```bash
# Import single tradebook
curl -X POST "http://localhost:8004/historical/import-tradebook" \
  -F "file=@/path/to/tradebook-XJ4540-EQ.xlsx" \
  -F "pseudo_account=Raghu" \
  -F "organization_id=stocksblitz" \
  -F "create_strategy=true"

# Import multiple tradebooks
curl -X POST "http://localhost:8004/historical/import-multiple-tradebooks" \
  -F "files=@tradebook-XJ4540-EQ.xlsx" \
  -F "files=@tradebook-XJ4540-FO.xlsx" \
  -F "files=@tradebook-XJ4540-COM.xlsx" \
  -F "pseudo_account=Raghu" \
  -F "organization_id=stocksblitz"
```

#### **Parse Kite Symbols**
```bash
# Parse option symbol
curl "http://localhost:8004/historical/parse-symbol?symbol=NIFTY24620223300PE&exchange=NSE&segment=FO"

# Response:
{
  "status": "success",
  "parsed_details": {
    "symbol": "NIFTY",
    "exchange": "NSE",
    "segment": "FO",
    "instrument_type": "OPTION",
    "strike_price": 23300,
    "option_type": "PE",
    "expiry_date": "20-Jun-2024"
  },
  "instrument_key": "NSE@NIFTY@options@20-Jun-2024@put@23300"
}
```

### 7. Error Handling

#### **Import Errors**
- Invalid file format
- Missing required columns
- Symbol parsing failures
- Duplicate order IDs
- Database constraints

#### **Recovery Strategies**
1. Transaction rollback on failure
2. Detailed error logging
3. Partial import support
4. Import preview for validation

### 8. Performance Considerations

#### **Bulk Operations**
- Batch symbol creation
- Bulk order insertion
- Efficient position calculation

#### **Memory Management**
- Streaming Excel file parsing
- Chunked data processing
- Symbol lookup caching

### 9. Security & Compliance

#### **Data Validation**
- File type validation
- Data integrity checks
- Symbol format validation
- Date range validation

#### **Audit Trail**
- Complete import history
- Order reconstruction logs
- Position snapshots
- Strategy assignment records

### 10. Future Enhancements

#### **Planned Features**
1. **Real-time External Order Detection**
   - WebSocket integration for live detection
   - Automatic strategy assignment
   - Alert notifications

2. **Advanced Symbol Mapping**
   - Multi-broker symbol conversion
   - Corporate action handling
   - Symbol change tracking

3. **Enhanced Position Calculation**
   - Intraday position tracking
   - Corporate action adjustments
   - Multi-currency support

4. **Strategy Intelligence**
   - ML-based strategy assignment
   - Pattern recognition
   - Anomaly detection

## Testing

### **Test Data**
Sample tradebook files provided:
- `tradebook-XJ4540-EQ.xlsx` - 631 equity trades
- `tradebook-XJ4540-FO.xlsx` - 4,992 F&O trades
- `tradebook-XJ4540-COM.xlsx` - 10 commodity trades

### **Test Scenarios**
1. Import single segment tradebook
2. Import multiple segments together
3. Handle duplicate imports
4. Symbol parsing edge cases
5. Position calculation accuracy
6. Holdings T+1 settlement

## Conclusion

This system provides comprehensive historical trade import with intelligent symbol parsing, order reconstruction, and position calculation. The architecture supports future external order detection with strategy assignment capabilities. All data is stored in TimescaleDB with provisions for Redis caching for real-time access.