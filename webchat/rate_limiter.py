from redis.asyncio import Redis


class RedisRateLimiter:
    """Simple token bucket stored in Redis."""

    def __init__(self, redis: Redis, max_requests: int, window_seconds: int) -> None:
        self._redis = redis
        self._max = max_requests
        self._window = window_seconds

    def _key(self, sender_id: str) -> str:
        return f"webchat:rate:{sender_id}"

    async def allow(self, sender_id: str) -> bool:
        key = self._key(sender_id)
        current = await self._redis.incr(key)
        if current == 1:
            await self._redis.expire(key, self._window)
        return current <= self._max
