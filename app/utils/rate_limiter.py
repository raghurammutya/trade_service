# trade_service/app/utils/rate_limiter.py
from redis import Redis
import time
from app.core.config import settings

class RateLimiter:
    def __init__(self, redis_conn: Redis):
        self.redis = redis_conn

    def user_rate_limit(self, user_id: str, organization_id: str) -> bool:
        """
        Applies user-level rate limiting, scoped to the organization.
        """
        now = time.time()
        pipe = self.redis.pipeline()
        pipe.zremrangebyscore(f"org:{organization_id}:user:{user_id}:5s", 0, now - 5)
        pipe.zcard(f"org:{organization_id}:user:{user_id}:5s")
        pipe.zadd(f"org:{organization_id}:user:{user_id}:5s", {now: now})
        requests_5s, _ = pipe.execute()
        if requests_5s > settings.user_rate_limit_5s:
            return False

        pipe = self.redis.pipeline()
        pipe.zremrangebyscore(f"org:{organization_id}:user:{user_id}:1m", 0, now - 60)
        pipe.zcard(f"org:{organization_id}:user:{user_id}:1m")
        pipe.zadd(f"org:{organization_id}:user:{user_id}:1m", {now: now})
        requests_1m, _ = pipe.execute()

        if requests_1m > settings.user_rate_limit_1m:
            return False

        return True

    def account_rate_limit(self, account_id: str, organization_id: str) -> bool:
        """
        Applies account-level rate limiting, scoped to the organization.
        """
        now = time.time()

        pipe = self.redis.pipeline()
        pipe.zremrangebyscore(f"org:{organization_id}:account:{account_id}:5s", 0, now - 5)
        pipe.zcard(f"org:{organization_id}:account:{account_id}:5s")
        pipe.zadd(f"org:{organization_id}:account:{account_id}:5s", {now: now})
        requests_5s, _ = pipe.execute()

        if requests_5s > settings.account_rate_limit_5s:
            return False

        pipe = self.redis.pipeline()
        pipe.zremrangebyscore(f"org:{organization_id}:account:{account_id}:1m", 0, now - 60)
        pipe.zcard(f"org:{organization_id}:account:{account_id}:1m")
        pipe.zadd(f"org:{organization_id}:account:{account_id}:1m", {now: now})
        requests_1m, _ = pipe.execute()

        if requests_1m > settings.account_rate_limit_1m:
            return False

        pipe = self.redis.pipeline()
        pipe.zremrangebyscore(f"org:{organization_id}:account:{account_id}:5m", 0, now - 300)
        pipe.zcard(f"org:{organization_id}:account:{account_id}:5m")
        pipe.zadd(f"org:{organization_id}:account:{account_id}:5m", {now: now})
        requests_5m, _ = pipe.execute()

        if requests_5m > settings.account_rate_limit_5m:
            return False

        return True