import os
import json
import pickle
import traceback
import logging
from typing import Dict, List, Any
from datetime import datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import redis.asyncio as redis
from langchain_openai import ChatOpenAI
from sqlalchemy import select, delete
from sqlalchemy.exc import SQLAlchemyError

from .database import async_session_maker
from .models import ChatSession, ChatMessage
from .ai_config import AIModelConfig, PromptTemplates, MessageFilter

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="EDU-AI Chat API")

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://go.edu-ai.eu", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Redis client (async)
redis_client = redis.Redis(
    host=os.getenv('REDIS_HOST', 'redis'),
    port=int(os.getenv('REDIS_PORT', 6379)),
    db=int(os.getenv('REDIS_DB', 0)),
    decode_responses=False  # Important for pickle
)

# OpenAI model configuration
model = ChatOpenAI(
    model=AIModelConfig.CHAT_MODEL,
    temperature=AIModelConfig.CHAT_TEMPERATURE,
    max_tokens=AIModelConfig.CHAT_MAX_TOKENS,
)

# Configuration from centralized config
MAX_ASSISTANT_RESPONSES = AIModelConfig.MAX_ASSISTANT_RESPONSES
MAX_MESSAGE_LENGTH = AIModelConfig.MAX_MESSAGE_LENGTH
MAX_FIRST_MESSAGE_LENGTH = AIModelConfig.MAX_FIRST_MESSAGE_LENGTH


def prepare_messages_for_ai(messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    Prepare messages for OpenAI API by filtering.
    Uses centralized MessageFilter from ai_config module.
    """
    return MessageFilter.prepare_messages_for_ai(messages)



async def save_chat_to_database(
    session_id: str,
    user_id: int,
    role_id: str,
    messages: List[Dict[str, str]]
):
    """Save chat session and messages to database asynchronously"""
    try:
        async with async_session_maker() as db_session:
            async with db_session.begin():
                # Check if session already exists (Flask creates it on session generation)
                result = await db_session.execute(
                    select(ChatSession).where(ChatSession.id == session_id)
                )
                existing_session = result.scalar_one_or_none()
                
                # Create session only if it doesn't exist (shouldn't happen with new flow)
                if not existing_session:
                    chat_session = ChatSession(
                        id=session_id,
                        user_id=user_id,
                        role_id=role_id
                    )
                    db_session.add(chat_session)
                    logger.info(f"Created chat session {session_id} for user {user_id}")
                
                # Delete existing messages to avoid duplicates (we save full history each time)
                delete_stmt = delete(ChatMessage).where(ChatMessage.session_id == session_id)
                await db_session.execute(delete_stmt)
                
                # Save all messages (skip system messages, only save user/assistant)
                message_index = 0
                for msg in messages:
                    if msg['role'] in ['user', 'assistant']:
                        chat_message = ChatMessage(
                            session_id=session_id,
                            role=msg['role'],
                            content=msg['content'],
                            message_index=message_index
                        )
                        db_session.add(chat_message)
                        message_index += 1
                
                await db_session.commit()
                logger.info(f"Saved {message_index} messages for session {session_id}")
                
    except SQLAlchemyError as e:
        logger.error(f"Database error saving chat {session_id}: {str(e)}")
        logger.error(traceback.format_exc())
        # Don't raise - we don't want to crash the WebSocket
    except Exception as e:
        logger.error(f"Unexpected error saving chat {session_id}: {str(e)}")
        logger.error(traceback.format_exc())


@app.get("/")
async def root():
    """Health check endpoint"""
    return {"status": "ok", "service": "EDU-AI Chat API"}


@app.websocket("/ws/roleplay/{session_id}")
async def roleplay_websocket(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for roleplay chat.
    
    Flow:
    1. Validate session exists in Redis (30s window from Flask)
    2. Load initial chat data (user_id, role, prompts)
    3. Accept WebSocket connection
    4. Process messages up to MAX_ASSISTANT_RESPONSES
    5. Save to database after each assistant response
    """
    messages: List[Dict[str, str]] = []
    user_id: int = None
    role_id: str = None
    assistant_message_count = 0
    
    try:
        # 1. Validate session exists in Redis
        if not await redis_client.exists(f"chat_history:{session_id}"):
            logger.warning(f"Session {session_id} not found in Redis")
            await websocket.close(code=1008, reason="Invalid or expired session")
            return
        
        # 2. Load initial chat data
        chat_data_raw = await redis_client.get(f"chat_history:{session_id}")
        chat_data = pickle.loads(chat_data_raw)
        
        # Delete from Redis (one-time use session)
        await redis_client.delete(f"chat_history:{session_id}")
        
        # Extract user and role information
        user_id = chat_data.get("user_id")
        role_id = chat_data.get("role", {}).get("id", "unknown")
        
        if not user_id:
            logger.error(f"Session {session_id} missing user_id")
            await websocket.close(code=1008, reason="Invalid session data")
            return
        
        # Initialize messages with system prompts
        system_prompt = chat_data.get("system_prompt", "")
        general_info = chat_data.get("general_info", "")
        
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if general_info:
            messages.append({"role": "system", "content": general_info})
        
        logger.info(f"Session {session_id} initialized for user {user_id}, role {role_id}")
        
        # 3. Accept WebSocket connection
        await websocket.accept()
        
        # Send welcome message
        await websocket.send_json({
            "type": "connected",
            "message": "Připojeno k chatovacímu serveru"
        })
        
        # 4. Chat loop
        while True:
            try:
                # Receive user message
                user_message = await websocket.receive_text()
                
                # Validate message length
                user_message_count = len([m for m in messages if m["role"] == "user"])
                is_first_user_message = user_message_count == 0
                max_length = MAX_FIRST_MESSAGE_LENGTH if is_first_user_message else MAX_MESSAGE_LENGTH
                
                if len(user_message) > max_length:
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Zpráva je příliš dlouhá (max {max_length} znaků)"
                    })
                    continue
                
                # Check if limit reached before processing
                if assistant_message_count >= MAX_ASSISTANT_RESPONSES:
                    await websocket.send_json({
                        "type": "limit_reached",
                        "message": f"Dosažen limit {MAX_ASSISTANT_RESPONSES} odpovědí AI"
                    })
                    await websocket.close(code=1000, reason="Message limit reached")
                    break
                
                # Add user message to history
                messages.append({
                    "role": "user",
                    "content": user_message,
                    "timestamp": datetime.utcnow().isoformat()
                })
                
                logger.info(f"Session {session_id}: Received user message ({len(user_message)} chars)")
                
                # Send processing indicator
                await websocket.send_json({
                    "type": "processing",
                    "message": "Generuji odpověď..."
                })
                
                # Prepare messages for AI (filter according to rules)
                ai_messages = prepare_messages_for_ai(messages)
                
                # Call OpenAI API
                response = await model.ainvoke(ai_messages)
                assistant_content = response.content
                
                # Add assistant response to history
                messages.append({
                    "role": "assistant",
                    "content": assistant_content,
                    "timestamp": datetime.utcnow().isoformat()
                })
                assistant_message_count += 1
                
                logger.info(f"Session {session_id}: Generated assistant response #{assistant_message_count}")
                
                # Send response to client
                await websocket.send_json({
                    "type": "message",
                    "content": assistant_content,
                    "message_count": assistant_message_count,
                    "max_messages": MAX_ASSISTANT_RESPONSES
                })
                
                # Save to database after each assistant response
                await save_chat_to_database(session_id, user_id, role_id, messages)
                
                # Check if limit reached after response
                if assistant_message_count >= MAX_ASSISTANT_RESPONSES:
                    await websocket.send_json({
                        "type": "limit_reached",
                        "message": f"Dosažen limit {MAX_ASSISTANT_RESPONSES} odpovědí AI"
                    })
                    await websocket.close(code=1000, reason="Message limit reached")
                    break
                
            except WebSocketDisconnect:
                logger.info(f"Session {session_id}: Client disconnected")
                break
            except Exception as e:
                logger.error(f"Session {session_id}: Error processing message: {str(e)}")
                logger.error(traceback.format_exc())
                await websocket.send_json({
                    "type": "error",
                    "message": "Nastala chyba při zpracování zprávy. Zkuste to znovu."
                })
                # Don't break - allow user to continue
        
    except WebSocketDisconnect:
        logger.info(f"Session {session_id}: WebSocket disconnected during setup")
    except Exception as e:
        logger.error(f"Session {session_id}: Fatal error: {str(e)}")
        logger.error(traceback.format_exc())
        try:
            await websocket.send_json({
                "type": "error",
                "message": "Nastala kritická chyba. Prosím začněte novou konverzaci."
            })
            await websocket.close(code=1011, reason="Internal error")
        except:
            pass
    finally:
        # Final save attempt on disconnect (in case last message wasn't saved)
        if user_id and messages:
            logger.info(f"Session {session_id}: Final cleanup, ensuring data is saved")
            await save_chat_to_database(session_id, user_id, role_id, messages)
        
        # Close Redis connection if needed
        # (connection pooling handles this automatically)