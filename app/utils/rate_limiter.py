# app/utils/rate_limiter.py
import time
import logging
import asyncio
from typing import Optional, Any

logger = logging.getLogger(__name__)

class RateLimiter:
    def __init__(self, redis_client: Optional[Any] = None):
        self.redis_client = redis_client
        self._enabled = redis_client is not None
        self._connection_retries = 3
        
        if not self._enabled:
            logger.warning("Rate limiter initialized without Redis - rate limiting disabled")
    
    async def _ensure_connection(self) -> bool:
        """Ensure Redis connection is alive, attempt reconnection if needed"""
        if not self.redis_client:
            return False
            
        try:
            # Test connection with a quick ping
            await asyncio.wait_for(self.redis_client.ping(), timeout=2.0)
            return True
        except Exception as e:
            logger.warning(f"Redis connection test failed: {e}")
            return False
    
    async def _execute_with_retry(self, operation_func, *args, **kwargs):
        """Execute Redis operation with retry logic"""
        for attempt in range(self._connection_retries):
            try:
                if not await self._ensure_connection():
                    logger.warning(f"Redis connection not available (attempt {attempt + 1})")
                    if attempt < self._connection_retries - 1:
                        await asyncio.sleep(0.5 * (attempt + 1))  # Exponential backoff
                        continue
                    else:
                        return None
                
                return await operation_func(*args, **kwargs)
                
            except Exception as e:
                logger.warning(f"Redis operation failed (attempt {attempt + 1}): {e}")
                if attempt < self._connection_retries - 1:
                    await asyncio.sleep(0.5 * (attempt + 1))  # Exponential backoff
                    continue
                else:
                    logger.error(f"All Redis retry attempts failed: {e}")
                    return None
        
        return None
    
    async def user_rate_limit(self, user_id: str, organization_id: str, limit: int = 100, window: int = 60) -> bool:
        """Check if user is within rate limits"""
        if not self._enabled or not self.redis_client:
            logger.debug("Rate limiting disabled - allowing request")
            return True
        
        async def _rate_limit_operation():
            if not self.redis_client:
                return True
                
            key = f"rate_limit:user:{organization_id}:{user_id}"
            current_time = int(time.time())
            window_start = current_time - window
            
            # Use pipeline for atomic operations
            pipe = self.redis_client.pipeline()
            
            # Remove old entries
            pipe.zremrangebyscore(key, 0, window_start)
            
            # Count current requests in window
            pipe.zcard(key)
            
            # Add current request
            pipe.zadd(key, {str(current_time): current_time})
            
            # Set expiry
            pipe.expire(key, window)
            
            results = await pipe.execute()
            
            current_count = results[1]  # Result of zcard
            
            if current_count >= limit:
                logger.warning(f"Rate limit exceeded for user {user_id} in org {organization_id}: {current_count}/{limit}")
                return False
                
            return True
        
        try:
            result = await self._execute_with_retry(_rate_limit_operation)
            if result is None:
                # Redis operation failed, allow request (fail open)
                logger.warning("Rate limit check failed, allowing request")
                return True
            return result
        except Exception as e:
            logger.error(f"Unexpected error in user_rate_limit: {e}")
            # On any error, allow the request (fail open)
            return True
    
    async def account_rate_limit(self, user_id: str, organization_id: str, limit: int = 1000, window: int = 60) -> bool:
        """Check if account/organization is within rate limits"""
        if not self._enabled or not self.redis_client:
            logger.debug("Rate limiting disabled - allowing request")
            return True
        
        async def _rate_limit_operation():
            if not self.redis_client:
                return True
                
            key = f"rate_limit:account:{organization_id}"
            current_time = int(time.time())
            window_start = current_time - window
            
            # Use pipeline for atomic operations
            pipe = self.redis_client.pipeline()
            
            # Remove old entries
            pipe.zremrangebyscore(key, 0, window_start)
            
            # Count current requests in window
            pipe.zcard(key)
            
            # Add current request
            pipe.zadd(key, {f"{user_id}:{current_time}": current_time})
            
            # Set expiry
            pipe.expire(key, window)
            
            results = await pipe.execute()
            
            current_count = results[1]  # Result of zcard
            
            if current_count >= limit:
                logger.warning(f"Rate limit exceeded for account {organization_id}: {current_count}/{limit}")
                return False
                
            return True
        
        try:
            result = await self._execute_with_retry(_rate_limit_operation)
            if result is None:
                # Redis operation failed, allow request (fail open)
                logger.warning("Rate limit check failed, allowing request")
                return True
            return result
        except Exception as e:
            logger.error(f"Unexpected error in account_rate_limit: {e}")
            # On any error, allow the request (fail open)
            return True