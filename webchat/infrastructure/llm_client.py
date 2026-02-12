"""LLM client wrapper with OpenAI and optional Ollama fallback."""

import json
import logging
import os
from typing import Any, Dict, List, Optional

from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)


class LLMClient:
    """Centralized LLM client for AI service integration."""
    
    def __init__(
        self,
        model: str = "gpt-4o-mini",
        temperature: float = 0.5,
        max_tokens: int = 200,
        timeout: int = 600
    ) -> None:
        """Initialize the client with model defaults."""
        self.model = ChatOpenAI(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )
        self.ollama_url = os.getenv("OLLAMA_URL", "http://ollama:11434")
    
    async def get_response(
        self,
        message: Optional[str] = None,
        chat_history: Optional[List[Dict[str, str]]] = None,
        use_ollama: bool = False,
        stream_callback: Optional[Any] = None
    ) -> str:
        """Get a response, optionally trying Ollama first."""
        if chat_history is not None:
            messages = chat_history
        elif message is not None:
            messages = [{"role": "user", "content": message}]
        else:
            return ""

        if use_ollama:
            try:
                response = await self._stream_ollama(messages, stream_callback)
                return response
            except Exception as e:
                logger.warning("Ollama connection error, falling back to OpenAI: %s", e)

        try:
            response = await self.model.ainvoke(messages)
            return response.content
        except Exception as e:
            logger.error("LLM request failed: %s", e)
            return "Omlouvám se, momentálně nemohu odpovědět."
    
    async def _stream_ollama(
        self,
        messages: List[Dict[str, str]],
        callback: Optional[Any] = None
    ) -> str:
        """Stream response from Ollama."""
        import aiohttp

        prompt = self._format_messages_for_ollama(messages)
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": "gemma2:27b",
                    "prompt": prompt,
                    "stream": True
                }
            ) as response:
                full_text = ""
                async for line in response.content:
                    if line:
                        try:
                            chunk = json.loads(line)
                            text = chunk.get("response", "")
                            full_text += text
                            if callback:
                                callback(text=text)
                        except json.JSONDecodeError:
                            pass
                
                return full_text
    
    def _format_messages_for_ollama(
        self,
        messages: List[Dict[str, str]]
    ) -> str:
        """Format OpenAI-style messages for Ollama."""
        prompt_parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            if role == "system":
                prompt_parts.append(f"System: {content}")
            elif role == "user":
                prompt_parts.append(f"User: {content}")
            elif role == "assistant":
                prompt_parts.append(f"Assistant: {content}")
        
        return "\n".join(prompt_parts)
