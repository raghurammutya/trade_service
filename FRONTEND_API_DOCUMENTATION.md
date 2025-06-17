# Trade Service API Documentation for React Frontend

## Base URL
```
http://localhost:8004
```

## 🔍 Redis Data Endpoints (For Current State - Fast Access)

### 1. Account Summary
Get complete account overview including all strategies and data:
```http
GET /data/account/{organization_id}/{pseudo_account}/summary
```

**Example:**
```bash
curl "http://localhost:8004/data/account/stocksblitz/Raghu/summary"
```

**Response:**
```json
{
  "positions": [...],
  "holdings": [...],
  "margins": [...],
  "orders": [...],
  "strategies": ["default", "batman", "iron_condor"],
  "strategy_data": {
    "default": {...},
    "batman": {...}
  }
}
```

### 2. Positions
Get real-time positions data:
```http
GET /data/account/{organization_id}/{pseudo_account}/positions
```

**Query Parameters:**
- `strategy_id` (optional): Filter by specific strategy

**Example:**
```bash
curl "http://localhost:8004/data/account/stocksblitz/Raghu/positions"
curl "http://localhost:8004/data/account/stocksblitz/Raghu/positions?strategy_id=batman"
```

**Response:**
```json
{
  "count": 8,
  "positions": [
    {
      "id": 272,
      "instrument_key": "NFO@NIFTY25JUN25000CE@options@25-JUN-2025@CE@25000",
      "symbol": "NIFTY25JUN25000CE",
      "exchange": "NFO",
      "direction": "LONG",
      "net_quantity": 750,
      "buy_quantity": 750,
      "sell_quantity": 0,
      "buy_avg_price": 139.45,
      "sell_avg_price": 0.0,
      "ltp": 165.6,
      "pnl": 18937.5,
      "unrealised_pnl": 18937.5,
      "realised_pnl": 0.0,
      "platform": "KITE",
      "stock_broker": "Zerodha",
      "strategy_id": null,
      "state": "OPEN"
    }
  ]
}
```

### 3. Holdings
Get current holdings:
```http
GET /data/account/{organization_id}/{pseudo_account}/holdings
```

**Query Parameters:**
- `strategy_id` (optional): Filter by specific strategy

**Example:**
```bash
curl "http://localhost:8004/data/account/stocksblitz/Raghu/holdings"
```

**Response:**
```json
{
  "count": 13,
  "holdings": [
    {
      "symbol": "867PFCL33",
      "instrument_key": "BSE@PFC@bonds",
      "exchange": "BSE",
      "quantity": 650,
      "avg_price": 1000.0,
      "ltp": 964.5,
      "current_value": 626925.0,
      "pnl": -23075.0,
      "platform": "KITE",
      "stock_broker": "Zerodha"
    }
  ]
}
```

### 4. Orders
Get order history and status:
```http
GET /data/account/{organization_id}/{pseudo_account}/orders
```

**Query Parameters:**
- `strategy_id` (optional): Filter by specific strategy
- `status` (optional): Filter by order status (OPEN, COMPLETE, CANCELLED, etc.)

**Example:**
```bash
curl "http://localhost:8004/data/account/stocksblitz/Raghu/orders?status=OPEN"
```

### 5. Margins
Get margin information:
```http
GET /data/account/{organization_id}/{pseudo_account}/margins
```

**Example:**
```bash
curl "http://localhost:8004/data/account/stocksblitz/Raghu/margins"
```

**Response:**
```json
{
  "count": 3,
  "margins": [
    {
      "category": "EQUITY",
      "available": 2653341.8,
      "utilized": 11078807.0,
      "total": 22955180.0,
      "funds": 9230313.0,
      "collateral": 13724868.0,
      "stock_broker": "Zerodha"
    }
  ]
}
```

### 6. Strategies
Get list of all strategies:
```http
GET /data/account/{organization_id}/{pseudo_account}/strategies
```

### 7. Strategy-Specific Data
Get all data for a specific strategy:
```http
GET /data/strategy/{organization_id}/{pseudo_account}/{strategy_id}
```

## 📊 Trade Execution Endpoints

### 1. Regular Order
Place a regular buy/sell order:
```http
POST /trades/execute
```

**Request Body:**
```json
{
  "pseudo_account": "Raghu",
  "exchange": "NSE",
  "symbol": "RELIANCE",
  "tradeType": "BUY",
  "orderType": "LIMIT",
  "productType": "MIS",
  "quantity": 10,
  "price": 2500.0,
  "triggerPrice": 0.0,
  "strategy_id": "default",
  "organization_id": "stocksblitz"
}
```

### 2. Cover Order
Place a cover order (with automatic stop loss):
```http
POST /trades/cover_order
```

### 3. Bracket Order
Place a bracket order (with target and stop loss):
```http
POST /trades/bracket_order
```

**Request Body:**
```json
{
  "pseudo_account": "Raghu",
  "exchange": "NSE", 
  "instrument_key": "RELIANCE",
  "tradeType": "BUY",
  "orderType": "LIMIT",
  "productType": "BO",
  "quantity": 10,
  "price": 2500.0,
  "target": 2600.0,
  "stoploss": 2400.0,
  "strategy_id": "default",
  "organization_id": "stocksblitz"
}
```

### 4. Order Management

#### Modify Order
```http
PUT /trades/modify_order/{platform_id}
```

#### Cancel Order
```http
DELETE /trades/cancel_order/{platform_id}
```

#### Cancel All Orders
```http
DELETE /trades/cancel_all_orders?pseudo_account={pseudo_account}&organization_id={organization_id}
```

#### Square Off Position
```http
POST /trades/square_off_position
```

**Request Body:**
```json
{
  "pseudo_account": "Raghu",
  "instrument_key": "NSE@RELIANCE@equities",
  "quantity": 10,
  "organization_id": "stocksblitz",
  "strategy_id": "default"
}
```

## 🔄 Data Management Endpoints

### 1. Refresh Data
Force refresh from broker:
```http
POST /trades/fetch_and_store/{pseudo_account}?organization_id={organization_id}
```

### 2. Sync to Redis
Force sync from database to Redis:
```http
POST /data/sync/{organization_id}/{pseudo_account}
```

### 3. Clear Cache
Clear Redis cache:
```http
DELETE /data/cache/{organization_id}/{pseudo_account}
```

## 🎯 Best Practices for React Frontend

### 1. Data Fetching Strategy
- **For Real-time UI**: Use Redis endpoints (`/data/*`) for fast access
- **For Order Execution**: Use trade endpoints (`/trades/*`)
- **For Refresh**: Use fetch_and_store then Redis endpoints

### 2. Recommended Data Flow
```javascript
// 1. Initial load - get account summary
const summary = await fetch('/data/account/stocksblitz/Raghu/summary');

// 2. Get specific data with filters
const openOrders = await fetch('/data/account/stocksblitz/Raghu/orders?status=OPEN');
const batmanPositions = await fetch('/data/account/stocksblitz/Raghu/positions?strategy_id=batman');

// 3. Place orders
const orderResult = await fetch('/trades/execute', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(orderData)
});

// 4. Refresh data after order placement
await fetch('/trades/fetch_and_store/Raghu?organization_id=stocksblitz', { method: 'POST' });
```

### 3. Error Handling
All endpoints return standard HTTP status codes:
- `200`: Success
- `400`: Bad Request (invalid parameters)
- `404`: Not Found (no data)
- `429`: Rate Limited
- `500`: Server Error

### 4. Data Formats
- **Timestamps**: ISO 8601 format with timezone
- **Numbers**: Floats for prices, integers for quantities
- **Status**: String enums (OPEN, COMPLETE, CANCELLED, etc.)
- **Symbols**: Both original symbol and instrument_key provided

### 5. Real-time Updates
Consider implementing WebSocket or polling for real-time updates:
```javascript
// Poll every 30 seconds for position updates
setInterval(async () => {
  const positions = await fetch('/data/account/stocksblitz/Raghu/positions');
  updateUI(positions);
}, 30000);
```

## 📋 Frontend Implementation Example

```javascript
class TradingService {
  constructor(baseUrl = 'http://localhost:8004') {
    this.baseUrl = baseUrl;
  }

  // Get account overview
  async getAccountSummary(orgId, userId) {
    const response = await fetch(`${this.baseUrl}/data/account/${orgId}/${userId}/summary`);
    return await response.json();
  }

  // Get positions with optional strategy filter
  async getPositions(orgId, userId, strategyId = null) {
    const url = `${this.baseUrl}/data/account/${orgId}/${userId}/positions`;
    const params = strategyId ? `?strategy_id=${strategyId}` : '';
    const response = await fetch(url + params);
    return await response.json();
  }

  // Place regular order
  async placeOrder(orderData) {
    const response = await fetch(`${this.baseUrl}/trades/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(orderData)
    });
    return await response.json();
  }

  // Cancel order
  async cancelOrder(platformId) {
    const response = await fetch(`${this.baseUrl}/trades/cancel_order/${platformId}`, {
      method: 'DELETE'
    });
    return await response.json();
  }

  // Refresh data
  async refreshData(orgId, userId) {
    const response = await fetch(`${this.baseUrl}/trades/fetch_and_store/${userId}?organization_id=${orgId}`, {
      method: 'POST'
    });
    return await response.json();
  }
}
```

This API provides comprehensive access to all trading data and operations needed for your React frontend.