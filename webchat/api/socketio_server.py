"""Socket.IO server implementing Rasa webchat protocol."""
import asyncio
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

import socketio
from redis.asyncio import Redis

from actions_bridge import ActionBridge, RasaDispatcher, TrackerAdapter
from query_cache import QueryCache
from rate_limiter import RedisRateLimiter
from settings import get_settings
from slot_cache import SlotCache
from tracker_store import RedisTrackerStore
from db_utils import close_db_pool

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

settings = get_settings()

# Log the allowed origins for debugging
logger.info(f"Allowed CORS origins: {settings.allowed_origins}")

# Create Socket.IO server with CORS support
# python-socketio accepts a list of origins or '*' for all
sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins=settings.allowed_origins,
    logger=True,
    engineio_logger=True
)

# Global state
redis_client: Optional[Redis] = None
tracker_store: Optional[RedisTrackerStore] = None
rate_limiter: Optional[RedisRateLimiter] = None
slot_cache: Optional[SlotCache] = None
query_cache: Optional[QueryCache] = None
action_bridge = ActionBridge()


async def startup():
    """Initialize Redis and tracker store."""
    global redis_client, tracker_store, rate_limiter, slot_cache, query_cache
    redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
    tracker_store = RedisTrackerStore(redis_client, settings.tracker_ttl_seconds)
    rate_limiter = RedisRateLimiter(
        redis_client, settings.rate_limit_max_requests, settings.rate_limit_window_seconds
    )
    slot_cache = SlotCache(redis_client, settings.slot_cache_ttl_seconds)
    query_cache = QueryCache(redis_client, ttl_seconds=300)  # 5 min cache for course/lecture data
    action_bridge.set_slot_cache(slot_cache)
    await redis_client.ping()
    logger.info("Socket.IO webchat server started")


async def shutdown():
    """Cleanup resources."""
    if redis_client:
        await redis_client.close()
    await close_db_pool()


@sio.event
async def connect(sid, environ, auth):
    """Handle client connection."""
    logger.info(f"Client connected: {sid}")
    
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
    logger.info(f"Session confirmed for {sid}: {session_id}")


@sio.event
async def disconnect(sid):
    """Handle client disconnection."""
    session = await sio.get_session(sid)
    session_id = session.get('session_id', 'unknown')
    logger.info(f"Client disconnected: {sid} (session: {session_id})")


@sio.event
async def user_uttered(sid, data):
    """
    Handle user message from client.
    
    Expected data format:
    {
        "message": "hello" or "/intent{\"entity\":\"value\"}",
        "session_id": "abc123",
        "customData": {...},
        "metadata": {...}
    }
    """
    logger.info(f"user_uttered from {sid}: {data}")
    
    try:
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
        if not await rate_limiter.allow(session_id):
            logger.warning(f"Rate limit exceeded for session {session_id}")
            await sio.emit('bot_uttered', {
                'text': 'Příliš mnoho požadavků, zkuste to prosím později.',
                'timestamp': int(time.time() * 1000)
            }, room=sid)
            return
        
        # Optional: Send typing indicator
        await sio.emit('bot_uttered', {'status': 'typing'}, room=sid)
        
        # Merge customData and metadata
        metadata = data.get('metadata', {})
        custom_data = data.get('customData', {})
        
        # Merge custom_data into metadata (Rasa webchat sends customData)
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
        
        # Run action with followup loop (mimics Rasa's FollowupAction behavior)
        max_followups = 50  # Prevent infinite loops
        followup_count = 0
        action_name = settings.default_action_name
        
        while followup_count < max_followups:
            # Run the action
            result = await action_bridge.run(action_name, tracker, dispatcher)
            
            # Persist bot messages to tracker store before sending
            if dispatcher.messages:
                bot_events = []
                for msg in dispatcher.messages:
                    # Create bot event with same structure
                    bot_event = msg.copy()
                    bot_event['event'] = 'bot'
                    # Extract text for event history
                    if 'text' in msg:
                        bot_event['text'] = msg['text']
                    elif 'attachment' in msg:
                        bot_event['text'] = ''  # Image/attachment has no text
                    else:
                        bot_event['text'] = ''
                    bot_events.append(bot_event)
                
                # Save to tracker store
                await tracker_store.append_bot_events(session_id, bot_events)
            
            # Send queued messages
            await dispatcher.send_all()
            
            # Check for FollowupAction in results
            followup_action = None
            if result:
                for event in result:
                    if hasattr(event, 'name') and event.__class__.__name__ == 'FollowupAction':
                        followup_action = event.name
                        break
            
            # If no followup, exit loop
            if not followup_action:
                break
            
            # If followup is action_listen, stop (user input required)
            if followup_action == 'action_listen':
                break
            
            # Continue with the followup action
            action_name = followup_action
            followup_count += 1
            
            # Refresh tracker state for next iteration
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


# Create ASGI app
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

fastapi_app = FastAPI()

# Add CORS middleware to FastAPI app
fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@fastapi_app.on_event("startup")
async def on_startup():
    await startup()

@fastapi_app.on_event("shutdown")
async def on_shutdown():
    await shutdown()

app = socketio.ASGIApp(
    sio,
    other_asgi_app=fastapi_app,
    socketio_path='socket.io'
)
