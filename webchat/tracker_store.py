import json
import time
from typing import Any, Dict, List, Optional

from redis.asyncio import Redis


def _now() -> float:
    return time.time()


class RedisTrackerStore:
    """Persists conversation events and metadata for the beta handler."""

    def __init__(self, redis: Redis, ttl_seconds: int = 3600) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    @staticmethod
    def _key(conversation_id: str) -> str:
        return f"webchat:tracker:{conversation_id}"

    async def create_or_load(
        self,
        conversation_id: str,
        sender_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        raw = await self._redis.get(self._key(conversation_id))
        if raw:
            data = json.loads(raw)
            # refresh ttl
            await self._redis.expire(self._key(conversation_id), self._ttl)
            return data

        data = {
            "conversation_id": conversation_id,
            "sender_id": sender_id or conversation_id,
            "metadata": metadata or {},
            "events": [],
            "latest_input_channel": metadata.get("input_channel") if metadata else None,
            "created_at": _now(),
        }
        await self._redis.set(self._key(conversation_id), json.dumps(data), ex=self._ttl)
        return data

    async def update_metadata(self, conversation_id: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        data = await self.create_or_load(conversation_id, metadata=metadata)
        data["metadata"].update(metadata or {})
        await self._redis.set(self._key(conversation_id), json.dumps(data), ex=self._ttl)
        return data

    async def append_user_event(
        self,
        conversation_id: str,
        text: str,
        input_channel: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        data = await self.create_or_load(conversation_id, metadata=metadata)
        data["events"].append(
            {
                "event": "user",
                "text": text,
                "timestamp": _now(),
                "metadata": metadata or data.get("metadata") or {},
            }
        )
        data["latest_input_channel"] = input_channel
        await self._redis.set(self._key(conversation_id), json.dumps(data), ex=self._ttl)
        return data

    async def append_bot_events(
        self, conversation_id: str, bot_messages: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        data = await self.create_or_load(conversation_id)
        for message in bot_messages:
            payload = message.copy()
            payload.setdefault("event", "bot")
            payload.setdefault("timestamp", _now())
            data["events"].append(payload)
        await self._redis.set(self._key(conversation_id), json.dumps(data), ex=self._ttl)
        return data

    async def get_events(self, conversation_id: str) -> List[Dict[str, Any]]:
        data = await self.create_or_load(conversation_id)
        return data.get("events", [])
