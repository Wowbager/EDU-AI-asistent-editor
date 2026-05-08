"""LLM client wrapper with unified Bifrost routing."""

import logging
from typing import Any, Dict, List, Optional

from langchain_openai import ChatOpenAI
from ai_config import AIModelConfig

logger = logging.getLogger(__name__)

CHAT_FALLBACKS = [
    "openrouter/gpt-5-mini:nitro",
    "groq/meta-llama/llama-4-scout-17b-16e-instruct",
]


class LLMClient:
    """Centralized LLM client for AI service integration."""
    
    def __init__(
        self,
        model: str = "openai/gpt-5-mini",
        temperature: float = 0.5,
        max_tokens: int = 200,
        timeout: int = 600
    ) -> None:
        """Initialize the client with model defaults."""
        self._validate_prefixed_model(model)
        self.model = ChatOpenAI(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            openai_api_key=AIModelConfig.OPENAI_API_KEY,
            openai_api_base=AIModelConfig.BIFROST_API_BASE,
            model_kwargs={"fallbacks": CHAT_FALLBACKS},
        )

    @staticmethod
    def _validate_prefixed_model(model_name: str) -> None:
        if not isinstance(model_name, str) or "/" not in model_name:
            raise ValueError(
                "Invalid OPENAI_MODEL format. Use 'openai/<model>' or 'groq/<model>'."
            )
        provider, _ = model_name.split("/", 1)
        if provider not in {"openai", "groq"}:
            raise ValueError(
                "Invalid OPENAI_MODEL provider prefix. Allowed prefixes: 'openai/' or 'groq/'."
            )
    
    async def get_response(
        self,
        message: Optional[str] = None,
        chat_history: Optional[List[Dict[str, str]]] = None,
        use_ollama: bool = False,
        stream_callback: Optional[Any] = None
    ) -> str:
        """Get a response through Bifrost.

        The `use_ollama` parameter is deprecated and ignored.
        """
        if chat_history is not None:
            messages = chat_history
        elif message is not None:
            messages = [{"role": "user", "content": message}]
        else:
            return ""

        if use_ollama:
            logger.warning("use_ollama is deprecated and disabled; using Bifrost model routing instead.")

        try:
            response = await self.model.ainvoke(messages)
            return response.content
        except Exception as e:
            logger.error("LLM request failed: %s", e)
            return "Omlouvám se, momentálně nemohu odpovědět."
