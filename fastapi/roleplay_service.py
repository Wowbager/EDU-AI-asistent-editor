"""Roleplay websocket runtime helpers for the FastAPI service."""

import logging
import pickle
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

from langchain_openai import ChatOpenAI
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError

from .ai_config import AIModelConfig
from .database import async_session_maker
from .models import ChatMessage, ChatSession

logger = logging.getLogger(__name__)

CHAT_FALLBACKS = [
    "openrouter/gpt-5-mini:nitro",
    "groq/meta-llama/llama-4-scout-17b-16e-instruct",
]


@dataclass
class SessionBootstrap:
    """Validated roleplay session payload loaded from Redis."""

    user_id: int
    role_id: str
    messages: List[Dict[str, str]]


def validate_prefixed_model(model_name: str) -> None:
    if not isinstance(model_name, str) or "/" not in model_name:
        raise ValueError(
            "Invalid OPENAI_MODEL format. Use 'openai/<model>' or 'groq/<model>'."
        )
    provider, _ = model_name.split("/", 1)
    if provider not in {"openai", "groq"}:
        raise ValueError(
            "Invalid OPENAI_MODEL provider prefix. Allowed prefixes: 'openai/' or 'groq/'."
        )


def create_chat_model() -> ChatOpenAI:
    """Create the LangChain chat model used by the websocket runtime."""

    validate_prefixed_model(AIModelConfig.CHAT_MODEL)
    return ChatOpenAI(
        model=AIModelConfig.CHAT_MODEL,
        temperature=AIModelConfig.CHAT_TEMPERATURE,
        max_tokens=AIModelConfig.CHAT_MAX_TOKENS,
        timeout=AIModelConfig.REQUEST_TIMEOUT,
        openai_api_key=AIModelConfig.OPENAI_API_KEY,
        openai_api_base=AIModelConfig.BIFROST_API_BASE,
        model_kwargs={"fallbacks": CHAT_FALLBACKS},
    )


async def load_session_from_redis(redis_client, session_id: str) -> Optional[SessionBootstrap]:
    """Load and validate one-time roleplay session payload from Redis."""

    if not await redis_client.exists(f"chat_history:{session_id}"):
        return None

    chat_data_raw = await redis_client.get(f"chat_history:{session_id}")
    chat_data = pickle.loads(chat_data_raw)

    await redis_client.delete(f"chat_history:{session_id}")

    user_id = chat_data.get("user_id")
    role_id = chat_data.get("role", {}).get("id", "unknown")
    messages = chat_data.get("messages", [])

    if not user_id or not messages:
        return None

    return SessionBootstrap(user_id=user_id, role_id=role_id, messages=messages)


async def rebuild_session_bootstrap(redis_client, conversation_id: str) -> Optional[Dict]:
    """Rebuild one-time Redis bootstrap for an existing conversation ID."""

    async with async_session_maker() as db_session:
        chat_session_result = await db_session.execute(
            select(ChatSession).where(ChatSession.id == conversation_id)
        )
        chat_session = chat_session_result.scalar_one_or_none()

        if not chat_session:
            return None

        messages_result = await db_session.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == conversation_id)
            .order_by(ChatMessage.message_index)
        )
        db_messages = messages_result.scalars().all()

    conversation_history: List[Dict[str, str]] = []
    for message in db_messages:
        if message.role in {"user", "assistant", "system"}:
            conversation_history.append(
                {
                    "role": message.role,
                    "content": message.content,
                }
            )

    role_id = chat_session.role_id or "unknown"
    bootstrap_payload = {
        "user_id": chat_session.user_id,
        "role": {
            "id": role_id,
        },
        "messages": conversation_history,
    }

    await redis_client.set(
        f"chat_history:{conversation_id}",
        pickle.dumps(bootstrap_payload),
        ex=600,
    )

    frontend_history = [
        message for message in conversation_history if message.get("role") in {"user", "assistant"}
    ]

    return {
        "conversation_id": conversation_id,
        "role_id": role_id,
        "conversation_history": frontend_history,
    }


async def save_chat_to_database(
    session_id: str,
    user_id: int,
    role_id: str,
    messages: List[Dict[str, str]],
) -> None:
    """Persist roleplay messages to DB for history and flagging features."""

    try:
        async with async_session_maker() as db_session:
            async with db_session.begin():
                result = await db_session.execute(
                    select(ChatSession).where(ChatSession.id == session_id)
                )
                existing_session = result.scalar_one_or_none()

                if not existing_session:
                    db_session.add(
                        ChatSession(id=session_id, user_id=user_id, role_id=role_id)
                    )

                await db_session.execute(
                    delete(ChatMessage).where(ChatMessage.session_id == session_id)
                )

                message_index = 0
                for msg in messages:
                    if msg.get("role") in {"user", "assistant"}:
                        db_session.add(
                            ChatMessage(
                                session_id=session_id,
                                role=msg["role"],
                                content=msg["content"],
                                message_index=message_index,
                            )
                        )
                        message_index += 1

                await db_session.commit()
    except SQLAlchemyError as exc:
        logger.error("Database error saving chat %s: %s", session_id, exc)
    except Exception as exc:
        logger.error("Unexpected error saving chat %s: %s", session_id, exc)


def append_user_message(messages: List[Dict[str, str]], user_message: str) -> None:
    messages.append(
        {
            "role": "user",
            "content": user_message,
            "timestamp": datetime.utcnow().isoformat(),
        }
    )


def append_assistant_message(messages: List[Dict[str, str]], content: str) -> None:
    messages.append(
        {
            "role": "assistant",
            "content": content,
            "timestamp": datetime.utcnow().isoformat(),
        }
    )
