import json
import uuid
import traceback
import openai
import redis
import pickle
import os

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

# Configure OpenAI to use Groq API
openai.api_key = os.environ.get("GROQ_KEY")
openai.api_base = "https://api.groq.com/openai/v1"

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
    if not chat_history:
        return 0
    return sum(1 for msg in chat_history if msg.get('role') == 'assistant')

def call_openai_chat_completion(model, messages, request_timeout=None):
    """
    Calls the OpenAI ChatCompletion API and returns the response content.
    Handles API errors.
    """
    if request_timeout is None:
        request_timeout = CHAT_TIMEOUT
        
    if not COMPETITION_RUNNING:
        raise Exception("Soutěž již skončila. AI chat není k dispozici.")
    
    # Check if this is a role generation call (system message contains role generation keywords)
    is_role_generation = False
    if messages and len(messages) > 0:
        system_content = messages[0].get('content', '').lower()
        if 'generování vzdělávacích rolí' in system_content or 'json pole' in system_content:
            is_role_generation = True
    
    # Only add general_info for regular chat, not role generation
    if not is_role_generation:
        # Enhanced general_info prompt for competition - simplified to avoid JSON interference
# Enhanced general_info prompt for competition - simplified to avoid JSON interference
        general_info = {
            "role": "system",
            "content": (
                "Odpovídejte v češtině s konkrétními fakty a detaily. Pro soutěž #NachytejAI buďte přirozeně informovaní, "
                "ale neověřujte každý fakt. Nepoužívejte markdown. Odpovědi by měly být stručné, maximálně 800 znaků. "
                "Za žádných okolností nepoužívejte sprostá slova ani urážky. "
                "Nepoužívejte fráze jako 'jsem jazykový model' nebo 'nemám přístup k internetu'. "
                "Snažte se odpovídat jako daný člověk, ber v potaz co zná a jak by měl odpovídat."
                "nezapomeň, že odpovídáš do chatu, takže se vyhni formálním pozdravům a rozloučením."
                "odpovídej krátce, maximálně 200 slov."
            ),
        }        
        messages_to_send = [general_info] + messages + [general_info]
    else:
        messages_to_send = messages
    
    try:
        # Use higher max_tokens for role generation to ensure complete JSON
        max_tokens_to_use = ROLE_GEN_MAX_TOKENS if is_role_generation else CHAT_MAX_TOKENS
        
        response = openai.ChatCompletion.create(
            model=model,
            messages=messages_to_send,
            request_timeout=request_timeout,
            temperature=CHAT_TEMPERATURE,
            max_tokens=max_tokens_to_use,
        )
        return response.choices[0].message.content
    except openai.error.OpenAIError as e:
        print(f"OpenAI API error in chat_utils: {str(e)}")
        raise
    except Exception as e:
        print(f"An unexpected error occurred during OpenAI call in chat_utils: {str(e)}")
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


