import os
from functools import lru_cache
from typing import List


class Settings:
    """Centralised configuration for the beta Deep Chat handler."""

    def __init__(self) -> None:
        redis_host = os.getenv("WEBCHAT_REDIS_HOST", "redis")
        redis_port = int(os.getenv("WEBCHAT_REDIS_PORT", "6379"))
        redis_db = int(os.getenv("WEBCHAT_REDIS_DB", "4"))
        redis_password = os.getenv("WEBCHAT_REDIS_PASSWORD")

        if redis_password:
            self.redis_url = f"redis://:{redis_password}@{redis_host}:{redis_port}/{redis_db}"
        else:
            self.redis_url = f"redis://{redis_host}:{redis_port}/{redis_db}"

        self.tracker_ttl_seconds = int(os.getenv("WEBCHAT_TRACKER_TTL", "3600"))
        self.slot_cache_ttl_seconds = int(os.getenv("WEBCHAT_SLOT_CACHE_TTL", "3600"))
        self.rate_limit_max_requests = int(os.getenv("WEBCHAT_RATE_LIMIT_MAX", "20"))
        self.rate_limit_window_seconds = int(os.getenv("WEBCHAT_RATE_LIMIT_WINDOW", "60"))
        # Split and strip whitespace from each origin
        origins_str = os.getenv(
            "WEBCHAT_ALLOWED_ORIGINS",
            "http://localhost:3000,http://localhost:4173,https://go.edu-ai.eu",
        )
        self.allowed_origins: List[str] = [origin.strip() for origin in origins_str.split(",")]
        self.default_input_channel = os.getenv("WEBCHAT_INPUT_CHANNEL", "deepchat-web")
        self.default_course_id = os.getenv("WEBCHAT_DEFAULT_COURSE_ID")

        # Deep Chat always sends a messages list. Keep a single action for beta.
        self.default_action_name = os.getenv("WEBCHAT_DEFAULT_ACTION", "action_quiz")


@lru_cache()
def get_settings() -> Settings:
    return Settings()
