import asyncio
import json
import logging
import uuid
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from actions_bridge import ActionBridge, DeepChatDispatcher, TrackerAdapter
from query_cache import QueryCache
from rate_limiter import RedisRateLimiter
from schemas import DeepChatRequest, DeepChatResponse, SessionRequest, SessionResponse
from settings import get_settings
from slot_cache import SlotCache
from tracker_store import RedisTrackerStore

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

settings = get_settings()
app = FastAPI(title="Deep Chat Beta Handler", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

redis_client: Redis | None = None
tracker_store: RedisTrackerStore | None = None
rate_limiter: RedisRateLimiter | None = None
slot_cache: SlotCache | None = None
query_cache: QueryCache | None = None
action_bridge = ActionBridge()


@app.on_event("startup")
async def startup() -> None:
    global redis_client, tracker_store, rate_limiter, slot_cache, query_cache  # noqa: PLW0603
    redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
    tracker_store = RedisTrackerStore(redis_client, settings.tracker_ttl_seconds)
    rate_limiter = RedisRateLimiter(
        redis_client, settings.rate_limit_max_requests, settings.rate_limit_window_seconds
    )
    slot_cache = SlotCache(redis_client, settings.slot_cache_ttl_seconds)
    query_cache = QueryCache(redis_client, ttl_seconds=300)  # 5 min cache for course/lecture data
    action_bridge.set_slot_cache(slot_cache)
    await redis_client.ping()
    logger.info("Webchat beta handler started")


@app.on_event("shutdown")
async def shutdown() -> None:
    if redis_client:
        await redis_client.close()


def _ensure_services() -> None:
    if not (redis_client and tracker_store and rate_limiter and slot_cache and query_cache):
        raise RuntimeError("Service initialisation failed")


@app.post("/api/sessions", response_model=SessionResponse)
async def create_session(payload: SessionRequest) -> SessionResponse:
    _ensure_services()
    conversation_id = payload.sender_id or str(uuid.uuid4())
    await tracker_store.create_or_load(
        conversation_id,
        sender_id=conversation_id,
        metadata=payload.custom_data or {},
    )
    return SessionResponse(conversation_id=conversation_id)


async def _run_action(conversation_id: str, user_text: str) -> List[DeepChatResponse]:
    _ensure_services()

    if not await rate_limiter.allow(conversation_id):
        logger.warning("Rate limit exceeded for %s", conversation_id)
        return [DeepChatResponse(error="Příliš mnoho požadavků, zkuste to prosím později.")]

    state = await tracker_store.append_user_event(
        conversation_id,
        user_text,
        input_channel=settings.default_input_channel,
    )

    tracker = TrackerAdapter(
        sender_id=state["sender_id"],
        events=state.get("events", []),
        latest_input_channel=state.get("latest_input_channel"),
        metadata=state.get("metadata", {}),
    )
    dispatcher = DeepChatDispatcher()
    responses = await action_bridge.run(settings.default_action_name, tracker, dispatcher)
    bot_events: List[Dict[str, Any]] = []
    for response in responses:
        payload = response.as_payload()
        payload["event"] = "bot"
        bot_events.append(payload)
    await tracker_store.append_bot_events(conversation_id, bot_events)
    return responses


@app.post("/api/chat/{conversation_id}/messages")
async def send_message(conversation_id: str, payload: DeepChatRequest):
    if not payload.messages:
        raise HTTPException(status_code=400, detail="Missing messages")
    user_text = payload.latest_user_text()
    if not user_text:
        raise HTTPException(status_code=400, detail="User message with text is required")

    responses = await _run_action(conversation_id, user_text)
    body: Any = [resp.as_payload() for resp in responses]
    if len(body) == 1:
        body = body[0]
    return JSONResponse(content=body)


@app.websocket("/ws/{conversation_id}")
async def websocket_endpoint(websocket: WebSocket, conversation_id: str):
    await websocket.accept()
    logger.info("WebSocket connection accepted for conversation: %s", conversation_id)
    
    try:
        while True:
            data = await websocket.receive_text()
            logger.info("Received WebSocket message: %s", data[:200])  # Log first 200 chars
            
            try:
                payload = DeepChatRequest(**json.loads(data))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Malformed payload: %s", exc)
                error_response = {"error": "Neplatný formát zprávy"}
                await websocket.send_text(json.dumps(error_response))
                continue

            user_text = payload.latest_user_text()
            if not user_text:
                logger.warning("No user text found in message")
                error_response = {"error": "Zpráva musí obsahovat text."}
                await websocket.send_text(json.dumps(error_response))
                continue

            logger.info("Processing message from %s: %s", conversation_id, user_text[:50])
            
            try:
                responses = await _run_action(conversation_id, user_text)
                logger.info("Generated %d responses", len(responses))
                
                # Send each response as a separate JSON message
                for response in responses:
                    response_json = json.dumps(response.as_payload())
                    logger.info("Sending response: %s", response_json[:200])
                    await websocket.send_text(response_json)
            except Exception as action_exc:  # noqa: BLE001
                logger.exception("Error processing action: %s", action_exc)
                error_response = {"error": "Došlo k chybě při zpracování zprávy"}
                await websocket.send_text(json.dumps(error_response))
                
    except WebSocketDisconnect:
        logger.info("Websocket disconnected for %s", conversation_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Websocket error: %s", exc)
        try:
            await websocket.close(code=1011, reason="Internal server error")
        except Exception:  # noqa: BLE001, S110
            pass
