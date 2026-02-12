"""LLM access helpers with OpenAI and optional Ollama fallback."""

import json
import logging
import os

import aiohttp
from langchain_openai import ChatOpenAI

from ai_config import AIModelConfig

logger = logging.getLogger(__name__)

model = ChatOpenAI(
    model=AIModelConfig.CHAT_MODEL,
    temperature=AIModelConfig.CHAT_TEMPERATURE,
    max_tokens=AIModelConfig.CHAT_MAX_TOKENS,
    timeout=AIModelConfig.REQUEST_TIMEOUT,
)

async def get_llm_response(message=None, chat=None, use_gemma=False, utter_message_sender=None):
    """Return a response from OpenAI, optionally falling back from Ollama."""
    if chat is not None:
        messages = chat
    elif message is not None:
        messages = [{"role": "user", "content": message}]
    else:
        return ""

    if use_gemma:
        try:
            response = await stream_ollama_chat(messages, utter_message_sender)
            return response
        except Exception as e:
            logger.warning("Ollama connection error, falling back to OpenAI: %s", e)

    try:
        response = await model.ainvoke(messages)
        return response.content
    except Exception as exc:
        logger.error("OpenAI API error: %s", exc)
        return "Omlouvám se, nemohu nyní odpovědět. Zkuste to prosím později."


async def stream_ollama_chat(messages, utter_message_sender):
    host = os.environ.get("OLLAMA_HOST", "http://172.17.0.1:11434")
    url = f"{host}/api/chat"
    payload = {
        "model": "gemma3:12b-it-qat",
        "messages": messages,
        "temperature": 0.5,
        "max_tokens": 200,
        "stream": True,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            resp.raise_for_status()

            full_msg = ""
            buffer = ""
            while True:
                line_bytes = await resp.content.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode().strip()
                if not line:
                    continue
                data = json.loads(line)
                if data.get("done"):
                    break
                fragment = data["message"]["content"]
                buffer += fragment
                full_msg += fragment

                if "\n" in buffer:
                    parts = buffer.split("\n")
                    for part in parts[:-1]:
                        if part and utter_message_sender:
                            utter_message_sender(text=part)
                    buffer = parts[-1]

            if buffer and utter_message_sender:
                utter_message_sender(text=buffer)

            return full_msg