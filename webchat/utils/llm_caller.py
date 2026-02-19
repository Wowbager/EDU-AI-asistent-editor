"""LLM access helpers with unified Bifrost routing."""

import logging
from langchain_openai import ChatOpenAI

from ai_config import AIModelConfig

logger = logging.getLogger(__name__)


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


_validate_prefixed_model(AIModelConfig.CHAT_MODEL)

model = ChatOpenAI(
    model=AIModelConfig.CHAT_MODEL,
    temperature=AIModelConfig.CHAT_TEMPERATURE,
    max_tokens=AIModelConfig.CHAT_MAX_TOKENS,
    timeout=AIModelConfig.REQUEST_TIMEOUT,
    openai_api_key=AIModelConfig.OPENAI_API_KEY,
    openai_api_base=AIModelConfig.BIFROST_API_BASE,
)

async def get_llm_response(message=None, chat=None):
    """Return a response from unified Bifrost-compatible OpenAI API."""
    if chat is not None:
        messages = chat
    elif message is not None:
        messages = [{"role": "user", "content": message}]
    else:
        return ""

    try:
        response = await model.ainvoke(messages)
        return response.content
    except Exception as exc:
        logger.error("OpenAI API error: %s", exc)
        return "Omlouvám se, nemohu nyní odpovědět. Zkuste to prosím později."
