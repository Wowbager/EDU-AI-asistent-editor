"""Runtime AI config for the FastAPI roleplay websocket service."""

import json
import os
from typing import Any, Dict


def _load_shared_ai_config() -> Dict[str, Any]:
    config_path = os.getenv("AI_CONFIG_PATH", "/opt/edu-ai/ai_config.json")
    try:
        with open(config_path, "r", encoding="utf-8") as config_file:
            data = json.load(config_file)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


_SHARED_AI_CONFIG = _load_shared_ai_config()


def _cfg_value(key: str, env_key: str, default: Any, caster=lambda value: value) -> Any:
    if key in _SHARED_AI_CONFIG:
        try:
            return caster(_SHARED_AI_CONFIG[key])
        except Exception:
            pass

    env_value = os.getenv(env_key)
    if env_value is not None:
        try:
            return caster(env_value)
        except Exception:
            pass

    return default


class AIModelConfig:
    """Configuration actually used by `fastapi/main.py`."""

    CHAT_MODEL = _cfg_value("chat_model", "OPENAI_MODEL", "openai/gpt-5.1", str)
    CHAT_TEMPERATURE = _cfg_value("chat_temperature", "CHAT_TEMPERATURE", 0.7, float)
    CHAT_MAX_TOKENS = _cfg_value("chat_max_tokens", "CHAT_MAX_TOKENS", 500, int)

    OPENAI_API_KEY = _cfg_value("bifrost_api_key", "BIFROST_API_KEY", os.getenv("OPENAI_API_KEY"), str)
    BIFROST_API_BASE = _cfg_value("bifrost_api_base", "BIFROST_API_BASE", "http://bifrost:8088/v1", str)

    REQUEST_TIMEOUT = _cfg_value("request_timeout", "CHAT_TIMEOUT", 30, int)
    MAX_ASSISTANT_RESPONSES = _cfg_value("max_ai_responses", "MAX_AI_RESPONSES", 10, int)
    MAX_MESSAGE_LENGTH = _cfg_value("max_message_length", "MAX_MESSAGE_LENGTH", 1000, int)
