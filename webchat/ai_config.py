"""Centralized AI settings and prompt templates."""

import os
from typing import Any, Dict


class AIModelConfig:
    """Configuration for AI models used in the application."""

    CHAT_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")
    CHAT_TEMPERATURE = float(os.getenv("CHAT_TEMPERATURE", "0.5"))
    CHAT_MAX_TOKENS = int(os.getenv("CHAT_MAX_TOKENS", "200"))
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    REQUEST_TIMEOUT = int(os.getenv("CHAT_TIMEOUT", "600"))
    MAX_MESSAGE_LENGTH = 1000


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
