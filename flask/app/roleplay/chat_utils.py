import json
import uuid
import traceback
import openai
import redis
import pickle
import os
import warnings

from app import app, db
from app.models import ChatMessage, ChatSession
from .config import (
    COMPETITION_RUNNING,
    CHAT_TIMEOUT,
    CHAT_TEMPERATURE,
    CHAT_MAX_TOKENS,
    ROLE_GEN_MAX_TOKENS,
    CHAT_HISTORY_TTL
)
from .ai_prompts import BIFROST_API_BASE, BIFROST_API_KEY

# Configure OpenAI to use Bifrost as a unified OpenAI-compatible endpoint
openai.api_key = BIFROST_API_KEY
openai.api_base = BIFROST_API_BASE


def _validate_prefixed_model(model: str) -> None:
    if not isinstance(model, str) or "/" not in model:
        raise ValueError(
            "Invalid model format. Expected provider-prefixed model like 'openai/<model>' or 'groq/<model>'."
        )
    provider, _ = model.split("/", 1)
    if provider not in {"openai", "groq"}:
        raise ValueError(
            "Invalid model provider prefix. Allowed prefixes are 'openai/' and 'groq/'."
        )

# Shared Redis client for roleplay module
redis_client = redis.Redis(
    host=app.config.get('REDIS_HOST', 'redis'),
    port=app.config.get('REDIS_PORT', 6379),
    db=app.config.get('REDIS_DB', 0),
    decode_responses=False  # Important for pickle
)

try:
    redis_client.ping()
    print("Roleplay Redis connection successful.")
except Exception as e:
    print(f"Roleplay Redis connection failed: {str(e)}")
    redis_client = None

def count_assistant_messages(chat_history):
    """Count the number of assistant messages in the chat history"""
    warnings.warn(
        "count_assistant_messages is deprecated and will be removed in a future cleanup.",
        DeprecationWarning,
        stacklevel=2,
    )
    if not chat_history:
        return 0
    return sum(1 for msg in chat_history if msg.get('role') == 'assistant')

def generate_roles_from_subject(subject: str, model: str, request_timeout: int) -> str:
    """
    Generate roleplay personas for a given subject using AI with strict structured outputs.
    
    Uses JSON Schema with strict mode to guarantee valid response format.
    
    Args:
        subject: The subject/topic for which to generate roles (e.g., "Starověký Řím")
        model: The OpenAI model to use for generation
        request_timeout: Timeout in seconds
        
    Returns:
        JSON string containing object with 'roles' array
        
    Raises:
        Exception: If competition has ended or API call fails
    """
    if not COMPETITION_RUNNING:
        raise Exception("Soutěž již skončila. Generování rolí není k dispozici.")

    _validate_prefixed_model(model)
    
    from .ai_prompts import (
        ROLE_GENERATION_SYSTEM_PROMPT,
        ROLE_GENERATION_TEMPERATURE,
        ROLE_NAME_COUNT,
    )
    
    messages = [
        {"role": "system", "content": ROLE_GENERATION_SYSTEM_PROMPT},
        {"role": "user", "content": f"předmět: {subject}"}
    ]
    
    # Phase 1 schema: names only
    role_schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "roleplay_roles_response",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "roles": {
                        "type": "array",
                        "minItems": ROLE_NAME_COUNT,
                        "maxItems": ROLE_NAME_COUNT,
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "title": {
                                    "type": "string",
                                    "minLength": 2,
                                    "maxLength": 80
                                }
                            },
                            "required": ["id", "title"],
                            "additionalProperties": False
                        }
                    }
                },
                "required": ["roles"],
                "additionalProperties": False
            }
        }
    }
    
    try:
        response = openai.ChatCompletion.create(
            model=model,
            messages=messages,
            request_timeout=request_timeout,
            temperature=ROLE_GENERATION_TEMPERATURE,
            max_tokens=ROLE_GEN_MAX_TOKENS,
            response_format=role_schema,
        )
        return response.choices[0].message.content
    except openai.error.OpenAIError as e:
        print(f"OpenAI API error during role generation: {str(e)}")
        raise
    except Exception as e:
        print(f"Unexpected error during role generation: {str(e)}")
        raise


def generate_role_instructions_preview(
    subject: str,
    role_title: str,
    model: str,
    request_timeout: int,
) -> str:
    """Generate editable sidebar instructions for a selected AI-generated role."""
    if not COMPETITION_RUNNING:
        raise Exception("Soutěž již skončila. Generování instrukcí není k dispozici.")

    _validate_prefixed_model(model)

    from .ai_prompts import (
        ROLE_INSTRUCTION_PREVIEW_SYSTEM_PROMPT,
        ROLE_INSTRUCTION_PREVIEW_TEMPERATURE,
        ROLE_INSTRUCTION_PREVIEW_MAX_TOKENS,
    )

    payload = {
        "subject": subject or "obecné vzdělávání",
        "role_title": role_title,
    }

    response_schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "roleplay_instruction_preview_response",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "instructions": {"type": "string"},
                },
                "required": ["instructions"],
                "additionalProperties": False,
            },
        },
    }

    messages = [
        {"role": "system", "content": ROLE_INSTRUCTION_PREVIEW_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]

    try:
        response = openai.ChatCompletion.create(
            model=model,
            messages=messages,
            request_timeout=request_timeout,
            temperature=ROLE_INSTRUCTION_PREVIEW_TEMPERATURE,
            max_tokens=ROLE_INSTRUCTION_PREVIEW_MAX_TOKENS,
            response_format=response_schema,
        )

        raw_content = response.choices[0].message.content
        parsed = json.loads(raw_content)
        instructions = str(parsed.get("instructions", "")).strip()
        if not instructions:
            raise ValueError("AI nevrátila validní instrukce.")
        return instructions
    except openai.error.OpenAIError as e:
        print(f"OpenAI API error during instruction preview generation: {str(e)}")
        raise
    except Exception as e:
        print(f"Unexpected error during instruction preview generation: {str(e)}")
        raise


def get_chat_history(session_id):
    """
    Retrieve chat history from Redis or database.
    First tries Redis for speed, falls back to database if needed.
    """
    try:
        # Try Redis first for performance
        if redis_client:
            chat_history_raw = redis_client.get(f"chat_history:{session_id}")
            if chat_history_raw:
                return pickle.loads(chat_history_raw)
        
        # If not in Redis or Redis failed, check the database
        db_messages = ChatMessage.query.filter_by(session_id=session_id).order_by(ChatMessage.message_index).all()
        if db_messages:
            # Convert to the expected format, ensuring timestamp is converted to string
            chat_history = [
                {
                    "role": msg.role, 
                    "content": msg.content, 
                    "timestamp": msg.timestamp.isoformat() if msg.timestamp else None
                } 
                for msg in db_messages
            ]
            
            # Repopulate Redis for faster future access
            if redis_client:
                try:
                    redis_client.set(
                        f"chat_history:{session_id}", 
                        pickle.dumps(chat_history),
                        ex=86400 * 14  # Expire after 14 days
                    )
                except Exception as e:
                    print(f"Error repopulating Redis with chat history in chat_utils: {str(e)}")
            
            return chat_history
    except Exception as e:
        print(f"Error retrieving chat history in chat_utils: {str(e)}")
        traceback.print_exc()
    
    return None

def save_chat_history(session_id, chat_history):
    """
    Save chat history to both Redis and database for persistence.
    Redis for quick access, database for long-term storage.
    """
    warnings.warn(
        "save_chat_history is deprecated for roleplay websocket flow and will be removed in a future cleanup.",
        DeprecationWarning,
        stacklevel=2,
    )
    if not COMPETITION_RUNNING:
        print("Competition ended - chat history saving disabled")
        return False
    
    try:
        # Save to Redis for quick access (with expiration)
        if redis_client:
            redis_client.set(
                f"chat_history:{session_id}", 
                pickle.dumps(chat_history),
                ex=CHAT_HISTORY_TTL
            )
        
        # Save to database for long-term storage
        # First, clear existing messages to avoid duplicates
        ChatMessage.query.filter_by(session_id=session_id).delete()
        
        # Insert all messages
        for index, message in enumerate(chat_history):
            db_message = ChatMessage(
                session_id=session_id,
                role=message.get('role', 'unknown'),
                content=message.get('content', ''),
                message_index=index
                # timestamp is handled by default in model
            )
            db.session.add(db_message)
        
        db.session.commit()
        return True
    except Exception as e:
        print(f"Error saving chat history in chat_utils: {str(e)}")
        traceback.print_exc()
        db.session.rollback()
        return False

def get_role_by_id(role_id):
    """
    Retrieves role information by ID.
    
    Args:
        role_id: The ID of the role to retrieve
    
    Returns:
        A dict with role information or None if not found
    """
    warnings.warn(
        "get_role_by_id is deprecated and scheduled for removal.",
        DeprecationWarning,
        stacklevel=2,
    )
    try:
        # Handle custom roles
        if isinstance(role_id, str) and role_id.startswith('custom-'):
            return {
                "id": role_id,
                "title": "Vlastní role",
                "brief": "Vlastní role definovaná uživatelem"
            }
        # Handle regular roles (placeholder, replace with actual role fetching if needed)
        # This is a simplified version. If roles are stored in DB or fetched from elsewhere,
        # that logic would go here.
        # For now, it matches the original behavior.
        return {
            "id": role_id,
            "title": f"Role {role_id}", # This might need adjustment if IDs are not user-friendly titles
            "brief": "Expert v této oblasti" 
        }
    except Exception as e:
        print(f"Error retrieving role in chat_utils: {str(e)}")
        return None


def prepare_messages_for_ai(chat_history):
    """
    Prepare chat history for OpenAI API by filtering messages.
    
    Filters out:
    - All but the first system message
    - The first user message (which contains custom instructions)
    - Timestamp fields (OpenAI doesn't need them)
    
    Args:
        chat_history: List of message dictionaries with 'role' and 'content'
    
    Returns:
        Filtered list of messages ready for OpenAI API
    """
    warnings.warn(
        "prepare_messages_for_ai is deprecated in the current roleplay implementation and will be removed.",
        DeprecationWarning,
        stacklevel=2,
    )
    if not chat_history:
        return []
    
    filtered_messages = []
    system_message_added = False
    user_message_count = 0
    
    for msg in chat_history:
        role = msg.get('role')
        
        # Keep only the first system message
        if role == 'system':
            if not system_message_added:
                # Only include role and content, not timestamp
                filtered_messages.append({
                    "role": msg.get('role'),
                    "content": msg.get('content')
                })
                system_message_added = True
            # Skip any additional system messages
            continue
        
        # Skip the first user message (custom instructions)
        if role == 'user':
            user_message_count += 1
            if user_message_count == 1:
                continue  # Skip first user message
        
        # Include all other messages (subsequent user messages and all assistant messages)
        # Only include role and content, not timestamp
        if role in ['user', 'assistant']:
            filtered_messages.append({
                "role": msg.get('role'),
                "content": msg.get('content')
            })
    
    return filtered_messages

def generate_session_id_for_roleplay_chat(role_information):
    session_id = uuid.uuid4()

    if not redis_client:
        raise RuntimeError("Redis is unavailable. Cannot create roleplay session.")

    while redis_client.exists(f"chat_history:{str(session_id)}"):
        session_id = uuid.uuid4()

    redis_client.set(f"chat_history:{str(session_id)}", pickle.dumps(role_information), ex=30)
    return str(session_id)


def delete_roleplay_session_bootstrap(session_id: str) -> bool:
    """Delete one-time roleplay session bootstrap payload from Redis."""
    if not redis_client:
        return False

    try:
        redis_client.delete(f"chat_history:{session_id}")
        return True
    except Exception:
        return False
