import logging
import os
from urllib.parse import parse_qs
from typing import Dict, List

import redis.asyncio as redis
import socketio
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .ai_config import AIModelConfig
from .roleplay_service import (
    append_assistant_message,
    append_user_message,
    create_chat_model,
    load_session_from_redis,
    rebuild_session_bootstrap,
    save_chat_to_database,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

fastapi_app = FastAPI(title="EDU-AI Chat API")

fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://go.edu-ai.eu", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins=["https://go.edu-ai.eu", "http://localhost:8000"],
)

app = socketio.ASGIApp(sio, other_asgi_app=fastapi_app)

redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "redis"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    db=int(os.getenv("REDIS_DB", 0)),
    decode_responses=False,
)

model = create_chat_model()
MAX_ASSISTANT_RESPONSES = AIModelConfig.MAX_ASSISTANT_RESPONSES
MAX_MESSAGE_LENGTH = AIModelConfig.MAX_MESSAGE_LENGTH

connection_states: Dict[str, Dict] = {}


class ResumeConversationRequest(BaseModel):
    conversation_id: str


@fastapi_app.get("/")
async def root():
    return {"status": "ok", "service": "EDU-AI Chat API"}


@fastapi_app.post("/sessions/resume")
async def resume_conversation(payload: ResumeConversationRequest):
    try:
        rebuilt = await rebuild_session_bootstrap(
            redis_client=redis_client,
            conversation_id=payload.conversation_id,
        )
    except Exception as exc:
        logger.error(
            "Failed to rebuild session bootstrap for conversation %s: %s",
            payload.conversation_id,
            exc,
        )
        raise HTTPException(
            status_code=500,
            detail="Nepodařilo se připravit pokračování konverzace.",
        )

    if not rebuilt:
        raise HTTPException(status_code=404, detail="Konverzace nebyla nalezena.")

    return {
        "session_id": rebuilt["conversation_id"],
        "conversation_id": rebuilt["conversation_id"],
        "role_id": rebuilt["role_id"],
        "conversation_history": rebuilt["conversation_history"],
    }


def _get_session_id_from_connect(environ: Dict, auth) -> str:
    if isinstance(auth, dict) and auth.get("session_id"):
        return str(auth.get("session_id"))

    query_params = parse_qs(environ.get("QUERY_STRING", ""))
    query_session_id = query_params.get("session_id", [""])[0]
    return query_session_id


async def _emit_stream_chunks(sid: str, content: str, chunk_size: int = 80) -> None:
    if not content:
        return

    for start_index in range(0, len(content), chunk_size):
        chunk = content[start_index : start_index + chunk_size]
        await sio.emit(
            "stream_chunk",
            {"type": "stream_chunk", "content": chunk},
            to=sid,
        )


@sio.event
async def connect(sid, environ, auth):
    session_id = _get_session_id_from_connect(environ, auth)
    if not session_id:
        raise ConnectionRefusedError("Missing session_id")

    session = await load_session_from_redis(redis_client, session_id)
    if not session:
        logger.warning("Socket.IO session rejected, invalid bootstrap session: %s", session_id)
        raise ConnectionRefusedError("Invalid or expired session")

    assistant_message_count = sum(
        1 for m in session.messages if m.get("role") == "assistant"
    )

    connection_states[sid] = {
        "session_id": session_id,
        "user_id": session.user_id,
        "role_id": session.role_id,
        "messages": session.messages,
        "assistant_message_count": assistant_message_count,
    }

    await sio.emit(
        "connected",
        {"type": "connected", "message": "Připojeno k chatovacímu serveru"},
        to=sid,
    )
    logger.info("Socket.IO client connected sid=%s session_id=%s", sid, session_id)

    if assistant_message_count >= MAX_ASSISTANT_RESPONSES:
        await sio.emit(
            "limit_reached",
            {
                "type": "limit_reached",
                "message": f"Dosažen limit {MAX_ASSISTANT_RESPONSES} odpovědí AI",
            },
            to=sid,
        )
        await sio.disconnect(sid)


@sio.on("send_message")
async def send_message(sid, user_message):
    state = connection_states.get(sid)
    if not state:
        await sio.emit(
            "error",
            {
                "type": "error",
                "message": "Neplatná relace. Prosím začněte novou konverzaci.",
            },
            to=sid,
        )
        await sio.disconnect(sid)
        return

    session_id = state["session_id"]
    messages: List[Dict[str, str]] = state["messages"]
    user_id = state["user_id"]
    role_id = state["role_id"]
    assistant_message_count = state["assistant_message_count"]

    try:
        if assistant_message_count >= MAX_ASSISTANT_RESPONSES:
            await sio.emit(
                "limit_reached",
                {
                    "type": "limit_reached",
                    "message": f"Dosažen limit {MAX_ASSISTANT_RESPONSES} odpovědí AI",
                },
                to=sid,
            )
            await sio.disconnect(sid)
            return

        if not isinstance(user_message, str):
            await sio.emit(
                "error",
                {
                    "type": "error",
                    "message": "Neplatný formát zprávy.",
                },
                to=sid,
            )
            return

        if len(user_message) > MAX_MESSAGE_LENGTH:
            await sio.emit(
                "error",
                {
                    "type": "error",
                    "message": f"Zpráva je příliš dlouhá (max {MAX_MESSAGE_LENGTH} znaků)",
                },
                to=sid,
            )
            return

        append_user_message(messages, user_message)
        await sio.emit(
            "processing",
            {"type": "processing", "message": "Generuji odpověď..."},
            to=sid,
        )

        response = await model.ainvoke(messages)
        assistant_content = response.content

        await _emit_stream_chunks(sid, assistant_content)

        append_assistant_message(messages, assistant_content)
        assistant_message_count += 1
        state["assistant_message_count"] = assistant_message_count

        await sio.emit(
            "message",
            {
                "type": "message",
                "content": assistant_content,
                "message_count": assistant_message_count,
                "max_messages": MAX_ASSISTANT_RESPONSES,
            },
            to=sid,
        )

        if user_id != "showcase_user":
            await save_chat_to_database(session_id, user_id, role_id, messages)

        if assistant_message_count >= MAX_ASSISTANT_RESPONSES:
            await sio.emit(
                "limit_reached",
                {
                    "type": "limit_reached",
                    "message": f"Dosažen limit {MAX_ASSISTANT_RESPONSES} odpovědí AI",
                },
                to=sid,
            )
            await sio.disconnect(sid)

    except Exception as exc:
        logger.error("Session %s: Error processing message: %s", session_id, exc)
        await sio.emit(
            "error",
            {
                "type": "error",
                "message": "Nastala chyba při zpracování zprávy. Zkuste to znovu.",
            },
            to=sid,
        )


@sio.event
async def disconnect(sid):
    state = connection_states.pop(sid, None)
    if not state:
        return

    await save_chat_to_database(
        state["session_id"],
        state["user_id"],
        state["role_id"],
        state["messages"],
    )
    logger.info("Socket.IO client disconnected sid=%s session_id=%s", sid, state["session_id"])
