import openai
import os
import json
from .rate_limiter import GlobalRateLimiter

rate_limiter = GlobalRateLimiter()


def _load_shared_ai_config():
    config_path = os.getenv("AI_CONFIG_PATH", "/opt/edu-ai/ai_config.json")
    try:
        with open(config_path, "r", encoding="utf-8") as config_file:
            data = json.load(config_file)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


_SHARED_AI_CONFIG = _load_shared_ai_config()


def _cfg_value(key, env_key, default, caster=lambda value: value):
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


openai.api_key = _cfg_value("bifrost_api_key", "BIFROST_API_KEY", os.environ.get("OPENAI_API_KEY"), str)
openai.api_base = _cfg_value("bifrost_api_base", "BIFROST_API_BASE", "http://bifrost:8088/v1", str)

async def get_llm_response(message=None, chat=None):
    if chat is not None:
        allowed = await rate_limiter.is_allowed()
        if not allowed:
            return "Omlouvám se, ale už jsem už jsem toho řekl dost. Napište mi kontakt a lidský kolega se vám ozve."
        messages = chat
        temperature = 1.0
        max_tokens = 200
    elif message is not None:
        messages = [{"role": "user", "content": message}]
        temperature = 1.0
        max_tokens = 200
    else:
        return ""
 
    model = await rate_limiter.get_model() if chat is not None else _cfg_value("chat_model", "OPENAI_MODEL", "openai/gpt-5.1", str)
    _validate_prefixed_model(model)
    chat_response = await openai.ChatCompletion.acreate(
        model=model,
        request_timeout=600,
        messages=messages,
        temperature=temperature,
        max_completion_tokens=max_tokens,
    )
    return chat_response.choices[0].message.content
