"""Dependency injection container for webchat services."""

from typing import Optional

from redis.asyncio import Redis

from repositories import CourseRepository, SlotRepository, TaskRepository
from infrastructure import SlotCache, QueryCache, RedisRateLimiter, LLMClient
from core.action_interface import ActionExecutor, LegacyActionAdapter
from core.prompts import AIModelConfig


class ServiceContainer:
    """Dependency injection container for the webchat service."""
    
    def __init__(self) -> None:
        """Initialize empty container."""
        self.redis: Optional[Redis] = None
        self.course_repo: Optional[CourseRepository] = None
        self.slot_repo: Optional[SlotRepository] = None
        self.task_repo: Optional[TaskRepository] = None
        self.slot_cache: Optional[SlotCache] = None
        self.query_cache: Optional[QueryCache] = None
        self.rate_limiter: Optional[RedisRateLimiter] = None
        self.llm_client: Optional[LLMClient] = None
        self.action_executor: Optional[ActionExecutor] = None
        self._initialized = False
    
    async def initialize(
        self,
        redis_url: str,
        tracker_ttl: int = 3600,
        slot_cache_ttl: int = 3600,
        query_cache_ttl: int = 300,
        rate_limit_max: int = 20,
        rate_limit_window: int = 60
    ) -> None:
        """Initialize all services in the correct order."""
        if self._initialized:
            return
        self.redis = Redis.from_url(redis_url, decode_responses=True)
        await self.redis.ping()
        self.course_repo = CourseRepository()
        self.slot_repo = SlotRepository()
        self.task_repo = TaskRepository()
        self.slot_cache = SlotCache(self.redis, ttl_seconds=slot_cache_ttl)
        self.query_cache = QueryCache(self.redis, ttl_seconds=query_cache_ttl)
        self.rate_limiter = RedisRateLimiter(
            self.redis,
            max_requests=rate_limit_max,
            window_seconds=rate_limit_window
        )
        self.llm_client = LLMClient(
            model=AIModelConfig.CHAT_MODEL,
            temperature=AIModelConfig.CHAT_TEMPERATURE,
            max_tokens=AIModelConfig.CHAT_MAX_TOKENS,
            timeout=AIModelConfig.REQUEST_TIMEOUT
        )
        self._initialize_action_executor()
        self._initialized = True
    
    def _initialize_action_executor(self) -> None:
        """Initialize the action executor with the legacy adapter."""
        from actions import ActionQuiz
        legacy_action = ActionQuiz()
        legacy_action.slot_cache = self.slot_cache
        self.action_executor = LegacyActionAdapter(legacy_action)
    
    async def shutdown(self) -> None:
        """Clean shutdown of all services."""
        if self.redis:
            await self.redis.close()
        
        self._initialized = False
    
    def ensure_initialized(self) -> None:
        """Raise error if container is not initialized."""
        if not self._initialized:
            raise RuntimeError(
                "ServiceContainer not initialized. "
                "Call await container.initialize() during startup."
            )


_container: Optional[ServiceContainer] = None


def get_container() -> ServiceContainer:
    """Get the global service container."""
    global _container
    if _container is None:
        _container = ServiceContainer()
    return _container


async def initialize_container(
    redis_url: str,
    **kwargs
) -> ServiceContainer:
    """Initialize the global service container."""
    container = get_container()
    await container.initialize(redis_url, **kwargs)
    return container


async def shutdown_container() -> None:
    """Shutdown the global service container."""
    global _container
    if _container:
        await _container.shutdown()
        _container = None
