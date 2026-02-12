"""API entrypoint with FastAPI and Socket.IO handlers."""

import asyncio
import json
import logging
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import socketio
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

sys.path.insert(0, str(Path(__file__).parent.parent))

from actions_bridge import ActionBridge, DeepChatDispatcher, RasaDispatcher, TrackerAdapter
from config import get_settings
from db_utils import close_db_pool
from schemas import DeepChatRequest, DeepChatResponse, SessionRequest, SessionResponse
from service_container import get_container, initialize_container, shutdown_container
from tracker_store import RedisTrackerStore

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

settings = get_settings()

sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins=settings.allowed_origins,
    logger=True,
    engineio_logger=True
)

fastapi_app = FastAPI(title="Webchat Service (Clean Architecture)", version="0.2.0")
fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

tracker_store: RedisTrackerStore | None = None
action_bridge = ActionBridge()


@fastapi_app.on_event("startup")
async def startup() -> None:
    """Initialize application dependencies."""
    global tracker_store  # noqa: PLW0603

    container = await initialize_container(
        redis_url=settings.redis_url,
        tracker_ttl=settings.tracker_ttl_seconds,
        slot_cache_ttl=settings.slot_cache_ttl_seconds,
        query_cache_ttl=300,
        rate_limit_max=settings.rate_limit_max_requests,
        rate_limit_window=settings.rate_limit_window_seconds,
    )

    tracker_store = RedisTrackerStore(container.redis, settings.tracker_ttl_seconds)
    action_bridge.set_slot_cache(container.slot_cache)

    logger.info("Webchat service started with clean architecture")
    logger.info("- Domain models: ConversationState, Course, Lecture, Quiz")
    logger.info("- Repositories: CourseRepository, SlotRepository, TaskRepository")
    logger.info("- Infrastructure: Caching, Rate Limiting, LLM Client")
    logger.info("- Action executor: LegacyActionAdapter (ready for agentic replacement)")


def _ensure_services() -> None:
    """Ensure service container is initialized."""
    container = get_container()
    container.ensure_initialized()


@fastapi_app.post("/api/sessions", response_model=SessionResponse)
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
    """Execute a single action for a conversation."""
    _ensure_services()
    container = get_container()

    if not await container.rate_limiter.allow(conversation_id):
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



@fastapi_app.post("/api/chat/{conversation_id}/messages")
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


@fastapi_app.websocket("/ws/{conversation_id}")
async def websocket_endpoint(websocket: WebSocket, conversation_id: str):
    await websocket.accept()
    logger.info("WebSocket connection accepted for conversation: %s", conversation_id)
    
    try:
        while True:
            data = await websocket.receive_text()
            logger.info("Received WebSocket message: %s", data[:200])
            
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


# ============================================================================
# Socket.IO Event Handlers (for Rasa Webchat Protocol)
# ============================================================================

@sio.event
async def connect(sid, environ, auth):
    """Handle Socket.IO client connection."""
    logger.info(f"Socket.IO client connected: {sid}")
    
    # Get session_id from auth or query params
    session_id = None
    if auth and isinstance(auth, dict):
        session_id = auth.get('session_id')
    
    if not session_id:
        # Try to get from query string
        query_string = environ.get('QUERY_STRING', '')
        if 'session_id=' in query_string:
            for param in query_string.split('&'):
                if param.startswith('session_id='):
                    session_id = param.split('=')[1]
                    break
    
    # Generate new session_id if not provided
    if not session_id:
        session_id = str(uuid.uuid4())
    
    # Store session mapping
    await sio.save_session(sid, {'session_id': session_id})
    
    # Get custom data from auth
    custom_data = {}
    if auth and isinstance(auth, dict):
        custom_data = auth.get('customData', {})
    
    # Initialize or load session
    await tracker_store.create_or_load(
        session_id,
        sender_id=session_id,
        metadata=custom_data
    )
    
    # Send session confirmation
    await sio.emit('session_confirm', {'session_id': session_id}, room=sid)
    logger.info(f"Socket.IO session confirmed for {sid}: {session_id}")


@sio.event
async def disconnect(sid):
    """Handle Socket.IO client disconnection."""
    session = await sio.get_session(sid)
    session_id = session.get('session_id', 'unknown')
    logger.info(f"Socket.IO client disconnected: {sid} (session: {session_id})")


@sio.event
async def user_uttered(sid, data):
    """
    Handle user message from Socket.IO client (Rasa webchat protocol).
    
    Expected data format:
    {
        "message": "hello",
        "session_id": "abc123",
        "customData": {...},
        "metadata": {...}
    }
    """
    logger.info(f"user_uttered from {sid}: {data}")
    
    try:
        _ensure_services()
        container = get_container()
        
        # Get session
        session = await sio.get_session(sid)
        session_id = data.get('session_id') or session.get('session_id')
        
        if not session_id:
            await sio.emit('error', {
                'error': 'bad_request',
                'message': 'Missing session_id'
            }, room=sid)
            return
        
        # Get user message
        user_message = data.get('message', '').strip()
        if not user_message:
            return
        
        # Check rate limit
        if not await container.rate_limiter.allow(session_id):
            logger.warning(f"Rate limit exceeded for session {session_id}")
            await sio.emit('bot_uttered', {
                'text': 'Příliš mnoho požadavků, zkuste to prosím později.',
                'timestamp': int(time.time() * 1000)
            }, room=sid)
            return
        
        # Send typing indicator
        await sio.emit('bot_uttered', {'status': 'typing'}, room=sid)
        
        # Merge customData and metadata
        metadata = data.get('metadata', {})
        custom_data = data.get('customData', {})
        if custom_data:
            metadata.update(custom_data)
        
        # Update tracker with user event
        state = await tracker_store.append_user_event(
            session_id,
            user_message,
            input_channel='socketio',
            metadata=metadata
        )
        
        # Create tracker adapter
        tracker = TrackerAdapter(
            sender_id=state['sender_id'],
            events=state.get('events', []),
            latest_input_channel=state.get('latest_input_channel'),
            metadata=state.get('metadata', {})
        )
        
        # Create Rasa dispatcher
        dispatcher = RasaDispatcher(sio, sid)
        
        # Run action with followup loop
        max_followups = 50
        followup_count = 0
        action_name = settings.default_action_name
        
        while followup_count < max_followups:
            result = await action_bridge.run(action_name, tracker, dispatcher)
            
            # Persist bot messages
            if dispatcher.messages:
                bot_events = []
                for msg in dispatcher.messages:
                    bot_event = msg.copy()
                    bot_event['event'] = 'bot'
                    bot_event['text'] = msg.get('text', '')
                    bot_events.append(bot_event)
                await tracker_store.append_bot_events(session_id, bot_events)
            
            # Send queued messages
            await dispatcher.send_all()
            
            # Check for FollowupAction
            followup_action = None
            if result:
                for event in result:
                    if hasattr(event, 'name') and event.__class__.__name__ == 'FollowupAction':
                        followup_action = event.name
                        break
            
            if not followup_action or followup_action == 'action_listen':
                break
            
            action_name = followup_action
            followup_count += 1
            
            # Refresh tracker state
            state = await tracker_store.create_or_load(session_id)
            tracker = TrackerAdapter(
                sender_id=state['sender_id'],
                events=state.get('events', []),
                latest_input_channel=state.get('latest_input_channel'),
                metadata=state.get('metadata', {})
            )
        
    except Exception as e:
        logger.exception(f"Error processing user_uttered: {e}")
        await sio.emit('bot_uttered', {
            'text': 'Došlo k neočekávané chybě.',
            'timestamp': int(time.time() * 1000)
        }, room=sid)


@sio.event
async def session_request(sid, data):
    """Handle session request (optional event)."""
    logger.info(f"session_request from {sid}: {data}")
    
    session = await sio.get_session(sid)
    session_id = session.get('session_id')
    
    await sio.emit('session_confirm', {'session_id': session_id}, room=sid)


# ============================================================================
# Create Combined ASGI App (Socket.IO + FastAPI)
# ============================================================================

# Combine Socket.IO with FastAPI in single ASGI application
app = socketio.ASGIApp(
    sio,
    other_asgi_app=fastapi_app,
    socketio_path='socket.io'
)
