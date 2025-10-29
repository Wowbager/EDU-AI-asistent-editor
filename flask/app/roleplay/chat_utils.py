import json
import uuid
import traceback
import openai
import redis
import pickle

from app import app, db
from app.models import ChatMessage, ChatSession

try:
    # Initialize Redis client specifically for chat_utils
    redis_client_chat_utils = redis.Redis(
        host=app.config.get('REDIS_HOST', 'redis'),
        port=app.config.get('REDIS_PORT', 6379),
        db=app.config.get('REDIS_DB', 0),
        decode_responses=False # Important for pickle
    )
    redis_client_chat_utils.ping()
    print("Chat Utils Redis connection successful.")
except Exception as e:
    print(f"Chat Utils Redis connection failed: {str(e)}")
    redis_client_chat_utils = None

# Add competition status check
COMPETITION_RUNNING = True  # Should match views.py

def count_assistant_messages(chat_history):
    """Count the number of assistant messages in the chat history"""
    if not chat_history:
        return 0
    return sum(1 for msg in chat_history if msg.get('role') == 'assistant')

def call_openai_chat_completion(model, messages, request_timeout=600):
    """
    Calls the OpenAI ChatCompletion API and returns the response content.
    Handles API errors.
    """
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
            ),
        }        
        messages_to_send = [general_info] + messages + [general_info]
    else:
        messages_to_send = messages
    
    try:
        # Use higher max_tokens for role generation to ensure complete JSON
        max_tokens_to_use = 800 if is_role_generation else 400
        
        response = openai.ChatCompletion.create(
            model=model,
            messages=messages_to_send,
            request_timeout=request_timeout,
            temperature=1,
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
        if redis_client_chat_utils:
            chat_history_raw = redis_client_chat_utils.get(f"chat_history:{session_id}")
            if chat_history_raw:
                return pickle.loads(chat_history_raw)
        
        # If not in Redis or Redis failed, check the database
        db_messages = ChatMessage.query.filter_by(session_id=session_id).order_by(ChatMessage.message_index).all()
        if db_messages:
            # Convert to the expected format, ensuring timestamp is included
            chat_history = [
                {"role": msg.role, "content": msg.content, "timestamp": msg.timestamp} 
                for msg in db_messages
            ]
            
            # Repopulate Redis for faster future access
            if redis_client_chat_utils:
                try:
                    redis_client_chat_utils.set(
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
        if redis_client_chat_utils:
            redis_client_chat_utils.set(
                f"chat_history:{session_id}", 
                pickle.dumps(chat_history),
                ex=86400 * 14  # Expire after 14 days
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

