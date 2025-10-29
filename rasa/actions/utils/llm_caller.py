import openai
import os
import aiohttp
import asyncio
import json
from .rate_limiter import GlobalRateLimiter

rate_limiter = GlobalRateLimiter()

async def get_llm_response(message=None, chat=None, use_gemma=False, utter_message_sender=None):
    if chat is not None:
        allowed = await rate_limiter.is_allowed()
        if not allowed:
            return "Omlouvám se, ale už jsem už jsem toho řekl dost. Napište mi kontakt a lidský kolega se vám ozve."
        messages = chat
        temperature = 0.5
        max_tokens = 200
    elif message is not None:
        messages = [{"role": "user", "content": message}]
        temperature = 0.5
        max_tokens = 200
    else:
        return ""

    if use_gemma:
        async with rate_limiter.ollama_lock() as ollama_secret:
            if ollama_secret:
                try:
                    response = await stream_ollama_chat(messages, utter_message_sender)
                    return response
                except Exception as e:
                    print(f"Ollama connection error, falling back to OpenAI. {e}", flush=True)

    # Fallback to OpenAI if Ollama is busy
    model = await rate_limiter.get_model() if chat is not None else "gpt-4.1"
    chat_response = await openai.ChatCompletion.acreate(
        model=model,
        request_timeout=600,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return chat_response.choices[0].message.content

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