# Strategy Management API Documentation

## Overview

The Strategy Management API provides comprehensive functionality for creating, managing, and monitoring trading strategies. This system ensures data integrity across positions, orders, and holdings while providing powerful tools for strategy-based trading operations.

## Key Features

✅ **Manual Strategy Creation & Management**  
✅ **Position/Order/Holdings Tagging to Strategies**  
✅ **Real-time Strategy Performance Tracking**  
✅ **Strategy Square-off Engine (with simulation)**  
✅ **Data Integrity Protection**  
✅ **Risk Management Controls**  
✅ **Comprehensive Error Handling**  

## Database Schema

### Strategy Table: `tradingdb.strategies`

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Primary key |
| `strategy_id` | STRING(50) | Unique strategy identifier |
| `strategy_name` | STRING(200) | Display name |
| `pseudo_account` | STRING(100) | Trading account |
| `organization_id` | STRING(100) | Organization identifier |
| `strategy_type` | STRING(50) | Strategy type (MANUAL, ALGORITHMIC, etc.) |
| `status` | STRING(20) | ACTIVE, PAUSED, COMPLETED, SQUARED_OFF, DISABLED |
| `description` | TEXT | Strategy description |
| `max_loss_amount` | FLOAT | Risk management limit |
| `max_profit_amount` | FLOAT | Profit target |
| `max_positions` | INTEGER | Maximum position count |
| `total_pnl` | FLOAT | Current total P&L |
| `realized_pnl` | FLOAT | Realized P&L |
| `unrealized_pnl` | FLOAT | Unrealized P&L |
| `total_margin_used` | FLOAT | Margin utilization |
| `active_positions_count` | INTEGER | Active positions |
| `total_orders_count` | INTEGER | Total orders |
| `active_orders_count` | INTEGER | Active orders |
| `holdings_count` | INTEGER | Holdings count |
| `auto_square_off_enabled` | BOOLEAN | Auto square-off setting |
| `square_off_time` | STRING(8) | Auto square-off time (HH:MM:SS) |
| `tags` | JSON | Strategy tags |
| `configuration` | JSON | Strategy configuration |
| `created_at` | DATETIME | Creation timestamp |
| `updated_at` | DATETIME | Last update timestamp |

## API Endpoints

### 1. Strategy CRUD Operations

#### Create Strategy
```http
POST /strategies/create?created_by={user}
Content-Type: application/json

{
  "strategy_name": "Swing Trading Strategy",
  "pseudo_account": "Raghu",
  "organization_id": "stocksblitz",
  "strategy_type": "SWING",
  "description": "Medium-term swing trading strategy",
  "max_loss_amount": 10000.0,
  "max_profit_amount": 25000.0,
  "max_positions": 5,
  "tags": ["swing", "manual", "equity"],
  "auto_square_off_enabled": true,
  "square_off_time": "15:15:00",
  "configuration": {
    "risk_per_trade": 2.0,
    "position_sizing": "fixed"
  }
}
```

**Response:**
```json
{
  "strategy_id": "STR_A1B2C3D4",
  "strategy_name": "Swing Trading Strategy",
  "status": "ACTIVE",
  "total_pnl": 0.0,
  "unrealized_pnl": 0.0,
  "active_positions_count": 0,
  "created_at": "2025-06-17T10:30:00Z"
}
```

#### Get Strategy
```http
GET /strategies/{strategy_id}
```

#### Update Strategy
```http
PUT /strategies/{strategy_id}?updated_by={user}
Content-Type: application/json

{
  "strategy_name": "Updated Strategy Name",
  "max_loss_amount": 15000.0,
  "status": "PAUSED"
}
```

#### Delete Strategy
```http
DELETE /strategies/{strategy_id}
```
⚠️ **Safety:** Prevents deletion if active positions/orders exist

#### List Strategies
```http
GET /strategies/list/{pseudo_account}?organization_id={org_id}
```

### 2. Strategy Tagging Operations

#### Tag Positions to Strategy
```http
POST /strategies/{strategy_id}/tag-positions
Content-Type: application/json

{
  "entity_ids": ["pos_123", "pos_456", "pos_789"],
  "overwrite_existing": false
}
```

**Response:**
```json
{
  "strategy_id": "STR_A1B2C3D4",
  "entity_type": "positions",
  "tagged_count": 3,
  "skipped_count": 0,
  "error_count": 0,
  "details": [
    {"entity_id": "pos_123", "status": "success", "message": "Tagged successfully"},
    {"entity_id": "pos_456", "status": "success", "message": "Tagged successfully"},
    {"entity_id": "pos_789", "status": "success", "message": "Tagged successfully"}
  ]
}
```

#### Tag Orders to Strategy
```http
POST /strategies/{strategy_id}/tag-orders
Content-Type: application/json

{
  "entity_ids": ["order_1", "order_2"],
  "overwrite_existing": true
}
```

#### Tag Holdings to Strategy
```http
POST /strategies/{strategy_id}/tag-holdings
Content-Type: application/json

{
  "entity_ids": ["holding_1", "holding_2"],
  "overwrite_existing": false
}
```

### 3. Strategy Data Retrieval

#### Get Strategy Positions
```http
GET /strategies/{strategy_id}/positions
```

**Response:**
```json
{
  "strategy_id": "STR_A1B2C3D4",
  "positions": [
    {
      "id": "pos_123",
      "trading_symbol": "RELIANCE",
      "exchange": "NSE",
      "quantity": 100,
      "average_price": 2500.0,
      "current_price": 2550.0,
      "unrealized_pnl": 5000.0,
      "product_type": "MIS"
    }
  ],
  "total_positions": 1,
  "active_positions": 1
}
```

#### Get Strategy Orders
```http
GET /strategies/{strategy_id}/orders?status_filter=OPEN
```

#### Get Strategy Holdings
```http
GET /strategies/{strategy_id}/holdings
```

#### Get Strategy Summary
```http
GET /strategies/{strategy_id}/summary
```
Returns complete strategy overview with positions, orders, and holdings.

### 4. Strategy Square-off Operations

#### Preview Square-off
```http
GET /strategies/{strategy_id}/square-off/preview
```

**Response:**
```json
{
  "strategy_id": "STR_A1B2C3D4",
  "estimated_orders": [
    {
      "trading_symbol": "RELIANCE",
      "exchange": "NSE",
      "order_type": "SELL",
      "quantity": 100,
      "product_type": "MIS",
      "current_pnl": 5000.0,
      "position_type": "LONG"
    }
  ],
  "total_positions": 1,
  "total_holdings": 0,
  "estimated_pnl_impact": 5000.0,
  "margin_release_estimate": 125000.0,
  "warnings": []
}
```

#### Execute Square-off
```http
POST /strategies/{strategy_id}/square-off
Content-Type: application/json

{
  "confirm": true,
  "force_market_orders": true,
  "batch_size": 10,
  "dry_run": false
}
```

**Response:**
```json
{
  "strategy_id": "STR_A1B2C3D4",
  "total_orders_placed": 1,
  "successful_orders": 1,
  "failed_orders": 0,
  "batch_count": 1,
  "estimated_completion_time": "IMMEDIATE",
  "order_details": [
    {
      "symbol": "RELIANCE",
      "action": "SELL",
      "quantity": 100,
      "status": "SIMULATED",
      "message": "Square-off order simulated (actual placement requires broker integration)"
    }
  ],
  "errors": ["DRY_RUN: No actual orders placed"]
}
```

### 5. Utility Endpoints

#### Recalculate Strategy Metrics
```http
POST /strategies/{strategy_id}/recalculate-metrics
```

#### Get Risk Metrics
```http
GET /strategies/{strategy_id}/risk-metrics
```

**Response:**
```json
{
  "strategy_id": "STR_A1B2C3D4",
  "current_pnl": 5000.0,
  "unrealized_pnl": 5000.0,
  "margin_used": 125000.0,
  "max_loss_limit": 10000.0,
  "max_profit_target": 25000.0,
  "risk_metrics": {
    "loss_percentage": -50.0,
    "profit_percentage": 20.0,
    "position_utilization": 20.0
  }
}
```

## Strategy Types

- `MANUAL` - Manual trading strategy
- `ALGORITHMIC` - Automated algorithmic trading  
- `COPY_TRADING` - Copy trading strategy
- `BASKET` - Basket trading
- `ARBITRAGE` - Arbitrage opportunities
- `HEDGE` - Hedging strategy
- `SCALPING` - High-frequency scalping
- `SWING` - Swing trading
- `OPTIONS` - Options trading
- `FUTURES` - Futures trading

## Strategy Status Values

- `ACTIVE` - Strategy is active and can accept new trades
- `PAUSED` - Strategy is paused, no new trades
- `COMPLETED` - Strategy has completed its objective
- `SQUARED_OFF` - All positions have been closed
- `DISABLED` - Strategy is disabled

## Data Integrity Features

### 1. Account Validation
- All tagged entities must belong to the same account as the strategy
- Cross-account tagging is prevented

### 2. Overwrite Protection
- Existing strategy tags are protected unless explicitly overwritten
- Detailed reporting of skipped vs. successful operations

### 3. Safe Deletion
- Strategies with active positions cannot be deleted
- Strategies with active orders cannot be deleted
- Comprehensive cleanup when deletion is allowed

### 4. Real-time Metrics
- Automatic calculation of P&L, margin usage, and counts
- Metrics updated on every strategy operation
- Performance tracking across strategy lifecycle

## Margin Calculation Notes

**Current Limitation:** The system does not yet have working margin calculations per strategy/position because margins are calculated based on all positions taken on an underlying. 

**Future Enhancement:** Need to implement:
- Portfolio-level margin calculation
- Strategy-specific margin allocation
- Position-level margin attribution
- Dynamic margin rebalancing

## Square-off Implementation Notes

**Current Status:** The square-off engine simulates order placement without actually placing orders through the broker API.

**Production Requirements:**
1. Integration with actual broker APIs (Zerodha, Upstox, etc.)
2. Real-time order status monitoring
3. Partial fill handling
4. Error recovery mechanisms
5. Market hours validation

## Error Handling

### Validation Errors (400)
- Invalid strategy data
- Missing required fields
- Business rule violations

### Not Found (404)
- Strategy does not exist
- Referenced entities not found

### Business Logic Errors (400)
- Cannot delete strategy with active positions
- Account mismatch in tagging operations
- Invalid strategy state transitions

### Server Errors (500)
- Database connectivity issues
- Unexpected service failures

## Usage Examples

### Complete Strategy Workflow

1. **Create Strategy**
```bash
curl -X POST "http://localhost:8004/strategies/create?created_by=trader1" \
  -H "Content-Type: application/json" \
  -d '{
    "strategy_name": "NIFTY Swing Strategy",
    "pseudo_account": "Raghu",
    "organization_id": "stocksblitz",
    "strategy_type": "SWING",
    "max_loss_amount": 50000,
    "max_profit_amount": 150000
  }'
```

2. **Tag Existing Positions**
```bash
curl -X POST "http://localhost:8004/strategies/STR_A1B2C3D4/tag-positions" \
  -H "Content-Type: application/json" \
  -d '{
    "entity_ids": ["pos_123", "pos_456"],
    "overwrite_existing": false
  }'
```

3. **Monitor Strategy**
```bash
curl "http://localhost:8004/strategies/STR_A1B2C3D4/summary"
```

4. **Square-off Strategy**
```bash
# Preview first
curl "http://localhost:8004/strategies/STR_A1B2C3D4/square-off/preview"

# Execute
curl -X POST "http://localhost:8004/strategies/STR_A1B2C3D4/square-off" \
  -H "Content-Type: application/json" \
  -d '{
    "confirm": true,
    "force_market_orders": true,
    "dry_run": true
  }'
```

## Implementation Status

✅ **Completed:**
- Strategy CRUD operations
- Entity tagging system  
- Real-time metrics calculation
- Square-off preview and simulation
- Data integrity validation
- Comprehensive error handling
- Risk management controls

🔄 **In Progress:**
- Margin calculation per strategy
- Actual broker API integration for square-off

⏳ **Future Enhancements:**
- Auto square-off scheduling
- Strategy performance analytics
- Advanced risk metrics
- Strategy templates
- Backtesting integration