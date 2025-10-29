import json
import uuid
import traceback
from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash
import openai
from flask_login import current_user, login_required
from app import app, db
from app.models import ChatSession, FlaggedResponse, Team, User, ChatMessage, Event # Ensure ChatMessage is imported
import redis
from datetime import datetime, timedelta # Added timedelta

# Import utility functions from chat_utils
from .chat_utils import (
    count_assistant_messages,
    call_openai_chat_completion,
    get_chat_history,
    save_chat_history,
    get_role_by_id
)

# Maximum number of AI responses allowed in a chat session
MAX_AI_RESPONSES = 10
# Maximum user message length in characters
MAX_MESSAGE_LENGTH = 1000
# Maximum length for custom instructions
MAX_CUSTOM_INSTRUCTIONS_LENGTH = 1500

COMPETITION_RUNNING = True  # Set to True when the competition is active

roleplay = Blueprint("roleplay", __name__)

try:
    redis_client = redis.Redis(
        host=app.config.get('REDIS_HOST', 'redis'),
        port=app.config.get('REDIS_PORT', 6379),
        db=app.config.get('REDIS_DB', 0)
    )
    redis_client.ping()
except Exception as e:
    print(f"Redis connection failed: {str(e)}")
    redis_client = None

@roleplay.route("/roles", methods=["GET"])
@login_required
def get_roles():
    """
    Generate roleplay personas for a given subject.
    
    Query Parameters:
        subject: The subject for which to generate roleplay personas
    
    Returns:
        JSON with 5 roleplay personas or an error message
    """
    if not COMPETITION_RUNNING:
        return jsonify({"error": "Soutěž již skončila. Generování rolí není k dispozici."}), 403
    
    # Get the subject from query parameters
    subject = request.args.get("subject")
    print(f"Received request for roles with subject: {subject}")
    
    # Return 400 if subject is not provided
    if not subject:
        return jsonify({"error": "Chybí povinný parametr dotazu: subject"}), 400
    
    if subject.lower() == "test":
        print("Using test subject, returning test roles")
        return jsonify({
            "roles": [
                {
                    "id": str(uuid.uuid4()),
                    "title": "Testovací role 1",
                    "brief": "Toto je testovací role."
                },
                {
                    "id": str(uuid.uuid4()),
                    "title": "Testovací role 2",
                    "brief": "Toto je další testovací role."
                }
            ]
        }), 200
    
    try:
        # Compose the system prompt
        # Simplified system_prompt for get_roles
        system_prompt = """Jste AI pro generování vzdělávacích rolí pro soutěž #NachytejAI. Pro daný předmět vygenerujte PŘESNĚ PĚT rolí bohatých na historické detaily.

KRITICKÉ: Odpověď MUSÍ být POUZE platný JSON. Žádný text před ani po JSON!

PRAVIDLA:
• Role nesmí být urážlivé nebo nevhodné.
• Pro neplatné předměty vraťte prázdné pole: []
• Předmět může být hovorový (čeština, matika, děják, zemák).
• Odpověď: JSON pole s pěti objekty:
[
  {"id": "unikátni_id", "title": "Název role", "brief": "Popis role (2-3 věty)"}
]
• Jazyk: Čeština.
• Role: Historicky reálné osobnosti, profese nebo koncepty.
• Soutěž: Role by měly obsahovat konkrétní fakta.

PŘÍKLAD pro 'Starověký Řím':
[
  {"id": "julius_caesar", "title": "Julius Caesar", "brief": "Římský vojevůdce, dobyl Galii, zavražděn v Senátu."},
  {"id": "rimsky_legionar", "title": "Římský legionář", "brief": "Veterán Caesarovy legie, bojoval u Alessie."},
  {"id": "marcus_aurelius", "title": "Marcus Aurelius", "brief": "Římský císař filozof, vedl války s Markomany."},
  {"id": "cicero", "title": "Cicero", "brief": "Římský řečník, odhalil Catilinu spiknutí."},
  {"id": "spartacus", "title": "Spartacus", "brief": "Gladiátor, vedl povstání otroků proti Římu."}
]"""
        # Make the API call to OpenAI
        messages_for_openai = [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": f"{subject=}"
            }
        ]
        
        content = call_openai_chat_completion(
            model="gpt-4.1", 
            messages=messages_for_openai,
            request_timeout=600
        )
        
        print(f"Raw OpenAI response for subject '{subject}': {repr(content)}")
        
        # Try to clean the response if it has extra text
        content_cleaned = content.strip()
        
        # Multiple attempts to extract valid JSON
        roles_data = None
        
        # Attempt 1: Direct JSON parsing
        try:
            roles_data = json.loads(content_cleaned)
            print(f"Successfully parsed JSON on first attempt for subject: {subject}")
        except json.JSONDecodeError:
            print(f"First JSON parse attempt failed for subject: {subject}")
            
            # Attempt 2: Remove any text before and after JSON array
            import re
            json_match = re.search(r'(\[.*?\])', content_cleaned, re.DOTALL)
            if json_match:
                content_cleaned = json_match.group(1)
                print(f"Extracted JSON pattern: {repr(content_cleaned)}")
                try:
                    roles_data = json.loads(content_cleaned)
                    print(f"Successfully parsed JSON on second attempt for subject: {subject}")
                except json.JSONDecodeError:
                    print(f"Second JSON parse attempt failed for subject: {subject}")
            
            # Attempt 3: Look for individual role objects and reconstruct array
            if roles_data is None:
                role_pattern = r'\{[^{}]*"id"[^{}]*"title"[^{}]*"brief"[^{}]*\}'
                role_matches = re.findall(role_pattern, content_cleaned, re.DOTALL)
                if role_matches:
                    try:
                        reconstructed_json = '[' + ','.join(role_matches) + ']'
                        roles_data = json.loads(reconstructed_json)
                        print(f"Successfully reconstructed JSON from {len(role_matches)} role objects for subject: {subject}")
                    except json.JSONDecodeError:
                        print(f"Failed to reconstruct JSON from role objects for subject: {subject}")
        
        # If all JSON parsing attempts failed, return fallback roles
        if roles_data is None:
            print(f"All JSON parsing attempts failed for subject: {subject}. Using fallback roles.")
            return jsonify({
                "roles": [
                    {
                        "id": f"fallback_role_1_{subject.lower().replace(' ', '_')}",
                        "title": f"Expert na {subject}",
                        "brief": f"Zkušený specialista v oblasti {subject} s hlubokými znalostmi a praktickými zkušenostmi."
                    },
                    {
                        "id": f"fallback_role_2_{subject.lower().replace(' ', '_')}",
                        "title": f"Výzkumník v {subject}",
                        "brief": f"Vědecký pracovník zaměřený na výzkum v oblasti {subject}, publikuje odborné studie."
                    },
                    {
                        "id": f"fallback_role_3_{subject.lower().replace(' ', '_')}",
                        "title": f"Učitel {subject}",
                        "brief": f"Pedagog s dlouholetými zkušenostmi ve výuce {subject} na různých úrovních vzdělávání."
                    },
                    {
                        "id": f"fallback_role_4_{subject.lower().replace(' ', '_')}",
                        "title": f"Praktik v {subject}",
                        "brief": f"Praktický odborník využívající znalosti {subject} v každodenní profesní praxi."
                    },
                    {
                        "id": f"fallback_role_5_{subject.lower().replace(' ', '_')}",
                        "title": f"Student {subject}",
                        "brief": f"Pokročilý student oboru {subject} s velkým zájmem a základními praktickými zkušenostmi."
                    }
                ]
            }), 200
        
        # Validate the structure of roles_data
        if not isinstance(roles_data, list):
            print(f"OpenAI response for roles was not a list for subject: {subject}. Response: {content}")
            # If the prompt asked for an empty list for invalid subjects, this is okay.
            if roles_data == []: # Explicitly empty list as per prompt for bad subject
                return jsonify({"roles": []}), 200
            return jsonify({"error": "Odpověď od AI pro generování rolí neměla očekávaný formát."}), 500

        validated_roles = []
        for role_candidate in roles_data:
            if isinstance(role_candidate, dict) and \
               'id' in role_candidate and \
               'title' in role_candidate and \
               'brief' in role_candidate:
                validated_roles.append({
                    "id": str(role_candidate['id']),
                    "title": str(role_candidate['title']),
                    "brief": str(role_candidate['brief'])
                })
            else:
                print(f"Malformed role object from OpenAI: {role_candidate} for subject: {subject}")
        
        # If after validation, no roles, and it wasn't an intentional empty list for bad subject
        if not validated_roles and not (isinstance(roles_data, list) and not roles_data):
            print(f"No valid roles were extracted from OpenAI response for subject: {subject}. Response: {content}")
            return jsonify({"error": "AI nevrátila žádné validní role."}), 500
        
        return jsonify({"roles": validated_roles}), 200
            
    except openai.error.OpenAIError as e:
        print(f"OpenAI API error during get_roles: {str(e)}")
        return jsonify({"error": f"Chyba API OpenAI: {str(e)}"}), 503
    except Exception as e:
        # Handle any other exceptions with more detailed logging
        print(f"Unexpected error during get_roles for subject '{subject}': {str(e)}")
        traceback.print_exc()
        return jsonify({"error": f"Chyba při generování rolí: {str(e)}"}), 500

@roleplay.route("/chat", methods=["POST"])
@login_required
def chat():
    """
    Chat with an AI roleplay persona.
    
    Request JSON:
        {
            "session_id": optional UUID,
            "role_id": string,
            "message": string
        }
    
    Returns:
        JSON with session_id and assistant's reply
    """
    if not COMPETITION_RUNNING:
        return jsonify({"error": "Soutěž již skončila. Chat není k dispozici."}), 403
    
    data = request.get_json()
    
    if not data:
        return jsonify({"error": "Chybějící tělo požadavku"}), 400
    role_id = data.get("role_id")
    message = data.get("message")
    if not role_id:
        return jsonify({"error": "Chybějící povinné pole: role_id"}), 400
    
    session_id = data.get("session_id")
    if message is None:
        return jsonify({"error": "Chybějící povinné pole: message"}), 400
    
    # Check if this is a first message (likely custom instructions)
    is_first_message = session_id is None
    
    # Apply appropriate length limit based on whether it's custom instructions or regular message
    max_length = MAX_CUSTOM_INSTRUCTIONS_LENGTH if is_first_message else MAX_MESSAGE_LENGTH
    
    # Check message length
    if len(message) > max_length:
        return jsonify({"error": f"Zpráva překračuje maximální délku {max_length} znaků"}), 400
    
    try:
        if not session_id:
            chat_session = ChatSession(role_id=role_id, user_id=current_user.id)
            db.session.add(chat_session)
            db.session.commit()
            session_id = chat_session.id
            
            current_role_title = None
            current_role_brief = None
            # Ensure subject is fetched from the request data for the first message
            current_subject = data.get("subject")
            if not current_subject: # Fallback if subject somehow not provided
                current_subject = "nespecifikováno"

            if role_id.startswith('custom-'):
                # For custom roles, title and brief are sent in the first message request
                current_role_title = data.get("role_title", "Vlastní role")
                current_role_brief = data.get("role_brief", "Definovaná uživatelem")
            else:
                role_details = get_role_by_id(role_id)
                if not role_details:
                    return jsonify({"error": "Nepodařilo se načíst informace o roli."}), 400
                current_role_title = role_details['title']
                current_role_brief = role_details['brief']
            
            # Enhanced system prompt - this is the main change
            system_prompt_content = (
                f"Jsi AI asistent v roli '{current_role_title}' ({current_role_brief}) pro soutěž #NachytejAI. "
                f"Specializuješ se na předmět '{current_subject}'. "
                "DŮLEŽITÉ INSTRUKCE:\n"
                "• Komunikuj výhradně v češtině.\n"
                "• Uváděj přesná data, místa, čísla, jména a události.\n"
                "• Buď historicky přesný, ale odpovídej přirozeně i na složité otázky.\n"
                "• Poskytuj detaily o době, kultuře a událostech vztahujících se k tématu.\n"
                "• Mluv v první osobě jako historická postava nebo expert.\n"
                "• Nepoužívej markdown.\n"
                "• Zaměř se pouze na oblast '{current_subject}'.\n"
                "• Odpovídej přirozeně, i když si nejsi jistý všemi fakty."
            )
            
            # For the first message, create chat history with system prompt and user instructions
            chat_history = [
                {"role": "system", "content": system_prompt_content},
                {"role": "user", "content": message}
            ]
            
            # For AI call on first message, use only system prompt (without user instructions)
            chat_history_for_ai = [
                {"role": "system", "content": system_prompt_content}
            ]
        else:
            chat_session = ChatSession.query.filter_by(id=session_id, user_id=current_user.id).first()
            
            if not chat_session:
                return jsonify({"error": "Relace chatu nebyla nalezena nebo k ní nemáte přístup."}), 404
            
            chat_history = get_chat_history(session_id)
            if not chat_history:
                return jsonify({"error": "Nepodařilo se načíst historii chatu."}), 500
            
            # Add current user message to history
            chat_history.append({
                "role": "user",
                "content": message
            })
            
            # For AI calls, filter out the first user message (instructions) and system messages
            # Keep only system prompt and actual conversation
            chat_history_for_ai = []
            found_system = False
            first_user_skipped = False
            
            for msg in chat_history:
                if msg.get('role') == 'system' and not found_system:
                    # Keep only the first system message (the actual prompt)
                    chat_history_for_ai.append(msg)
                    found_system = True
                elif msg.get('role') == 'user' and not first_user_skipped:
                    # Skip the first user message (initial instructions)
                    first_user_skipped = True
                    continue
                elif msg.get('role') in ['user', 'assistant']:
                    # Keep all other user and assistant messages
                    chat_history_for_ai.append(msg)
        
        try:
            # Check if chat has reached the maximum number of AI responses
            num_assistant_messages = count_assistant_messages(chat_history)
            if num_assistant_messages >= MAX_AI_RESPONSES:
                return jsonify({"error": "Překročen maximální počet odpovědí AI v této relaci."}), 400
                
            # Determine model for chat completion
            model_for_chat = "gpt-4.1-nano"

            # Use the filtered chat history for AI call
            assistant_reply_content = call_openai_chat_completion(
                model=model_for_chat,
                messages=chat_history_for_ai
            )

            chat_history.append({
                "role": "assistant",
                "content": assistant_reply_content
            })
            
            save_chat_history(chat_session.id, chat_history)
            
            return jsonify({
                "session_id": str(chat_session.id),
                "reply": assistant_reply_content
            }), 200
            
        except openai.error.OpenAIError as e:
            print(f"OpenAI API error during chat: {str(e)}")
            traceback.print_exc()
            return jsonify({"error": f"Chyba API OpenAI: {str(e)}"}), 503
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": f"Došlo k neočekávané chybě při zpracování chatu: {str(e)}"}), 500
    
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Chyba při zpracování požadavku na chat: {str(e)}"}), 500

@roleplay.route("/chat/<session_id>", methods=["GET"])
@login_required
def get_chat_session(session_id):
    """
    Retrieve the chat history for a specific session.
    
    Path Parameters:
        session_id: The ID of the chat session
    
    Returns:
        JSON with chat history
    """
    if not COMPETITION_RUNNING:
        return jsonify({"error": "Soutěž již skončila. Přístup k historii chatu není k dispozici."}), 403
    
    try:
        # Find the chat session
        chat_session = ChatSession.query.filter_by(id=session_id, user_id=current_user.id).first()
        
        if not chat_session:
            return jsonify({"error": "Relace chatu nebyla nalezena."}), 404
        
        # Load chat history
        chat_history = get_chat_history(session_id)
        
        if not chat_history:
            return jsonify({"error": "Historie chatu je prázdná nebo ji nelze načíst."}), 404
        
        # Filter out system messages before sending to frontend
        filtered_chat_history = [msg for msg in chat_history if msg.get('role') != 'system']
        
        # Return the filtered chat history
        return jsonify(filtered_chat_history), 200
        
    except Exception as e:
        print(f"Error retrieving chat session {session_id}: {str(e)}")
        traceback.print_exc()
        return jsonify({"error": f"Chyba při načítání relace chatu: {str(e)}"}), 500

@roleplay.route("/flag", methods=["POST"])
@login_required
def flag_response():
    """
    Flag an inappropriate assistant response from a chat session.
    
    Request JSON:
        {
            "session_id": UUID,
            "message_index": integer (optional) - The index of the assistant message to flag,
            "team_id": integer (optional) - The ID of the team that is flagging this message,
            "is_public": boolean (optional) - Whether this flag should be publicly visible,
            "summary": string (optional) - A brief summary of why the message is flagged
        }
    
    Returns:
        JSON indicating success and the ID of the flagged response
    """
    if not COMPETITION_RUNNING:
        return jsonify({"error": "Soutěž již skončila. Označování zpráv není k dispozici."}), 403
    
    data = request.get_json()
    
    if not data:
        return jsonify({"error": "Chybějící tělo JSON v požadavku."}), 400
    
    session_id = data.get("session_id")
    message_index = data.get("message_index")
    summary = data.get("summary")

    # Make sure message_index is an integer if provided
    try:
        if message_index is not None:
            message_index = int(message_index)
    except (ValueError, TypeError) as e:
        return jsonify({"error": "Neplatný formát message_index."}), 400
    
    # Get team_id and is_public if provided
    team_id = data.get("team_id")
    is_public = data.get("is_public", False)
    
    if not session_id:
        return jsonify({"error": "Chybějící session_id."}), 400
    
    try:
        chat_session = ChatSession.query.get(session_id)
        if not chat_session:
            return jsonify({"error": "Relace chatu nebyla nalezena."}), 404

        # Get chat history for AI analysis
        chat_history = get_chat_history(session_id)
        flagged_content = data.get("flagged_content", "Obsah není k dispozici")
        
        # AI Content Analysis for inappropriate content
        ai_analysis_result = None
        severity_level = "normal"
        
        try:
            # Prepare content for AI analysis
            analysis_prompt = """Analyzujte následující konverzaci a označenou zprávu z AI asistenta na nevhodný obsah. 

KRITÉRIA PRO VYSOCE NEVHODNÝ OBSAH:
- Explicitní sexuální obsah
- Násilí nebo podněcování k násilí
- Diskriminace nebo nenávistné projevy
- Nezákonné aktivity
- Škodlivé nebo nebezpečné pokyny
- Urážlivý nebo dehonestující obsah

Odpovězte ve formátu JSON:
{
    "severity": "low" | "medium" | "high" | "critical",
    "inappropriate_categories": ["kategorie1", "kategorie2"],
    "explanation": "stručné vysvětlení v češtině",
    "requires_immediate_attention": true/false
}

OZNAČENÁ ZPRÁVA:
{flagged_content}

CELÁ KONVERZACE:
{chat_context}"""

            # Include complete chat history for context
            chat_context = ""
            if chat_history and len(chat_history) > 0:
                for i, msg in enumerate(chat_history):
                    if isinstance(msg, dict):
                        role = msg.get('role', 'unknown')
                        content = msg.get('content', '')
                        # Skip system messages for cleaner analysis
                        if role != 'system':
                            chat_context += f"{i}. {role}: {content}\n\n"
            
            analysis_messages = [
                {
                    "role": "system",
                    "content": "Jste AI specializovaný na detekci nevhodného obsahu v českých konverzacích. Analyzujte objektivně a přesně."
                },
                {
                    "role": "user", 
                    "content": analysis_prompt.format(
                        flagged_content=flagged_content,
                        chat_context=chat_context
                    )
                }
            ]
            
            ai_analysis_response = call_openai_chat_completion(
                model="gpt-4.1-mini",
                messages=analysis_messages,
                request_timeout=30
            )
              # Parse AI analysis
            try:
                # Clean the AI response to handle formatting issues
                cleaned_response = ai_analysis_response.strip()
                ai_analysis_result = json.loads(cleaned_response)
                severity_level = ai_analysis_result.get("severity", "normal")
                
                # Auto-mark as requiring attention if high severity
                if severity_level in ["high", "critical"]:
                    is_public = False  # Keep highly inappropriate content private initially
                    
            except json.JSONDecodeError:
                print(f"Failed to parse AI analysis JSON: {ai_analysis_response}", flush=True)
                ai_analysis_result = {
                    "severity": "unknown",
                    "explanation": "Úspěšně nachytaný AI asistent",
                    "requires_immediate_attention": False
                }
            except Exception as ai_error:
                print(f"AI content analysis failed: {str(ai_error)}")
                ai_analysis_result = {
                    "severity": "unknown", 
                    "explanation": "Úspěšně nachytaný AI asistent",
                    "requires_immediate_attention": False
                }
        except:
            print("AI content analysis failed, using fallback values.", flush=True)
            ai_analysis_result = {
                "severity": "unknown", 
                "explanation": "Úspěšně nachytaný AI asistent",
                "requires_immediate_attention": False
            }
        flagged_response_id = str(uuid.uuid4())
        new_flag = FlaggedResponse(
            id=flagged_response_id,
            user_id=current_user.id,
            session_id=session_id,
            content=flagged_content,
            summary=summary,
            team_id=team_id,
            is_public=is_public,
            timestamp=datetime.utcnow()
        )
        
        # Store AI analysis result in the summary if no user summary provided
        if not summary and ai_analysis_result:
            analysis_summary = f"AI analýza: {ai_analysis_result.get('explanation', 'Bez vysvětlení')}"
            if ai_analysis_result.get('inappropriate_categories'):
                analysis_summary += f" | Kategorie: {', '.join(ai_analysis_result['inappropriate_categories'])}"
            new_flag.summary = analysis_summary
        
        db.session.add(new_flag)
        db.session.commit()
        
        response_data = {
            "success": True, 
            "flagged_response_id": flagged_response_id,
            "message": "Odpověď byla úspěšně označena."
        }
        
        # Include AI analysis in response if available
        if ai_analysis_result:
            response_data["ai_analysis"] = {
                "severity": severity_level,
                "requires_attention": ai_analysis_result.get("requires_immediate_attention", False)
            }
            
            # Add warning for high severity content
            if severity_level in ["high", "critical"]:
                response_data["warning"] = "Detekován vysoce nevhodný obsah - automaticky označeno pro okamžitou pozornost."
        
        return jsonify(response_data), 201
        
    except Exception as e:
        db.session.rollback()
        print(f"Error flagging response: {str(e)}")
        traceback.print_exc()
        return jsonify({"error": f"Chyba při označování odpovědi: {str(e)}"}), 500

@roleplay.route("/flagged", methods=["GET"])
@login_required
def flagged_messages():   
    """
    Display all flagged messages with their context.
    
    Query Parameters:
        page: The page number (default: 1)
        per_page: Number of items per page (default: 12)
        view_all: If set to 'true' and user is admin, show all flagged messages
        team_id: If provided, show flagged messages for this team
    
    Returns:
        The rendered flagged messages template
    """
    if not COMPETITION_RUNNING:
        flash("Soutěž již skončila. Přístup k označeným zprávám není k dispozici.", "warning")
        return redirect(url_for("roleplay.public_flagged_messages"))
    
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 12, type=int)
    view_all = request.args.get('view_all', 'false').lower() == 'true'
    team_id = request.args.get('team_id', None, type=int)
    
    is_admin = hasattr(current_user, 'email') and current_user.email.endswith('@admin.com')
    
    # Get user's teams
    user_teams_query = Team.query.join(Team.members).filter(User.id == current_user.id)
    if not is_admin: # Non-admins only see their own teams
        user_teams = user_teams_query.all()
    else: # Admins can see all teams if they choose to filter
        user_teams = Team.query.order_by(Team.name).all()

    # Base query for flagged responses
    query = FlaggedResponse.query.order_by(FlaggedResponse.timestamp.desc())

    if not is_admin:
        # Non-admins see their own flags + flags from their teams (if no specific team is selected)
        # or flags for a specific team they are part of.
        if team_id:
            query = query.filter(FlaggedResponse.team_id == team_id, Team.members.any(User.id == current_user.id)) # Ensure user is part of the team
        else:
            # User's own flags OR flags from any of their teams
            user_team_ids = [t.id for t in user_teams_query.all()]
            query = query.filter(
                db.or_(
                    FlaggedResponse.user_id == current_user.id,
                    FlaggedResponse.team_id.in_(user_team_ids)
                )
            )
    else: # Admin view
        if not view_all: # Admin not viewing all, so filter to their teams or personal
            user_team_ids = [t.id for t in user_teams_query.all()] # Potentially all teams if admin made them members of all
            query = query.filter(
                db.or_(
                    FlaggedResponse.user_id == current_user.id,
                    FlaggedResponse.team_id.in_(user_team_ids) # Only if admin wants to see team-specific and is member
                )
            )
        # If view_all is true, admin sees all flags (no additional team_id based filters on query needed here, unless team_id is also specified)
        if team_id: # Admin can also filter by a specific team
            query = query.filter(FlaggedResponse.team_id == team_id)
        
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    flagged_items = pagination.items
    
    flagged_data = []
    for item in flagged_items:
        team_obj = Team.query.get(item.team_id) if item.team_id else None
        
        full_chat_history = []
        last_two_messages = []
        chat_session = ChatSession.query.get(item.session_id)
        if chat_session:
            # ChatMessages are ordered by message_index by default in the relationship or query them ordered
            messages = ChatMessage.query.filter_by(session_id=item.session_id).order_by(ChatMessage.message_index).all()
            # Filter out system messages
            filtered_messages = [msg for msg in messages if getattr(msg, 'role', '') != 'system']
            full_chat_history = filtered_messages
            last_two_messages = filtered_messages[-2:] if len(filtered_messages) >= 2 else filtered_messages
            
        flagged_data.append({
            "flagged": item,
            "team": team_obj,
            "user": item.user,
            "full_chat_history": full_chat_history,
            "last_two_messages": last_two_messages
        })
        
    return render_template(
        "roleplay/flagged.html", 
        flagged_data=flagged_data, 
        pagination=pagination,
        current_team_id=team_id,
        user_teams=user_teams,
        is_admin=is_admin,
        view_all=view_all
    )

@roleplay.route("/flagged/<flagged_id>/edit", methods=["POST"])
@login_required
def edit_flagged_response(flagged_id):
    """
    Edit the summary and public status of a flagged response.
    
    Path Parameters:
        flagged_id: The ID of the flagged response to edit.
        
    Form Data:
        summary: The new summary for the flagged response.
        is_public: 'true' or 'false' string to set the public status.
        
    Returns:
        JSON response indicating success or failure.
    """
    if not COMPETITION_RUNNING:
        return jsonify({"success": False, "message": "Soutěž již skončila. Úprava označení není k dispozici."}), 403
    
    try:
        flagged_response = FlaggedResponse.query.get(flagged_id)
        
        if not flagged_response:
            return jsonify({"success": False, "message": "Označení nebylo nalezeno."}), 404 # Added return
            
        # Check permissions: user who flagged or an admin
        is_admin = hasattr(current_user, 'email') and current_user.email.endswith('@admin.com')
        if flagged_response.user_id != current_user.id and not is_admin:
            return jsonify({"success": False, "message": "Nemáte oprávnění k úpravě tohoto označení."}), 403 # Added return
            
        new_summary = request.form.get("summary")
        is_public_str = request.form.get("is_public")

        if new_summary is None: # Check if summary is part of the form at all
            return jsonify({"success": False, "message": "Chybí shrnutí (summary)."}), 400
            
        if not isinstance(new_summary, str) or len(new_summary.strip()) == 0:
            return jsonify({"success": False, "message": "Shrnutí nesmí být prázdné."}), 400 # Added return

        flagged_response.summary = new_summary.strip()
        
        # Update is_public status
        if is_public_str is not None:
            flagged_response.is_public = is_public_str.lower() == 'true'
        
        db.session.commit()
        
        return jsonify({"success": True, "message": "Označení bylo úspěšně aktualizováno."})
        
    except Exception as e:
        db.session.rollback()
        print(f"Error editing flagged response: {str(e)}")
        traceback.print_exc()
        return jsonify({"success": False, "message": f"Chyba při úpravě označení: {str(e)}"}), 500 # Added return


@roleplay.route("/public_flags", methods=["GET"])
def public_flagged_messages():
    """
    Display all publicly flagged messages.
    This page is accessible without login.
    """
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 12, type=int)

    query = FlaggedResponse.query.filter_by(is_public=True)
    pagination = query.order_by(FlaggedResponse.timestamp.desc()).paginate(page=page, per_page=per_page, error_out=False)
    public_flags_db = pagination.items

    published_flags_data = []
    for flagged_item in public_flags_db:
        chat_history = get_chat_history(flagged_item.session_id)
        team = Team.query.get(flagged_item.team_id) if flagged_item.team_id else None
        
        # Convert ChatMessage objects to dicts if get_chat_history returns them
        processed_chat_history = []
        if chat_history:
            for msg in chat_history:
                # Filter out system messages
                if isinstance(msg, dict):
                    if msg.get('role') != 'system':
                        processed_chat_history.append(msg)
                else:
                    # If ChatMessage objects, convert them and filter
                    msg_role = getattr(msg, 'role', 'unknown')
                    if msg_role != 'system':
                        processed_chat_history.append({"role": msg_role, "content": getattr(msg, 'content', '')})
        
        published_flags_data.append({
            "flagged": flagged_item,
            "team": team,
            "chat_history": processed_chat_history
        })

    return render_template(
        "roleplay/published_flagged_messages.html",
        published_flags=published_flags_data,
        pagination=pagination
    )

@roleplay.route("/update_flagged_summary/<flagged_id>", methods=["POST"])
@login_required
def update_flagged_summary(flagged_id):
    """
    Update the summary of a flagged response.
    Only the user who created the flag can update it.
    """
    if not COMPETITION_RUNNING:
        return jsonify({"success": False, "error": "Soutěž již skončila. Aktualizace shrnutí není k dispozici."}), 403
    
    try:
        flagged_response = FlaggedResponse.query.get(flagged_id)
        
        if not flagged_response:
            return jsonify({"success": False, "error": "Označení nebylo nalezeno."}), 404
            
        # Check permissions: only the user who flagged can edit
        if flagged_response.user_id != current_user.id:
            return jsonify({"success": False, "error": "Nemáte oprávnění k úpravě tohoto označení."}), 403
            
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "Chybějící JSON data."}), 400
            
        new_summary = data.get("summary", "").strip()
        
        if not new_summary:
            return jsonify({"success": False, "error": "Shrnutí nesmí být prázdné."}), 400

        flagged_response.summary = new_summary
        db.session.commit()
        
        return jsonify({"success": True, "message": "Shrnutí bylo úspěšně aktualizováno."})
        
    except Exception as e:
        db.session.rollback()
        print(f"Error updating flagged summary: {str(e)}")
        traceback.print_exc()
        return jsonify({"success": False, "error": f"Chyba při aktualizaci shrnutí: {str(e)}"}), 500

@roleplay.route("/unpublish_flagged/<flagged_id>", methods=["POST"])
@login_required
def unpublish_flagged(flagged_id):
    """
    Make a flagged response private (unpublish it).
    Only the user who created the flag can unpublish it.
    """
    if not COMPETITION_RUNNING:
        return jsonify({"success": False, "error": "Soutěž již skončila. Rušení zveřejnění není k dispozici."}), 403
    
    try:
        flagged_response = FlaggedResponse.query.get(flagged_id)
        
        if not flagged_response:
            return jsonify({"success": False, "error": "Označení nebylo nalezeno."}), 404
            
        # Check permissions: only the user who flagged can unpublish
        if flagged_response.user_id != current_user.id:
            return jsonify({"success": False, "error": "Nemáte oprávnění k úpravě tohoto označení."}), 403
            
        # Set is_public to False to make it private
        flagged_response.is_public = False
        db.session.commit()
        
        return jsonify({"success": True, "message": "Zpráva byla úspěšně zrušena ze zveřejnění."})
        
    except Exception as e:
        db.session.rollback()
        print(f"Error unpublishing flagged response: {str(e)}")
        traceback.print_exc()
        return jsonify({"success": False, "error": f"Chyba při rušení zveřejnění: {str(e)}"}), 500

@roleplay.route("/", methods=["GET"])
@login_required
def roleplay_home():
    """
    Render the roleplay chat interface
    
    Returns:
        The rendered roleplay template
    """
    if not COMPETITION_RUNNING:
        flash("Soutěž již skončila. Chat není k dispozici. Můžete si prohlédnout veřejně označené zprávy.", "info")
        return redirect(url_for("roleplay.public_flagged_messages"))
    
    user_teams = current_user.teams # Get user's teams
    return render_template("roleplay/index.html", user_teams=user_teams) # Pass user_teams to template

@roleplay.route("/teams", methods=["GET"])
@login_required
def teams():
    """
    List all teams and provide functionality for the user to create or join a team
    
    Returns:
        Rendered template showing teams
    """
    if not COMPETITION_RUNNING:
        flash("Soutěž již skončila. Správa týmů není k dispozici.", "warning")
        return redirect(url_for("roleplay.public_flagged_messages"))
    
    # Get user's teams
    user_teams_db = current_user.teams # This is already a list-like collection
    app.logger.info(f"--- Initial user_teams_db (current_user.teams): {list(user_teams_db)} ---") # Log initial state
    
    # Get all teams
    all_teams_db = Team.query.order_by(Team.name).all()
    app.logger.info(f"--- Initial all_teams_db: {list(all_teams_db)} ---") # Log initial state

    def process_team_description(team_list):
        processed_teams = []
        app.logger.info(f"--- process_team_description called with team_list: {team_list} ---")
        if not team_list:
            app.logger.warning("--- process_team_description received an empty or None team_list ---")
            return []
            
        for team_obj in team_list:
            # Initialize attributes
            team_obj.creator_id = None
            team_obj.display_description = "Tento tým nemá popis." # Default if no description or parsing fails

            if team_obj.description: # Only proceed if there's a description string
                try:
                    description_data = json.loads(team_obj.description)
                    if isinstance(description_data, dict):
                        # Successfully parsed to a dictionary
                        team_obj.display_description = description_data.get("original_description", team_obj.description) # Use original_description from JSON if present
                        
                        parsed_creator_id = description_data.get("creator_id")
                        if parsed_creator_id is not None:
                            try:
                                team_obj.creator_id = int(parsed_creator_id)
                            except (ValueError, TypeError):
                                app.logger.warning(f"Team '{team_obj.name}': creator_id '{parsed_creator_id}' is not a valid integer. Kept as None.")
                                pass 
                    else:
                        # Parsed to JSON, but not a dictionary. Use raw description.
                        team_obj.display_description = team_obj.description
                except (json.JSONDecodeError, TypeError):
                    # Failed to parse JSON or description was not a string. Use raw description.
                    app.logger.warning(f"Team '{team_obj.name}': Failed to parse description JSON. Raw description: {team_obj.description}")
                    team_obj.display_description = team_obj.description if team_obj.description else "Chyba při čtení popisu."
            
            processed_teams.append(team_obj)
        app.logger.info(f"--- process_team_description finished, processed_teams: {processed_teams} ---")
        return processed_teams

    # Process a copy by converting to list if it's not already (e.g. InstrumentedList)
    user_teams_processed = process_team_description(list(user_teams_db)) 
    all_teams_processed = process_team_description(list(all_teams_db))

    # ---- START DEBUG LOGGING ----
    app.logger.info("--- Debugging user_teams_processed in /teams (now /soutez/teams) route ---")
    if not user_teams_processed:
        app.logger.warning("--- user_teams_processed is empty or None. No teams to loop through for detailed logging. ---")
    for team_item in user_teams_processed:
        app.logger.info(f"Team Name: {team_item.name}, Team ID: {team_item.id}, Type of ID: {type(team_item.id)}, Creator ID: {team_item.creator_id}, Type of Creator ID: {type(team_item.creator_id)}")
        app.logger.info(f"Current User ID: {current_user.id}, Type: {type(current_user.id)}")
        if team_item.id is not None and team_item.creator_id == current_user.id:
            app.logger.info(f"Condition MET for team {team_item.name} (ID: {team_item.id}) to show 'Edit Members' button.")
            try:
                # Attempt to build URL here to see if it fails at this stage with known good values
                test_url = url_for('roleplay.edit_team_members', team_id=team_item.id)
                app.logger.info(f"Successfully built test URL for edit_team_members: {test_url}")
            except Exception as e_url:
                app.logger.error(f"ERROR building test URL for edit_team_members for team ID {team_item.id}: {e_url}")
        else:
            is_id_none = team_item.id is None
            is_creator_match = team_item.creator_id == current_user.id if team_item.creator_id is not None and current_user.id is not None else False
            app.logger.info(f"Condition NOT MET for team {team_item.name} (ID: {team_item.id}). ID is None: {is_id_none}, Creator matches current user: {is_creator_match} (Creator: {team_item.creator_id}, Current User: {current_user.id})")
    app.logger.info("--- End Debugging /teams (now /soutez/teams) route ---")
    # ---- END DEBUG LOGGING ----
    
    return render_template(
        "roleplay/teams.html",
        user_teams=user_teams_processed,
        all_teams=all_teams_processed
    )

@roleplay.route("/teams/<int:team_id>/metrics", methods=["GET"])
@login_required
def get_team_metrics(team_id):
    """
    Get metrics for a specific team
    
    Args:
        team_id: ID of the team to get metrics for
        
    Returns:
        JSON with team metrics
    """
    if not COMPETITION_RUNNING:
        return jsonify({"error": "Soutěž již skončila. Metriky týmů nejsou k dispozici."}), 403
    
    team = Team.query.get_or_404(team_id)
    
    # Parse team description to get the display description
    display_description = "Bez popisu"
    if team.description:
        try:
            description_data = json.loads(team.description)
            if isinstance(description_data, dict):
                display_description = description_data.get("original_description", "Bez popisu")
                if not display_description.strip():
                    display_description = "Bez popisu"
            else:
                # If description is not JSON or not a dict, use it directly
                display_description = team.description
        except (json.JSONDecodeError, TypeError):
            # If parsing fails, use raw description
            display_description = team.description if team.description else "Bez popisu"
    
    # Count published flags for this team
    published_flags_count = FlaggedResponse.query.filter_by(
        team_id=team_id, 
        is_public=True
    ).count()
    
    # Count total flags for this team
    total_flags_count = FlaggedResponse.query.filter_by(team_id=team_id).count()
    
    # Get team creation date
    created_date = team.created_at.strftime('%d.%m.%Y') if team.created_at else "Neznámo"
    
    # Count active chat sessions from team members (last 30 days)
    time_30_days_ago = datetime.utcnow() - timedelta(days=30)
    team_member_ids = [member.id for member in team.members]
    active_sessions_count = ChatSession.query.filter(
        ChatSession.user_id.in_(team_member_ids),
        ChatSession.created_at >= time_30_days_ago
    ).count()
    
    return jsonify({
        "member_count": team.members.count(),
        "published_flags": published_flags_count,
        "total_flags": total_flags_count,
        "created_date": created_date,
        "active_sessions_30d": active_sessions_count,
        "team_name": team.name,
        "description": display_description
    })

@roleplay.route("/teams/new", methods=["GET", "POST"])
@login_required
def new_team():
    """
    Create a new team
    
    Returns:
        Redirects to teams page on success
    """
    if not COMPETITION_RUNNING:
        flash("Soutěž již skončila. Vytváření nových týmů není k dispozici.", "warning")
        return redirect(url_for("roleplay.public_flagged_messages"))
    
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        original_description = request.form.get("description", "").strip()
        # Handle the new members[] array format
        members_list = request.form.getlist("members[]")
        member_emails_to_add = [email.strip() for email in members_list if email.strip()]
        
        if not name:
            flash("Název týmu nesmí být prázdný.", "danger")
            return render_template("roleplay/new_team.html", name=name, description=original_description)
            
        if Team.query.filter_by(name=name).first():
            flash(f"Tým s názvem '{name}' již existuje.", "warning")
            return render_template("roleplay/new_team.html", name=name, description=original_description)

        # Prepare structured data for the description field with creator_id
        team_data_for_description = {
            "creator_id": str(current_user.id),  # Add creator_id here
            "original_description": original_description,
            "invited_member_emails": member_emails_to_add 
        }
        
        # Create the team
        team = Team(name=name, description=json.dumps(team_data_for_description))
        
        # Add the current user as a member
        team.members.append(current_user)
        
        # Add other specified members
        added_members_count = 0
        not_found_emails = []
        if member_emails_to_add:
            for email in member_emails_to_add:
                user_to_add = User.query.filter_by(email=email).first()
                if user_to_add:
                    if user_to_add not in team.members: # Avoid adding duplicates if creator is also in list
                        team.members.append(user_to_add)
                        added_members_count += 1
                else:
                    not_found_emails.append(email)
        
        db.session.add(team)
        db.session.commit()
        
        flash_message = f"Tým '{name}' byl vytvořen"
        if added_members_count > 0:
            flash_message += f" a {added_members_count} člen(ů) bylo přidáno."
        else:
            flash_message += "."
        
        if not_found_emails:
            flash_message += f" Uživatelé s e-maily: {', '.join(not_found_emails)} nebyli nalezeni a přidáni."
        
        flash(flash_message, "success")
        return redirect(url_for("roleplay.teams"))
        
    return render_template("roleplay/new_team.html")

@roleplay.route("/teams/<int:team_id>/leave", methods=["POST"])
@login_required
def leave_team(team_id):
    """
    Leave a team
    
    Args:
        team_id: ID of the team to leave
        
    Returns:
        Redirects to teams page on success
    """
    if not COMPETITION_RUNNING:
        flash("Soutěž již skončila. Opuštění týmu není k dispozici.", "warning")
        return redirect(url_for("roleplay.public_flagged_messages"))
    
    team = Team.query.get_or_404(team_id)
    
    # Check if the user is a member
    if team in current_user.teams:
        # Check if the user is not the last member
        if team.members.count() > 1:
            team.members.remove(current_user)
            db.session.commit()
        else:
            # User is the last member, so delete the team
            db.session.delete(team)
            db.session.commit()
        
    return redirect(url_for("roleplay.teams"))

@roleplay.route("/teams/<int:team_id>/edit_members", methods=["GET", "POST"])
@login_required
def edit_team_members(team_id):
    if not COMPETITION_RUNNING:
        flash("Soutěž již skončila. Úprava členů týmu není k dispozici.", "warning")
        return redirect(url_for("roleplay.public_flagged_messages"))
    
    team = Team.query.get_or_404(team_id)
    
    # --- Authorization: Parse team.description to get creator_id ---
    auth_creator_id = None
    original_description_text_for_auth = "" # Used if needed later for context
    if team.description:
        try:
            description_data = json.loads(team.description)
            if isinstance(description_data, dict):
                original_description_text_for_auth = description_data.get("original_description", "")
                parsed_creator_id = description_data.get("creator_id")
                if parsed_creator_id is not None:
                    auth_creator_id = int(parsed_creator_id)
        except (json.JSONDecodeError, TypeError, ValueError):
            # Fallback to raw description if parsing fails
            original_description_text_for_auth = team.description 
            app.logger.warning(f"Team ID {team.id}: for edit authorization, description was not valid JSON or creator_id was missing/malformed. Raw description: '{team.description}'")

    if auth_creator_id != current_user.id:
        flash("Nemáte oprávnění upravovat členy tohoto týmu.", "danger")
        return redirect(url_for("roleplay.teams"))

    if request.method == "POST":
        # --- Handle removing members ---
        members_to_remove_ids = request.form.getlist("remove_member")
        for member_id_str in members_to_remove_ids:
            try:
                member_id_to_remove = int(member_id_str)
                if member_id_to_remove == current_user.id:
                    continue
                member_to_remove = User.query.get(member_id_to_remove)
                if member_to_remove and member_to_remove in team.members:
                    team.members.remove(member_to_remove)
            except ValueError:
                pass
        
        # --- Handle adding new members ---
        new_members_list = request.form.getlist("new_members[]")
        new_member_emails_to_add = [email.strip() for email in new_members_list if email.strip()]
        
        # --- Prepare for updating team.description JSON ---
        # Preserve original_description and manage invited_member_emails
        final_original_description = "" 
        current_invited_emails = []

        if team.description:
            try:
                desc_data = json.loads(team.description)
                if isinstance(desc_data, dict):
                    final_original_description = desc_data.get("original_description", "")
                    current_invited_emails = desc_data.get("invited_member_emails", [])
                else: # Was JSON but not a dict, treat original text as description
                    final_original_description = team.description 
            except (json.JSONDecodeError, TypeError):
                 # Not JSON, treat as plain text for original_description
                 final_original_description = team.description if team.description else ""
        
        updated_invited_emails = list(current_invited_emails) # Start with existing invited emails

        if new_member_emails_to_add:
            current_team_member_emails = [m.email for m in team.members] # Get current members *after* removals

            for email in new_member_emails_to_add:
                if email in current_team_member_emails: # Check if already a member
                    if email in updated_invited_emails: # If they were invited, remove from list
                        updated_invited_emails.remove(email)
                    continue
                
                user_to_add = User.query.filter_by(email=email).first()
                if user_to_add:
                    if user_to_add not in team.members:
                        team.members.append(user_to_add)
                    
                    if email in updated_invited_emails: # If they were invited, remove from list
                        updated_invited_emails.remove(email)
                else:
                    if email not in updated_invited_emails: # Add to invited if not found and not already invited
                         updated_invited_emails.append(email)
        
        # Construct the new description JSON
        new_description_json_content = {
            "creator_id": str(current_user.id), 
            "original_description": final_original_description,
            "invited_member_emails": updated_invited_emails
        }
        team.description = json.dumps(new_description_json_content)
        
        db.session.commit()
        return redirect(url_for("roleplay.edit_team_members", team_id=team.id))

    # --- GET request ---
    # Ensure team object passed to template has members loaded for display
    team_members = team.members.all() 
    
    # For the template, ensure team.name and other attributes are directly accessible
    # The team object itself is passed, which is fine.
    
    return render_template("roleplay/edit_team_members.html", team=team, team_members=team_members, current_user_id=current_user.id)

# Hardcoded admin email for the new admin check page
ADMIN_EMAIL = "youradmin@example.com"

@roleplay.route("/admin-email-check", methods=["GET"])
@login_required
def admin_email_check():
    """
    Admin page that checks if the current user's email matches a hardcoded admin email.
    """
    if hasattr(current_user, 'email') and current_user.email == ADMIN_EMAIL:
        return "Přístup povolen: E-mail administrátora se shoduje.", 200 # Added return
    else:
        return "Přístup odepřen: E-mail se neshoduje s e-mailem administrátora.", 403 # Added return

@roleplay.route("/admin-dashboard", methods=["GET"])
@login_required
def admin_dashboard():
    """
    Admin page to view all chats, teams, and flagged messages.
    Only accessible to users with the hardcoded admin email.
    """
    if not (hasattr(current_user, 'email') and current_user.email == ADMIN_EMAIL):
        flash("Přístup odepřen: Nemáte oprávnění k zobrazení této stránky.", "danger")
        return redirect(url_for("roleplay.roleplay_home"))

    # Fetching data for summary cards (counts not requiring pagination)
    total_users = User.query.count()
    time_24_hours_ago = datetime.utcnow() - timedelta(days=1)
    chats_last_24h = ChatSession.query.filter(ChatSession.created_at >= time_24_hours_ago).count()
    flags_last_24h = FlaggedResponse.query.filter(FlaggedResponse.timestamp >= time_24_hours_ago).count()

    # Pagination parameters
    page_chats = request.args.get('page_chats', 1, type=int)
    page_teams = request.args.get('page_teams', 1, type=int)
    page_flags = request.args.get('page_flags', 1, type=int)
    PER_PAGE = 12  # Items per page, updated from 10 to 12

    # Paginated queries
    all_chats_pagination = ChatSession.query.order_by(ChatSession.created_at.desc()).paginate(
        page=page_chats, per_page=PER_PAGE, error_out=False
    )
    all_teams_pagination = Team.query.order_by(Team.name).paginate(
        page=page_teams, per_page=PER_PAGE, error_out=False
    )
    all_flagged_messages_pagination = FlaggedResponse.query.order_by(FlaggedResponse.timestamp.desc()).paginate(
        page=page_flags, per_page=PER_PAGE, error_out=False
    )

    return render_template(
        "roleplay/admin_dashboard.html",
        total_users=total_users,
        chats_last_24h=chats_last_24h,
        flags_last_24h=flags_last_24h,
        all_chats_pagination=all_chats_pagination,
        all_teams_pagination=all_teams_pagination,
        all_flagged_messages_pagination=all_flagged_messages_pagination
    )

@roleplay.route("/admin/chat_history/<session_id>", methods=["GET"])
@login_required
def admin_chat_history(session_id):
    """
    Admin view for a specific chat session's history.
    Only accessible to users with the hardcoded admin email.
    """
    if not (hasattr(current_user, 'email') and current_user.email == ADMIN_EMAIL):
        flash("Přístup odepřen: Nemáte oprávnění k zobrazení této stránky.", "danger")
        return redirect(url_for('roleplay.roleplay_home'))

    # Fetch the chat session object
    chat_session = ChatSession.query.get(session_id)
    if not chat_session:
        flash(f"Chat session {session_id} nebyl nalezen.", "error")
        return redirect(url_for('roleplay.admin_dashboard'))

    chat_history = get_chat_history(session_id)
    flagged_messages_for_session = FlaggedResponse.query.filter_by(session_id=session_id).all()
    # Create a dictionary for quick lookup of flagged messages by index
    flagged_indices = {fm.message_index: fm for fm in flagged_messages_for_session if fm.message_index is not None}

    # Ensure chat_history is a list of dicts with 'role', 'content', and 'timestamp' (if available)
    # If get_chat_history returns None or raises an error, handle it gracefully
    if chat_history is None:
        flash(f"Nepodařilo se načíst historii chatu pro relaci {session_id}.", "warning")
        chat_history = []
    else:
        # Filter out system messages for admin view as well
        chat_history = [msg for msg in chat_history if msg.get('role') != 'system']

    return render_template(
        "roleplay/admin_chat_history.html",
        session_id=session_id,
        chat_session=chat_session,
        chat_history=chat_history,
        flagged_indices=flagged_indices,
        flagged_messages_for_session=flagged_messages_for_session
    )


@roleplay.route("/ulovky", methods=["GET"])
def public_ulovky():
    """
    Display all publicly flagged messages (ulovky) with pagination.
    This page is accessible without login.
    
    Query Parameters:
        page: The page number (default: 1)
        per_page: Number of items per page (default: 12)
    
    Returns:
        The rendered public flagged messages template
    """
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 12, type=int)

    # Query for public flagged responses only
    query = FlaggedResponse.query.filter_by(is_public=True)
    pagination = query.order_by(FlaggedResponse.timestamp.desc()).paginate(
        page=page, 
        per_page=per_page, 
        error_out=False
    )
    public_flags_db = pagination.items

    public_flags_data = []
    for flagged_item in public_flags_db:
        try:
            # Get basic session info
            session = ChatSession.query.get(flagged_item.session_id)
            user = User.query.get(flagged_item.user_id)
            team = Team.query.get(flagged_item.team_id) if flagged_item.team_id else None
            
            # Prepare flag data
            flag_data = {
                'id': flagged_item.id,
                'content': flagged_item.content,
                'summary': flagged_item.summary or "Bez shrnutí",
                'timestamp': flagged_item.timestamp.strftime('%d.%m.%Y %H:%M'),
                'session_id': flagged_item.session_id,
                'message_index': flagged_item.message_index,
                'user_id': flagged_item.user_id,  # Changed from user_name to user_id
                'team_name': team.name if team else None,
                'team_id': team.id if team else None
            }
            
            public_flags_data.append(flag_data)
            
        except Exception as e:
            app.logger.error(f"Error processing flagged item {flagged_item.id}: {str(e)}")
            continue

    return render_template(
        "roleplay/public_ulovky.html",
        public_flags=public_flags_data,
        pagination=pagination
    )

@roleplay.route("/ulovky/<conversation_id>", methods=["GET"])
def public_conversation_detail(conversation_id):
    """
    Display the full conversation history for a specific chat session with highlighted flagged messages.
    This page is accessible without login.
    
    Path Parameters:
        conversation_id: The session ID of the conversation to view
    
    Returns:
        The rendered conversation detail template
    """
    try:
        # Get the chat session
        chat_session = ChatSession.query.get(conversation_id)
        if not chat_session:
            flash("Konverzace nebyla nalezena.", "error")
            return redirect(url_for("roleplay.public_ulovky"))
        
        # Get all public flagged messages for this session
        flagged_messages = FlaggedResponse.query.filter_by(
            session_id=conversation_id,
            is_public=True
        ).all()
        
        # If no public flagged messages exist for this session, redirect
        if not flagged_messages:
            flash("Tato konverzace neobsahuje žádné veřejné úlovky.", "warning")
            return redirect(url_for("roleplay.public_ulovky"))
        
        # Get the chat history using chat_utils function
        chat_history_raw = get_chat_history(conversation_id)
        if not chat_history_raw:
            flash("Nepodařilo se načíst historii konverzace.", "error")
            return redirect(url_for("roleplay.public_ulovky"))
        
        # Debug: Print raw chat history
        print(f"DEBUG: Raw chat history length: {len(chat_history_raw)}")
        for i, msg in enumerate(chat_history_raw):
            role = msg.get('role', 'unknown') if isinstance(msg, dict) else getattr(msg, 'role', 'unknown')
            content_preview = (msg.get('content', '') if isinstance(msg, dict) else getattr(msg, 'content', ''))[:50]
            print(f"DEBUG: Raw message {i}: role={role}, content={content_preview}...")
        
        # Filter out system messages for public export
        chat_history = [msg for msg in chat_history_raw if (msg.get('role') if isinstance(msg, dict) else getattr(msg, 'role', '')) != 'system']
        
        # Debug: Print filtered chat history
        print(f"DEBUG: Filtered chat history length: {len(chat_history)}")
        for i, msg in enumerate(chat_history):
            role = msg.get('role', 'unknown') if isinstance(msg, dict) else getattr(msg, 'role', 'unknown')
            content_preview = (msg.get('content', '') if isinstance(msg, dict) else getattr(msg, 'content', ''))[:50]
            print(f"DEBUG: Filtered message {i}: role={role}, content={content_preview}...")
        
        # Debug: Print flagged messages info
        print(f"DEBUG: Number of flagged messages: {len(flagged_messages)}")
        for i, flag in enumerate(flagged_messages):
            print(f"DEBUG: Flag {i}: message_index={flag.message_index}, content={flag.content[:50] if flag.content else 'None'}...")
        
        # Create a map of flagged message indices using multiple strategies
        flagged_indices = {}
          # Strategy 1: Direct index mapping (if message_index is valid for filtered history)
        for flagged_msg in flagged_messages:
            if flagged_msg.message_index is not None:
                if 0 <= flagged_msg.message_index < len(chat_history):
                    # Clean up the summary if it contains AI analysis errors
                    flagged_indices[flagged_msg.message_index] = {
                        'id': flagged_msg.id,
                        'summary': flagged_msg.summary or "Bez shrnutí",
                        'timestamp': flagged_msg.timestamp.strftime('%d.%m.%Y %H:%M'),
                        'content': flagged_msg.content,
                        'method': 'direct_index'
                    }
                    print(f"DEBUG: Added flag at direct index {flagged_msg.message_index}")
        
        # Strategy 2: Content matching if direct indexing didn't work
        if not flagged_indices:
            print("DEBUG: Direct indexing failed, trying content matching...")
            for flagged_msg in flagged_messages:
                if flagged_msg.content:
                    flagged_content = flagged_msg.content.strip()
                    for i, chat_msg in enumerate(chat_history):
                        chat_content = (chat_msg.get('content', '') if isinstance(chat_msg, dict) else getattr(chat_msg, 'content', '')).strip()
                        if chat_content == flagged_content:
                            flagged_indices[i] = {
                                'id': flagged_msg.id,
                                'summary': flagged_msg.summary or "Bez shrnutí",
                                'timestamp': flagged_msg.timestamp.strftime('%d.%m.%Y %H:%M'),
                                'content': flagged_msg.content,
                                'method': 'content_match'
                            }
                            print(f"DEBUG: Added flag at content-matched index {i}")
                            break
        
        # Strategy 3: If still no matches, try to match with original (unfiltered) indices
        if not flagged_indices:
            print("DEBUG: Content matching failed, trying original index mapping...")
            for flagged_msg in flagged_messages:
                if flagged_msg.message_index is not None:
                    # Try to find the message in the raw history and map to filtered index
                    if 0 <= flagged_msg.message_index < len(chat_history_raw):
                        raw_msg = chat_history_raw[flagged_msg.message_index]
                        raw_content = (raw_msg.get('content', '') if isinstance(raw_msg, dict) else getattr(raw_msg, 'content', '')).strip()
                        
                        for filtered_i, filtered_msg in enumerate(chat_history):
                            filtered_content = (filtered_msg.get('content', '') if isinstance(filtered_msg, dict) else getattr(filtered_msg, 'content', '')).strip()
                            if filtered_content == raw_content:
                                flagged_indices[filtered_i] = {
                                    'id': flagged_msg.id,
                                    'summary': flagged_msg.summary or "Bez shrnutí",
                                    'timestamp': flagged_msg.timestamp.strftime('%d.%m.%Y %H:%M'),
                                    'content': flagged_msg.content,
                                    'method': 'raw_to_filtered_mapping'
                                }
                                print(f"DEBUG: Added flag at raw-to-filtered mapped index {filtered_i}")
                                break

        print(f"DEBUG: Final flagged_indices: {list(flagged_indices.keys())}")
        for idx, info in flagged_indices.items():
            print(f"DEBUG: Index {idx}: method={info['method']}, summary={info['summary'][:30]}...")
        
        # Get session creator info
        user = User.query.get(chat_session.user_id)
        
        # Get team info if available
        team_info = None
        if flagged_messages[0].team_id:
            team = Team.query.get(flagged_messages[0].team_id)
            if team:
                team_info = {
                    'id': team.id,
                    'name': team.name
                }
        
        conversation_data = {
            'session_id': conversation_id,
            'user_id': chat_session.user_id,  # Changed from user_name to user_id
            'created_at': chat_session.created_at.strftime('%d.%m.%Y %H:%M'),
            'team_info': team_info,
            'flagged_count': len(flagged_messages)
        }
        
        return render_template(
            "roleplay/public_conversation_detail.html",
            conversation=conversation_data,
            chat_history=chat_history,
            flagged_indices=flagged_indices,
            flagged_messages=flagged_messages
        )
        
    except Exception as e:
        app.logger.error(f"Error viewing conversation {conversation_id}: {str(e)}")
        traceback.print_exc()
        flash("Došlo k chybě při načítání konverzace.", "error")
        return redirect(url_for("roleplay.public_ulovky"))


@roleplay.route("/download", methods=["GET"])
@login_required
def download_ulovky():
    """
    Download a CSV file containing all public flagged messages with user ID, timestamp, and conversation URL.
    Only accessible to logged-in users.
    
    Returns:
        CSV file download response
    """
    try:
        import csv
        from io import StringIO
        from flask import make_response
        
        # Query all public flagged messages
        public_flags = FlaggedResponse.query.filter_by(is_public=True).order_by(FlaggedResponse.timestamp.desc()).all()
        
        # Create CSV content
        output = StringIO()
        writer = csv.writer(output)
        
        # Write CSV header
        writer.writerow(['User ID', 'Timestamp', 'Conversation URL', 'Flag ID', 'Team Name', 'Summary'])
        
        # Write data rows
        for flag in public_flags:
            try:
                # Get team name if available
                team_name = ""
                if flag.team_id:
                    team = Team.query.get(flag.team_id)
                    if team:
                        team_name = team.name
                
                # Format timestamp
                timestamp_formatted = flag.timestamp.strftime('%Y-%m-%d %H:%M:%S')
                
                # Generate conversation URL
                conversation_url = url_for('roleplay.public_conversation_detail', 
                                         conversation_id=flag.session_id, 
                                         _external=True) + f"#flag-{flag.id}"
                
                # Clean summary
                clean_summary = flag.summary or "Bez shrnutí"
                if ('AI analýza: Chyba při analýze:' in clean_summary or 
                    'AI analýza: Úspěšně nachytaný AI asistent' in clean_summary or
                    'severity' in clean_summary or 
                    'Analýza AI selhala' in clean_summary or
                    'Chyba při analýze:' in clean_summary):
                    clean_summary = 'Úspěšně nachytaný AI asistent'
                
                # Write row
                writer.writerow([
                    flag.user_id,
                    timestamp_formatted,
                    conversation_url,
                    flag.id,
                    team_name,
                    clean_summary
                ])
                
            except Exception as e:
                app.logger.error(f"Error processing flag {flag.id} for CSV: {str(e)}")
                continue
        
        # Create response
        output.seek(0)
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv'
        response.headers['Content-Disposition'] = f'attachment; filename="ulovky_ai_soutez_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv"'
        
        return response
        
    except Exception as e:
        app.logger.error(f"Error generating CSV download: {str(e)}")
        traceback.print_exc()
        flash("Došlo k chybě při generování CSV souboru.", "error")
        return redirect(url_for("roleplay.public_ulovky"))

@roleplay.route("/download_json", methods=["GET"])
@login_required
def download_ulovky_json():
    """
    Download a comprehensive JSON file containing all public flagged conversations with full context for AI evaluation.
    Only accessible to logged-in users.
    
    JSON Schema:
    {
        "metadata": {
            "export_timestamp": "ISO 8601 timestamp",
            "export_version": "1.0",
            "total_conversations": "number of conversations",
            "total_flags": "number of flags",
            "competition_name": "#NachytejAI",
            "description": "Complete dataset of AI assistant catches for evaluation"
        },
        "conversations": [
            {
                "conversation_id": "session UUID",
                "created_at": "ISO 8601 timestamp", 
                "user_id": "integer - user who created conversation",
                "flags": [
                    {
                        "flag_id": "UUID",
                        "flagged_by_user_id": "integer",
                        "flag_timestamp": "ISO 8601 timestamp",
                        "summary": "string - clean summary",
                        "original_summary": "string - original with AI analysis",
                        "team_id": "integer or null",
                        "team_name": "string or null",
                        "flagged_message_index": "integer - index in filtered chat",
                        "flagged_content": "string - the actual flagged message"
                    }
                ],
                "chat_history": [
                    {
                        "message_index": "integer - position in conversation",
                        "role": "user|assistant", 
                        "content": "string - message content",
                        "is_flagged": "boolean - whether this message was flagged"
                    }
                ],
                "conversation_stats": {
                    "total_messages": "integer",
                    "user_messages": "integer", 
                    "assistant_messages": "integer",
                    "flagged_messages": "integer"
                }
            }
        ]
    }
    
    Returns:
        JSON file download response with complete conversation data
    """
    try:
        from flask import make_response
        import json
        
        # Get all public flagged messages grouped by session
        public_flags = FlaggedResponse.query.filter_by(is_public=True).order_by(FlaggedResponse.timestamp.desc()).all()
        
        # Group flags by session_id
        sessions_with_flags = {}
        for flag in public_flags:
            session_id = flag.session_id
            if session_id not in sessions_with_flags:
                sessions_with_flags[session_id] = []
            sessions_with_flags[session_id].append(flag)
        
        conversations_data = []
        total_flags = 0
        
        for session_id, session_flags in sessions_with_flags.items():
            try:
                # Get chat session info
                chat_session = ChatSession.query.get(session_id)
                if not chat_session:
                    app.logger.warning(f"Chat session {session_id} not found, skipping")
                    continue
                
                # Get full chat history
                chat_history_raw = get_chat_history(session_id)
                if not chat_history_raw:
                    app.logger.warning(f"No chat history for session {session_id}, skipping")
                    continue
                
                # Filter out system messages for public export
                chat_history = [msg for msg in chat_history_raw if (msg.get('role') if isinstance(msg, dict) else getattr(msg, 'role', '')) != 'system']
                
                # Create flagged indices map for this conversation
                flagged_indices = {}
                for flagged_msg in session_flags:
                    # Try multiple strategies to find the correct message index
                    found_index = None
                    
                    # Strategy 1: Direct index if valid
                    if flagged_msg.message_index is not None and 0 <= flagged_msg.message_index < len(chat_history):
                        found_index = flagged_msg.message_index
                    
                    # Strategy 2: Content matching
                    if found_index is None and flagged_msg.content:
                        flagged_content = flagged_msg.content.strip()
                        for i, chat_msg in enumerate(chat_history):
                            chat_content = (chat_msg.get('content', '') if isinstance(chat_msg, dict) else getattr(chat_msg, 'content', '')).strip()
                            if chat_content == flagged_content:
                                found_index = i
                                break
                    
                    # Strategy 3: Raw to filtered mapping
                    if found_index is None and flagged_msg.message_index is not None:
                        if 0 <= flagged_msg.message_index < len(chat_history_raw):
                            raw_msg = chat_history_raw[flagged_msg.message_index]
                            raw_content = (raw_msg.get('content', '') if isinstance(raw_msg, dict) else getattr(raw_msg, 'content', '')).strip()
                            
                            for filtered_i, filtered_msg in enumerate(chat_history):
                                filtered_content = (filtered_msg.get('content', '') if isinstance(filtered_msg, dict) else getattr(filtered_msg, 'content', '')).strip()
                                if filtered_content == raw_content:
                                    found_index = filtered_i
                                    break
                    
                    if found_index is not None:
                        flagged_indices[found_index] = flagged_msg
                
                # Prepare flags data
                flags_data = []
                for flag in session_flags:
                    # Find the message index for this flag
                    message_index = None
                    for idx, flag_obj in flagged_indices.items():
                        if flag_obj.id == flag.id:
                            message_index = idx
                            break
                    
                    # Get team info if available
                    team_name = None
                    if flag.team_id:
                        team = Team.query.get(flag.team_id)
                        if team:
                            team_name = team.name or ""
                    
                    # Clean summary with proper UTF-8 handling
                    clean_summary = flag.summary or "Bez shrnutí"
                    original_summary = flag.summary or ""
                    if ('AI analýza: Chyba při analýze:' in clean_summary or 
                        'AI analýza: Úspěšně nachytaný AI asistent' in clean_summary or
                        'severity' in clean_summary or 
                        'Analýza AI selhala' in clean_summary or
                        'Chyba při analýze:' in clean_summary):
                        clean_summary = 'Úspěšně nachytaný AI asistent'
                    
                    # Ensure all string fields are properly encoded
                    flag_data = {
                        "flag_id": str(flag.id),
                        "flagged_by_user_id": flag.user_id,
                        "flag_timestamp": flag.timestamp.isoformat(),
                        "summary": str(clean_summary),
                        "original_summary": str(original_summary),
                        "team_id": flag.team_id,
                        "team_name": str(team_name) if team_name else None,
                        "flagged_message_index": message_index,
                        "flagged_content": str(flag.content) if flag.content else ""
                    }
                    flags_data.append(flag_data)
                    total_flags += 1
                
                # Prepare chat history with flagged indicators
                chat_messages = []
                user_messages = 0
                assistant_messages = 0
                
                for i, msg in enumerate(chat_history):
                    role = msg.get('role') if isinstance(msg, dict) else getattr(msg, 'role', 'unknown')
                    content = msg.get('content') if isinstance(msg, dict) else getattr(msg, 'content', '')
                    is_flagged = i in flagged_indices
                    
                    if role == 'user':
                        user_messages += 1
                    elif role == 'assistant':
                        assistant_messages += 1
                    
                    # Ensure content is properly handled as UTF-8 string
                    message_data = {
                        "message_index": i,
                        "role": str(role),
                        "content": str(content),
                        "is_flagged": is_flagged
                    }
                    chat_messages.append(message_data)
                
                # Prepare conversation data
                conversation_data = {
                    "conversation_id": str(session_id),
                    "created_at": chat_session.created_at.isoformat(),
                    "user_id": chat_session.user_id,
                    "flags": flags_data,
                    "chat_history": chat_messages,
                    "conversation_stats": {
                        "total_messages": len(chat_messages),
                        "user_messages": user_messages,
                        "assistant_messages": assistant_messages,
                        "flagged_messages": len(flags_data)
                    }
                }
                conversations_data.append(conversation_data)
                
            except Exception as e:
                app.logger.error(f"Error processing conversation {session_id}: {str(e)}")
                continue
        
        # Create the complete JSON structure
        export_data = {
            "metadata": {
                "export_timestamp": datetime.utcnow().isoformat(),
                "export_version": "1.0",
                "total_conversations": len(conversations_data),
                "total_flags": total_flags,
                "competition_name": "#NachytejAI",
                "description": "Complete dataset of AI assistant catches for evaluation"
            },
            "conversations": conversations_data
        }
        
        # Create JSON response with explicit UTF-8 encoding
        json_content = json.dumps(export_data, ensure_ascii=False, indent=2, separators=(',', ': '))
        
        # Ensure the content is properly encoded as UTF-8 bytes
        json_bytes = json_content.encode('utf-8')
        
        response = make_response(json_bytes)
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        response.headers['Content-Disposition'] = f'attachment; filename="ulovky_ai_complete_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.json"'
        response.headers['Content-Length'] = str(len(json_bytes))
        
        return response
        
    except Exception as e:
        app.logger.error(f"Error generating JSON download: {str(e)}")
        traceback.print_exc()
        flash("Došlo k chybě při generování JSON souboru.", "error")
        return redirect(url_for("roleplay.public_ulovky"))
