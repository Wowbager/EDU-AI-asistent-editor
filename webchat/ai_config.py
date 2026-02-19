"""Centralized AI settings and prompt templates."""

import os
import json
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
    """Configuration for AI models used in the application."""

    CHAT_MODEL = _cfg_value("chat_model", "OPENAI_MODEL", "openai/gpt-5.1", str)
    CHAT_TEMPERATURE = _cfg_value("chat_temperature", "CHAT_TEMPERATURE", 0.7, float)
    CHAT_MAX_TOKENS = _cfg_value("chat_max_tokens", "CHAT_MAX_TOKENS", 500, int)
    OPENAI_API_KEY = _cfg_value("bifrost_api_key", "BIFROST_API_KEY", os.getenv("OPENAI_API_KEY"), str)
    BIFROST_API_BASE = _cfg_value("bifrost_api_base", "BIFROST_API_BASE", "http://bifrost:8088/v1", str)
    REQUEST_TIMEOUT = _cfg_value("request_timeout", "CHAT_TIMEOUT", 30, int)
    MAX_MESSAGE_LENGTH = _cfg_value("max_message_length", "MAX_MESSAGE_LENGTH", 1000, int)


class PromptTemplates:
    """Centralized prompt templates for consistent AI behavior."""

    GENERAL_INSTRUCTIONS = """Odpovídejte v češtině s konkrétními fakty a detaily. Pro soutěž #NachytejAI buďte přirozeně informovaní, ale neověřujte každý fakt.

DŮLEŽITÉ ZÁSADY:
- Nepoužívejte markdown nebo formátování
- Odpovědi musí být stručné, maximálně 200 slov, moc se nerozepisuj
- Za žádných okolností nepoužívejte sprostá slova ani urážky
- Nepoužívejte fráze jako "jsem jazykový model" nebo "nemám přístup k internetu"
- Snažte se odpovídat jako daná osoba/role, vezměte v úvahu co zná a jak by měl odpovídat
- Odpovídáte do chatu, takže se vyhněte formálním pozdravům a rozloučením
- Odpovídejte krátce a přirozeně"""


def get_ai_config() -> Dict[str, Any]:
    """Return AI configuration as a dictionary."""
    return {
        "model": AIModelConfig.CHAT_MODEL,
        "temperature": AIModelConfig.CHAT_TEMPERATURE,
        "max_tokens": AIModelConfig.CHAT_MAX_TOKENS,
        "timeout": AIModelConfig.REQUEST_TIMEOUT,
    }
