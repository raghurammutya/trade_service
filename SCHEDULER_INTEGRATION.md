# Scheduler Integration for Automatic External Order Detection

## Current vs Enhanced Workflow

### **Before (Current)**
```python
# Existing sync_to_redis_task.py runs every 5-10 minutes
@celery_app.task
def sync_all_accounts_to_redis():
    # Only syncs internal data to Redis
    # No external order detection
```

### **After (Enhanced)**
```python
# New external_order_sync_task.py runs every 5-10 minutes  
@celery_app.task
def sync_all_accounts_with_external_detection():
    for each_account:
        # 1. Fetch fresh broker data
        # 2. Detect external orders automatically
        # 3. Create missing order records
        # 4. Update positions/holdings
        # 5. Sync to Redis
        # 6. Update strategy metrics
```

## Integration Steps

### **1. Update Celery Beat Schedule**

Add this to your `celery_config.py` or wherever you configure periodic tasks:

```python
# app/core/celery_config.py

from celery.schedules import crontab

app.conf.beat_schedule = {
    # Replace existing sync task with enhanced version
    'enhanced-sync-all-accounts': {
        'task': 'app.tasks.external_order_sync_task.sync_all_accounts_with_external_detection',
        'schedule': crontab(minute='*/5'),  # Every 5 minutes
    },
    
    # Keep other existing tasks
    'sync-positions-and-holdings': {
        'task': 'app.tasks.update_positions_and_holdings_task.update_all_positions',
        'schedule': crontab(minute='*/10'),
    },
    
    # Historical import can be on-demand only
    # No need to schedule historical imports
}
```

### **2. Broker API Integration Points**

Update the `get_broker_client()` function in `external_order_sync_task.py`:

```python
async def get_broker_client(pseudo_account: str):
    """Get actual broker client for the account"""
    
    # Get account's broker info from database
    account_info = get_account_broker_info(pseudo_account)
    
    if account_info.broker == 'ZERODHA':
        from your_broker_clients import ZerodhaClient
        return ZerodhaClient(
            api_key=account_info.api_key,
            access_token=account_info.access_token
        )
    elif account_info.broker == 'UPSTOX':
        from your_broker_clients import UpstoxClient
        return UpstoxClient(
            api_key=account_info.api_key,
            access_token=account_info.access_token
        )
    else:
        return None
```

### **3. Data Flow Comparison**

#### **Current Flow**
```
Timer (5 min) → sync_all_accounts_to_redis
                ↓
                TimescaleDB → Redis
                (Internal data only)
```

#### **Enhanced Flow**
```
Timer (5 min) → sync_all_accounts_with_external_detection
                ↓
                Broker APIs → Compare with TimescaleDB
                ↓
                External Orders Detected → Create Order Records
                ↓
                Update Positions/Holdings → Update Strategy Metrics
                ↓
                TimescaleDB → Redis (All data including external)
```

## Implementation Checklist

### **Phase 1: Basic Integration** ✅
- [x] Enhanced sync task created
- [x] External order detector implemented
- [x] Integration with existing Redis sync
- [x] Manual trigger endpoint for testing

### **Phase 2: Broker API Integration** (Next)
- [ ] Replace `get_broker_client()` with actual broker factory
- [ ] Implement `fetch_broker_data()` with real API calls
- [ ] Add error handling for broker API failures
- [ ] Test with real broker data

### **Phase 3: Production Deployment**
- [ ] Update Celery beat schedule
- [ ] Monitor external order detection alerts
- [ ] Set up notifications for external orders
- [ ] Performance optimization for large accounts

## Testing the Integration

### **1. Test Manual Trigger**
```bash
# Trigger enhanced sync manually
curl -X POST "http://localhost:8004/external/trigger-sync?pseudo_account=Raghu&organization_id=stocksblitz"
```

### **2. Monitor External Orders**
```bash
# Check detected external orders
curl "http://localhost:8004/external/external-orders/Raghu?organization_id=stocksblitz&days=1"
```

### **3. Check Unassigned Orders**
```bash
# Orders that couldn't be auto-assigned to strategies
curl "http://localhost:8004/external/unassigned-orders/Raghu?organization_id=stocksblitz"
```

## Error Handling & Monitoring

### **Broker API Failures**
```python
# In fetch_broker_data()
try:
    orders = await broker_client.orders()
except BrokerAPIError as e:
    logger.error(f"Broker API failed: {e}")
    # Continue with cached data or skip this cycle
    return previous_data_or_empty
```

### **External Order Alerts**
```python
# In external_order_detector.py
if external_orders_detected > 0:
    # Send notification
    await send_alert(
        f"🚨 {external_orders_detected} external orders detected for {account}",
        orders=external_orders
    )
```

### **Performance Monitoring**
- Track sync task execution time
- Monitor broker API response times
- Alert on external order detection spikes
- Database performance for large accounts

## Configuration Options

Add these to your settings for tuning:

```python
# Settings for external order detection
EXTERNAL_ORDER_DETECTION_ENABLED = True
EXTERNAL_ORDER_SYNC_INTERVAL_MINUTES = 5
EXTERNAL_ORDER_CONFIDENCE_THRESHOLD = 70.0
AUTO_CREATE_EXTERNAL_STRATEGY = True
EXTERNAL_ORDER_NOTIFICATION_ENABLED = True

# Broker API settings
BROKER_API_TIMEOUT_SECONDS = 30
BROKER_API_RETRY_ATTEMPTS = 3
BROKER_API_RATE_LIMIT_DELAY = 1.0
```

## Summary

**Automatic Detection**: External orders are detected every 5-10 minutes without any manual intervention.

**Zero Manual Effort**: Once broker APIs are connected, the system automatically:
1. Detects external orders
2. Creates order records with events
3. Assigns to strategies (where possible)
4. Updates positions and holdings
5. Syncs to Redis for frontend

**Monitoring**: Endpoints provided for monitoring detected external orders and manual assignment of unassigned orders.

The system treats external orders exactly like internal orders - they get the same order events, strategy assignments, and data flow.