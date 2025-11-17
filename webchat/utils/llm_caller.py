import os
import aiohttp
import asyncio
import json
import logging
from langchain_openai import ChatOpenAI
from ai_config import AIModelConfig

logger = logging.getLogger(__name__)

# Initialize LangChain ChatOpenAI model
model = ChatOpenAI(
    model=AIModelConfig.CHAT_MODEL,
    temperature=AIModelConfig.CHAT_TEMPERATURE,
    max_tokens=AIModelConfig.CHAT_MAX_TOKENS,
    timeout=AIModelConfig.REQUEST_TIMEOUT,
)

async def get_llm_response(message=None, chat=None, use_gemma=False, utter_message_sender=None):
    """
    Get LLM response using LangChain ChatOpenAI.
    
    Args:
        message: Single message string (creates simple user message)
        chat: Full chat history in OpenAI format [{"role": "user/assistant/system", "content": "..."}]
        use_gemma: If True, try Ollama first, fallback to OpenAI
        utter_message_sender: Optional callback for streaming (Ollama only)
    
    Returns:
        String response from the model
    """
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

    # Use LangChain for OpenAI
    try:
        response = await model.ainvoke(messages)
        return response.content
    except Exception as e:
        logger.error("OpenAI API error: %s", e)
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
            # Read one JSON‐line at a time
            while True:
                line_bytes = await resp.content.readline()
                if not line_bytes:
                    break  # connection closed
                line = line_bytes.decode().strip()
                if not line:
                    continue
                data = json.loads(line)
                # Stop when Ollama signals completion
                if data.get("done"):
                    break
                fragment = data["message"]["content"]
                buffer += fragment
                full_msg += fragment

                if "\n" in buffer:
                    parts = buffer.split("\n")
                    for part in parts[:-1]:
                        if part:
                            ...
                            # Rasa dispatcher does not support streaming, so we don't need the whole streaming functionality. But if we move to a different dispatcher that supports streaming, we can uncomment the next line.
                            # utter_message_sender(text=part)
                    buffer = parts[-1]
            
            if buffer:
                utter_message_sender(text=buffer)

            return full_msg