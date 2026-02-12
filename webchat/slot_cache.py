"""Redis-based slot caching to reduce database load."""
import json
import logging
from typing import Any, Dict, Optional

from redis.asyncio import Redis

from db_utils import get_db_all, get_db_row

logger = logging.getLogger(__name__)


class SlotCache:
    """Cache slots in Redis to minimize database hits."""

    def __init__(self, redis: Redis, ttl_seconds: int = 3600) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    @staticmethod
    def _key(sender_id: str) -> str:
        return f"webchat:slots:{sender_id}"

    async def get_slots(self, sender_id: str) -> Dict[str, Any]:
        """Retrieve slots from cache or database."""
        cached = await self._redis.get(self._key(sender_id))
        if cached:
            logger.debug("Slots cache hit for %s", sender_id)
            return json.loads(cached)
        logger.debug("Slots cache miss for %s, loading from DB", sender_id)
        tmp_query = await get_db_all(
            "SELECT * FROM events_slots WHERE sender_id = %s", [sender_id]
        )

        slots = {}
        if tmp_query is not None:
            for _slot in tmp_query:
                slots[_slot["key2find"]] = _slot["value"]

        await self._redis.set(self._key(sender_id), json.dumps(slots), ex=self._ttl)
        return slots

    async def set_slot(self, sender_id: str, key: str, value: Any) -> None:
        """Persist slot to database and update cache."""
        await get_db_row(
            """INSERT INTO events_slots (sender_id, key2find, value) 
               VALUES (%s, %s, %s)
               ON DUPLICATE KEY UPDATE value = %s""",
            [sender_id, key, value, value],
        )
        slots = await self.get_slots(sender_id)
        slots[key] = value
        await self._redis.set(self._key(sender_id), json.dumps(slots), ex=self._ttl)

    async def reset_slots(self, sender_id: str) -> None:
        """Clear all slots for a sender."""
        await get_db_row("DELETE FROM events_slots WHERE sender_id = %s", [sender_id])
        await self._redis.delete(self._key(sender_id))

    async def invalidate(self, sender_id: str) -> None:
        """Invalidate cache for a sender (force reload on next access)."""
        await self._redis.delete(self._key(sender_id))
