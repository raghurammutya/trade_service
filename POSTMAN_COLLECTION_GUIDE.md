# Trade Service API - Postman Collection Guide

## Overview
This comprehensive Postman collection contains all endpoints for testing the Trade Service API with realistic sample data and proper configurations.

## Quick Setup

### 1. Import the Collection
1. Open Postman
2. Click "Import" → "Upload Files"
3. Select `Trade_Service_API_Collection.postman_collection.json`
4. Click "Import"

### 2. Configure Variables
The collection includes pre-configured variables. Update these as needed:

| Variable | Default | Description |
|----------|---------|-------------|
| `base_url` | `http://localhost:8000` | API base URL |
| `organization_id` | `ORG001` | Your organization ID |
| `pseudo_account` | `XJ4540` | Trading account identifier |
| `strategy_id` | `strategy-123` | Strategy identifier (auto-generated) |
| `platform_id` | `order-123` | Order identifier (auto-generated) |

### 3. Environment Setup
For different environments, create separate environments:
- **Local**: `http://localhost:8000`
- **Development**: `http://dev-api.yourdomain.com`
- **Production**: `http://api.yourdomain.com`

## Collection Structure

### 📊 Health & Status
- **Health Check**: Basic service health
- **System Status**: Comprehensive system status

### 🔄 Redis Data Endpoints
- **Get All Orders**: Retrieve cached orders
- **Get All Positions**: Retrieve cached positions
- **Get All Holdings**: Retrieve cached holdings
- **Get All Margins**: Retrieve cached margins

### 💰 Trade Operations
- **Fetch All Trading Users**: Get all trading accounts
- **Fetch and Store Account Data**: Sync account data
- **Place Regular Order - Equity**: Place equity orders
- **Place Regular Order - Options**: Place options orders
- **Place Advanced Order**: Advanced order with all parameters
- **Place Bracket Order**: Bracket orders with target/SL
- **Modify Order**: Modify existing orders
- **Cancel Order**: Cancel specific orders
- **Cancel All Orders**: Cancel all pending orders
- **Square Off Position**: Square off specific positions
- **Square Off Portfolio**: Square off entire portfolio

### 🎯 Strategy Management
- **Create Strategy**: Create new trading strategies
- **List All Strategies**: Get all strategies
- **Get Strategy Details**: Detailed strategy information
- **Tag Positions to Strategy**: Associate positions with strategies
- **Square Off Strategy**: Close strategy positions
- **Update Strategy Status**: Change strategy status

### 📋 Ledger Management
- **Upload Ledger File**: Upload Excel ledger files
- **Get Ledger Entries**: Retrieve ledger entries

### 📈 Historical Import
- **Import Historical Tradebook**: Import individual tradebook files
- **Import All Historical Files**: Batch import from directory
- **Get Import Status**: Check import progress

### 🔄 Position Generation
- **Generate Positions from Orders**: Reconstruct positions from order history
- **Generate Holdings from Positions**: Convert positions to holdings
- **Comprehensive Position Generation**: Full position/holding generation

### 🔍 External Order Detection
- **Detect External Orders**: Find orders placed outside the system
- **Get External Order Status**: Check detection status

### 📊 Query Endpoints
- **Get Orders by Organization and User**: Query orders
- **Get Positions by Organization and User**: Query positions
- **Get Holdings by Organization and User**: Query holdings
- **Get Margins by Organization and User**: Query margins
- **Get Orders/Positions/Holdings by Strategy**: Strategy-specific queries

### 🔧 Infrastructure & Testing
- **Test Redis Connection**: Test Redis connectivity
- **Infrastructure Health Check**: System health overview
- **Get Trade Status**: Check specific trade status

## Sample Test Flows

### 🚀 Complete Trading Workflow
1. **Health Check** → Verify service is running
2. **Fetch All Trading Users** → Get available accounts
3. **Fetch and Store Account Data** → Sync latest data
4. **Create Strategy** → Set up trading strategy
5. **Place Regular Order** → Place test order
6. **Tag Positions to Strategy** → Associate with strategy
7. **Modify Order** → Test order modification
8. **Cancel Order** → Test order cancellation

### 📊 Data Verification Workflow
1. **Get All Orders** → Check cached data
2. **Get Orders by Organization and User** → Verify database data
3. **Generate Positions from Orders** → Test position generation
4. **Get All Positions** → Verify generated positions

### 📈 Historical Data Workflow
1. **Import Historical Tradebook** → Load historical data
2. **Generate Comprehensive** → Reconstruct positions/holdings
3. **Detect External Orders** → Find external trades
4. **Get Import Status** → Verify completion

## Key Testing Tips

### 🛡️ Safety Measures
- **Low Quantities**: Always use quantity = 1 for equity, 25 for options
- **AMO Flag**: Set `"amo": true` for after-market testing
- **Test Symbols**: Use liquid stocks like RELIANCE, TCS, INFY

### 🔧 Pre-Execution Scripts
The collection includes automatic:
- Timestamp generation
- Random ID generation for orders/strategies
- Variable extraction from responses

### ✅ Test Scripts
Each request includes:
- Status code validation
- Response logging for debugging
- Automatic ID extraction and storage

### 🐛 Debugging
- Check Console tab for detailed logs
- Response bodies are logged for troubleshooting
- Status codes and timing information available

## Common Use Cases

### 🏁 Getting Started
```bash
1. Health Check
2. Fetch All Trading Users
3. Fetch and Store Account Data (for your pseudo_account)
4. Get All Orders/Positions/Holdings/Margins
```

### 🎯 Strategy Testing
```bash
1. Create Strategy
2. Place Regular Order - Equity
3. Tag Positions to Strategy
4. Get Strategy Details
5. Square Off Strategy
```

### 📊 Data Management
```bash
1. Upload Ledger File
2. Import Historical Tradebook
3. Generate Comprehensive Positions
4. Detect External Orders
```

### 🔧 Infrastructure Testing
```bash
1. Infrastructure Health Check
2. Test Redis Connection
3. System Status
```

## Error Handling

### Common Issues
- **Connection Errors**: Check base_url variable
- **Authentication**: Ensure organization_id is correct
- **Data Not Found**: Run fetch_and_store first
- **Order Failures**: Verify account has sufficient margin

### Status Codes
- **200**: Success
- **201**: Created
- **400**: Bad Request (check payload)
- **404**: Not Found (check IDs)
- **500**: Internal Server Error (check logs)

## Production Notes

### 🚨 Safety Reminders
1. **Never test on production** during market hours
2. **Use AMO orders** for after-market testing
3. **Start with paper trading** accounts
4. **Monitor margin requirements**
5. **Keep quantities minimal**

### 📊 Monitoring
- Check system health before trading
- Monitor Redis connection status
- Verify data sync completion
- Watch for external order detection

## Support

For issues:
1. Check Postman Console for detailed error logs
2. Verify variable values are correct
3. Test health endpoints first
4. Check service logs for backend errors

---

**Happy Testing! 🚀**

This collection provides comprehensive coverage of all Trade Service functionality with realistic test data and proper safety measures.