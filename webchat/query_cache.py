"""Query result caching to reduce database load."""
import hashlib
import json
import logging
from typing import Any, Dict, List, Optional

from redis.asyncio import Redis

from db_utils import get_db_all, get_db_row

logger = logging.getLogger(__name__)


class QueryCache:
    """Cache database query results in Redis."""

    def __init__(self, redis: Redis, ttl_seconds: int = 300) -> None:
        """Initialize query cache."""
        self._redis = redis
        self._ttl = ttl_seconds

    @staticmethod
    def _make_key(sql: str, params: List[Any]) -> str:
        """Generate cache key from SQL and parameters."""
        query_str = f"{sql}:{json.dumps(params, sort_keys=True)}"
        hash_val = hashlib.md5(query_str.encode()).hexdigest()
        return f"webchat:qcache:{hash_val}"

    async def get_cached_row(
        self, sql: str, params: List[Any], ttl: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """Get a single row with caching."""
        cache_key = self._make_key(sql, params)
        cached = await self._redis.get(cache_key)
        if cached:
            logger.debug("Query cache hit: %s", sql[:50])
            return json.loads(cached) if cached != "null" else None
        logger.debug("Query cache miss: %s", sql[:50])
        result = await get_db_row(sql, params)
        cache_ttl = ttl if ttl is not None else self._ttl
        await self._redis.set(
            cache_key,
            json.dumps(result) if result else "null",
            ex=cache_ttl
        )
        return result

    async def get_cached_all(
        self, sql: str, params: List[Any], ttl: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get all rows with caching."""
        cache_key = self._make_key(sql, params)
        cached = await self._redis.get(cache_key)
        if cached:
            logger.debug("Query cache hit: %s", sql[:50])
            return json.loads(cached)
        logger.debug("Query cache miss: %s", sql[:50])
        result = await get_db_all(sql, params)
        cache_ttl = ttl if ttl is not None else self._ttl
        await self._redis.set(
            cache_key,
            json.dumps(result),
            ex=cache_ttl
        )
        return result

    async def invalidate_pattern(self, pattern: str) -> int:
        """Invalidate all cache keys matching a pattern."""
        cursor = 0
        deleted = 0
        while True:
            cursor, keys = await self._redis.scan(cursor, match=pattern, count=100)
            if keys:
                deleted += await self._redis.delete(*keys)
            if cursor == 0:
                break
        return deleted

    async def clear_all(self) -> int:
        """Clear all query cache entries."""
        return await self.invalidate_pattern("webchat:qcache:*")
