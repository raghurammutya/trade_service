# Redis Connection Issue Analysis

## Problem Summary
The modify_order and cancel_order endpoints are failing with:
```
Error -3 connecting to redis:6379. Temporary failure in name resolution.
```

## Root Cause
While the TradeService correctly uses the connection manager with service discovery, there are multiple places where Redis connections are hardcoded to use `redis:6379`, bypassing the service discovery mechanism:

### 1. Celery Configuration (Primary Issue)
**File**: `/home/stocksadmin/stocksblitz/trade_service/app/core/celery_config.py`

The Celery broker and backend are hardcoded:
```python
redis_host = "redis"
redis_broker_url = f"redis://{redis_host}:6379/0"
redis_backend_url = f"redis://{redis_host}:6379/0"
```

This causes Celery tasks to attempt direct connections to `redis:6379` instead of using service discovery.

### 2. Resilient Connection Manager
**File**: `/home/stocksadmin/stocksblitz/trade_service/app/utils/resilient_connection_manager.py`

The primary Redis host defaults to "redis":
```python
primary_host=os.getenv("REDIS_HOST", "redis"),
```

### 3. Environment Files
- `.env` and `.env.production` contain:
  ```
  CELERY_BROKER_URL=redis://redis:6379/0
  CELERY_RESULT_BACKEND=redis://redis:6379/0
  ```

## Connection Flow Analysis

1. **TradeService Initialization** (Working correctly):
   - Uses `connection_manager.get_redis_connection()`
   - This calls `redis_client.py` which uses service discovery
   - Service discovery resolves the hostname based on environment

2. **Celery Task Execution** (Failing):
   - When endpoints like `modify_order_by_platform_id` are called
   - They create an order and call `celery_app.send_task('process_order_task', ...)`
   - Celery tries to connect to its broker at `redis://redis:6379/0`
   - This bypasses service discovery and fails with DNS resolution error

## Service Discovery Details
The service discovery system (in `shared_architecture/connections/service_discovery.py`):
- Detects environment (local/docker/kubernetes)
- For local environment: converts service names to "localhost"
- For docker/kubernetes: uses service names as-is

## Why It's Failing
1. The environment is likely set to "local" or not properly detected
2. Celery is trying to connect to hostname "redis" which doesn't exist in local DNS
3. Service discovery is not being used for Celery's Redis connections

## Required Fixes

### 1. Fix Celery Configuration
Update `celery_config.py` to use service discovery:
```python
from shared_architecture.connections.service_discovery import service_discovery, ServiceType

# Get the resolved Redis host
redis_host = service_discovery.resolve_service_host(
    os.getenv("REDIS_HOST", "redis"), 
    ServiceType.REDIS
)
redis_port = int(os.getenv("REDIS_PORT", "6379"))

redis_broker_url = f"redis://{redis_host}:{redis_port}/0"
redis_backend_url = f"redis://{redis_host}:{redis_port}/0"
```

### 2. Update Resilient Connection Manager
Use service discovery for the primary host resolution:
```python
from shared_architecture.connections.service_discovery import service_discovery, ServiceType

redis_host_config = os.getenv("REDIS_HOST", "redis")
resolved_host = service_discovery.resolve_service_host(redis_host_config, ServiceType.REDIS)

redis_config = ConnectionConfig(
    name="redis",
    primary_host=resolved_host,
    primary_port=int(os.getenv("REDIS_PORT", "6379")),
    # ... rest of config
)
```

### 3. Environment Variables
Update environment files to use localhost for local development:
```
REDIS_HOST=localhost
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
```

## Verification
The issue can be verified by:
1. Checking if `redis` hostname resolves: `nslookup redis`
2. Testing connection: `redis-cli -h redis ping`
3. Checking Celery worker logs for connection errors

## Temporary Workaround
Add to `/etc/hosts`:
```
127.0.0.1 redis
```

But the proper fix is to use service discovery consistently across all components.