"""
Deprecated: Use shared_architecture.resilience.rate_limiter instead.

This module is kept for backward compatibility.
"""

import warnings
from shared_architecture.resilience.rate_limiter import (
    get_rate_limiter_manager,
    RateLimitConfig,
    RateLimitAlgorithm
)

warnings.warn(
    "app.utils.rate_limiter is deprecated. "
    "Use shared_architecture.resilience.rate_limiter instead.",
    DeprecationWarning,
    stacklevel=2
)

class RateLimiter:
    """
    Deprecated rate limiter implementation.
    
    Use shared_architecture.resilience.rate_limiter.get_rate_limiter_manager() instead.
    """
    
    def __init__(self, redis_client=None):
        warnings.warn(
            "RateLimiter class is deprecated. Use shared_architecture.resilience.rate_limiter instead.",
            DeprecationWarning,
            stacklevel=2
        )
        self.manager = get_rate_limiter_manager()
        
        # Set up default limiters if they don't exist
        if not self.manager.get_limiter("user_requests"):
            user_config = RateLimitConfig(
                name="user_requests",
                requests_per_window=100,
                window_size=60,
                algorithm=RateLimitAlgorithm.SLIDING_WINDOW
            )
            self.manager.add_limiter(user_config)
        
        if not self.manager.get_limiter("account_requests"):
            account_config = RateLimitConfig(
                name="account_requests", 
                requests_per_window=1000,
                window_size=60,
                algorithm=RateLimitAlgorithm.SLIDING_WINDOW
            )
            self.manager.add_limiter(account_config)
    
    async def user_rate_limit(self, user_id: str, organization_id: str, limit: int = 100, window: int = 60) -> bool:
        """Check if user is within rate limits."""
        try:
            key = self.manager.create_key(user_id, "", organization_id)
            limiter = self.manager.get_limiter("user_requests")
            if limiter:
                result = await limiter.check_rate_limit(key)
                return result.allowed
            return True
        except Exception:
            # Fail open on errors
            return True
    
    async def account_rate_limit(self, user_id: str, organization_id: str, limit: int = 1000, window: int = 60) -> bool:
        """Check if account/organization is within rate limits."""
        try:
            key = organization_id
            limiter = self.manager.get_limiter("account_requests")
            if limiter:
                result = await limiter.check_rate_limit(key)
                return result.allowed
            return True
        except Exception:
            # Fail open on errors
            return True