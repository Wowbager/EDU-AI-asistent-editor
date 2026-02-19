import logging
import secrets
import asyncio
from typing import Optional
from contextlib import asynccontextmanager
from redis.asyncio import Redis
from redis.exceptions import RedisError
from ai_config import AIModelConfig


logger = logging.getLogger(__name__)

class GlobalRateLimiter:
    def __init__(self, redis_url="redis://redis:6379/3"):
        self.redis_url = redis_url
        self.redis = None
        # Models sorted by capacity (highest capacity first)
        # Keys are the *upper bound* of requests for that model tier
        base = 10
        default_model = AIModelConfig.CHAT_MODEL
        self.models_by_traffic = {
            base: default_model,
            base * 5: default_model,
            base * 10: default_model,
        }
        # Sort thresholds for reliable iteration
        self._sorted_thresholds = sorted(self.models_by_traffic.keys())
        # Define max_requests based on the highest threshold
        self.max_requests = self._sorted_thresholds[-1] * 2 if self._sorted_thresholds else 0
        self.window_seconds = 10
        self._connection_lock = asyncio.Lock() # Prevent race conditions during connection

    async def _ensure_connected(self):
        """Ensures Redis connection is established, handling potential failures."""
        async with self._connection_lock:
            if not self.redis or not await self.redis.ping():
                logger.info(f"Attempting to connect to Redis at {self.redis_url}...")
                try:
                    # Close existing broken connection if any
                    if self.redis:
                        await self.redis.close()
                    self.redis = Redis.from_url(self.redis_url, socket_timeout=5)
                    await self.redis.ping()
                    logger.info("Successfully connected to Redis.")
                except (RedisError, asyncio.TimeoutError, OSError) as e:
                    logger.error(f"Failed to connect to Redis: {e}")
                    self.redis = None # Ensure redis is None if connection failed
                    # Optionally re-raise or handle specific connection errors differently
                    # raise ConnectionError("Could not connect to Redis") from e

    async def is_allowed(self) -> bool:
        """Checks if a request is allowed based on the global rate limit."""
        await self._ensure_connected()
        if not self.redis:
             logger.error("Rate limit check failed: Redis connection unavailable.")
             # Fail open (allow) or closed (deny) depending on requirements
             return True # Defaulting to allow if Redis is down

        key = "global_rate_limit"
        try:
            # Use a pipeline for atomic increment and conditional expire
            async with self.redis.pipeline(transaction=True) as pipe:
                # Increment the counter
                pipe.incr(key)

                pipe.expire(key, self.window_seconds)
                results = await pipe.execute()

            current_count = results[0]
            logger.debug(f"Current requests in window: {current_count}")

            if current_count > self.max_requests:
                logger.warning(f"Rate limit exceeded: {current_count} > {self.max_requests}")
                return False
            return True
        except (RedisError, asyncio.TimeoutError) as e:
            logger.error(f"Redis error during is_allowed check: {e}")
            # Decide behavior on Redis error during check (e.g., allow, deny, retry)
            return True # Defaulting to allow on error

    async def get_model(self) -> str:
        """Selects the appropriate model based on the current request count."""
        await self._ensure_connected()
        # Define a default model (highest capacity) for error cases or no traffic
        default_model = self.models_by_traffic.get(self._sorted_thresholds[0], "default-model-name") if self._sorted_thresholds else "default-model-name"

        if not self.redis:
            logger.error("Cannot get model: Redis connection unavailable. Returning default model.")
            return default_model

        key = "global_rate_limit"
        try:
            current_count_bytes = await self.redis.get(key)

            if current_count_bytes is None:
                # No requests yet in this window, or key expired
                logger.debug("No current request count found, using default/highest capacity model.")
                return default_model

            try:
                current_count = int(current_count_bytes.decode('utf-8'))
            except ValueError:
                logger.error(f"Invalid count value in Redis: {current_count_bytes}. Using default model.")
                return default_model

            logger.debug(f"Current request count for model selection: {current_count}")

            # Iterate through sorted thresholds to find the appropriate model tier
            for threshold in self._sorted_thresholds:
                if current_count <= threshold:
                    selected_model = self.models_by_traffic[threshold]
                    logger.debug(f"Selected model based on count {current_count} <= {threshold}: {selected_model}")
                    return selected_model

            # If count exceeds the highest threshold (should ideally be blocked by is_allowed)
            # Fallback to the lowest capacity model
            lowest_capacity_model = self.models_by_traffic.get(self._sorted_thresholds[-1], default_model)
            if current_count > self.max_requests:
                raise ValueError(f"Request count {current_count} exceeds twice the max requests.")
            asyncio.sleep((self.max_requests - current_count) / (self.max_requests / 5)) # Optional: Sleep to prevent immediate retry
            logger.warning(f"Request count {current_count} exceeds highest threshold. Falling back to lowest capacity model: {lowest_capacity_model}")
            return lowest_capacity_model

        except (RedisError, asyncio.TimeoutError) as e:
            logger.error(f"Redis error during get_model: {e}. Returning default model.")
            return default_model
            
    async def ollama_is_allowed(self) -> Optional[str]:
        """
        Allows only one Ollama model running at a time.
        If not in use, returns a secret key and stores it in Redis.
        If already in use, returns None.
        """
        await self._ensure_connected()
        if not self.redis:
            logger.error("Ollama rate limit check failed: Redis connection unavailable.")
            return None

        key = "ollama_in_use"
        try:
            # Try to set the key if it does not exist, with a short TTL (e.g., 120s)
            secret = secrets.token_urlsafe(32)
            was_set = await self.redis.set(key, secret, ex=120, nx=True)
            if was_set:
                logger.info("Ollama lock acquired, returning secret.")
                return secret
            else:
                logger.info("Ollama is already in use.")
                return None
        except (RedisError, asyncio.TimeoutError) as e:
            logger.error(f"Redis error during ollama_is_allowed: {e}")
            return None

    async def ollama_release(self, secret: str) -> bool:
        """
        Releases the Ollama lock if the correct secret is provided.
        Returns True if released, False otherwise.
        """
        await self._ensure_connected()
        if not self.redis:
            logger.error("Ollama release failed: Redis connection unavailable.")
            return False

        key = "ollama_in_use"
        try:
            current_secret = await self.redis.get(key)
            # Debug log for troubleshooting secret mismatch
            if current_secret:
                logger.debug(f"Ollama release: current_secret={current_secret.decode('utf-8')}, provided_secret={secret}")
            if current_secret and current_secret.decode('utf-8') == secret:
                await self.redis.delete(key)
                logger.info("Ollama lock released.")
                return True
            else:
                logger.warning("Ollama release failed: Secret mismatch.")
                return False
        except (RedisError, asyncio.TimeoutError) as e:
            logger.error(f"Redis error during ollama_release: {e}")
            return False

    @asynccontextmanager
    async def ollama_lock(self):
        """A context manager to handle the Ollama lock."""
        secret = await self.ollama_is_allowed()
        try:
            yield secret
        finally:
            if secret:
                await self.ollama_release(secret)
