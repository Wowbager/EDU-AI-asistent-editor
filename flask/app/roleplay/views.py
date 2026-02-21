import json
import traceback
import uuid
import os
from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash
from flask_login import current_user, login_required
from app import app, db
from app.models import ChatSession, FlaggedResponse, Team, User, ChatMessage, TeamInvitation
from datetime import datetime, timedelta
import openai

# Import utility functions and config from within roleplay module
from .chat_utils import (
    get_chat_history,
    save_chat_history,
    get_role_by_id,
    generate_roles_from_subject,
    generate_role_instructions_preview,
    generate_session_id_for_roleplay_chat
)
from .ai_prompts import (
    prepare_session_prompt,
)
from .config import (
    COMPETITION_RUNNING,
    MAX_AI_RESPONSES,
    MAX_MESSAGE_LENGTH,
    MAX_CUSTOM_INSTRUCTIONS_LENGTH,
    CHAT_MODEL,
    ROLE_GENERATION_MODEL,
    ROLE_GENERATION_TIMEOUT
)

roleplay = Blueprint("roleplay", __name__)

@roleplay.route("/", methods=["GET"])
@login_required
def roleplay_home():
    """
    Render the roleplay chat interface
    
    Returns:
        The rendered roleplay template
    """
    if not COMPETITION_RUNNING:
        flash("Soutěž již skončila. Chat není k dispozici.", "info")
        return redirect(url_for("public.index"))
    
    user_teams = current_user.teams  # Get user's teams
    return render_template("roleplay/index.html", user_teams=user_teams)

@roleplay.route("/roles", methods=["GET"])
@login_required
def get_roles():
    """
    Generate roleplay personas for a given subject.
    
    Query Parameters:
        subject: The subject for which to generate roleplay personas
    
    Returns:
        JSON with role names (phase 1) or an error message
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
                    "title": "Testovací role 1"
                },
                {
                    "id": str(uuid.uuid4()),
                    "title": "Testovací role 2"
                }
            ]
        }), 200
    
    try:
        # Generate roles using AI with strict structured outputs
        content = generate_roles_from_subject(
            subject=subject,
            model=ROLE_GENERATION_MODEL,
            request_timeout=ROLE_GENERATION_TIMEOUT
        )
        
        print(f"Raw AI response for subject '{subject}': {repr(content)}")
        
        # Parse JSON response - guaranteed valid with strict schema
        try:
            response_data = json.loads(content)
            roles_data = response_data.get('roles', [])
            
            if not roles_data:
                print(f"No roles in response for subject: {subject}")
                return jsonify({"error": "AI nevrátila žádné role."}), 500
                
            print(f"Successfully parsed {len(roles_data)} roles for subject: {subject}")
            
        except json.JSONDecodeError as e:
            print(f"JSON parse failed for subject '{subject}': {str(e)}")
            return jsonify({"error": "Odpověď od AI nebyla validní JSON."}), 500
        
        # Validate role structure (phase 1: names only)
        validated_roles = []
        for role in roles_data:
            if isinstance(role, dict) and 'id' in role and 'title' in role:
                validated_roles.append({
                    "id": str(role['id']),
                    "title": str(role['title'])
                })
            else:
                print(f"Malformed role object: {role}")
        
        if not validated_roles:
            print(f"No valid roles after validation for subject: {subject}")
            return jsonify({"error": "AI nevrátila žádné validní role."}), 500
        
        return jsonify({"roles": validated_roles}), 200
            
    except openai.error.OpenAIError as e:
        print(f"OpenAI API error during get_roles: {str(e)}")
        return jsonify({"error": f"Chyba API OpenAI: {str(e)}"}), 503
    except Exception as e:
        print(f"Unexpected error during get_roles for subject '{subject}': {str(e)}")
        traceback.print_exc()
        return jsonify({"error": f"Chyba při generování rolí: {str(e)}"}), 500


@roleplay.route("/role_instructions", methods=["POST"])
@login_required
def generate_role_instructions():
    """Generate editable sidebar instructions for a selected generated role."""
    if not COMPETITION_RUNNING:
        return jsonify({"error": "Soutěž již skončila. Generování instrukcí není k dispozici."}), 403

    data = request.get_json() or {}
    role_title = str(data.get("role_title", "")).strip()
    subject = str(data.get("subject", "")).strip()

    if not role_title:
        return jsonify({"error": "Chybí povinné pole: role_title"}), 400

    try:
        instructions = generate_role_instructions_preview(
            subject=subject,
            role_title=role_title,
            model=ROLE_GENERATION_MODEL,
            request_timeout=ROLE_GENERATION_TIMEOUT,
        )
    except openai.error.OpenAIError as e:
        app.logger.error(f"OpenAI API error during instruction generation: {str(e)}")
        return jsonify({"error": "Nepodařilo se vygenerovat instrukce. Zkuste to prosím znovu."}), 503
    except Exception as e:
        app.logger.error(f"Error during instruction generation: {str(e)}")
        return jsonify({"error": "Nepodařilo se připravit instrukce role."}), 500

    if len(instructions) > MAX_CUSTOM_INSTRUCTIONS_LENGTH:
        instructions = instructions[:MAX_CUSTOM_INSTRUCTIONS_LENGTH].rstrip()

    return jsonify({"instructions": instructions}), 200

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

@roleplay.route("/conversations", methods=["GET"])
def conversations():
    """
    Display all user's chat conversations with the ability to view details and flag/unflag messages.
    
    Query Parameters:
        page: The page number (default: 1)
        per_page: Number of items per page (default: 20)
        show_flagged_only: If 'true', show only conversations with flagged messages (default: 'false')
        show_public_flags: If 'true', show all publicly flagged conversations (default: 'false')
    
    Returns:
        The rendered conversations template
    """
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    show_flagged_only = request.args.get('show_flagged_only', 'false').lower() == 'true'
    show_public_flags = request.args.get('show_public_flags', 'false').lower() == 'true'
    
    # If not showing public flags, require login
    if not show_public_flags and not current_user.is_authenticated:
        return redirect(url_for('public.login'))
    
    # If showing public flags, get all public flagged conversations (not just current user's)
    if show_public_flags:
        # Get all public flagged messages with their session IDs
        public_flags = FlaggedResponse.query.filter_by(is_public=True).order_by(FlaggedResponse.timestamp.desc()).all()
        
        # Group by session_id
        sessions_dict = {}
        for flag in public_flags:
            if flag.session_id not in sessions_dict:
                sessions_dict[flag.session_id] = {
                    'session_id': flag.session_id,
                    'flags': [],
                    'team_id': flag.team_id
                }
            sessions_dict[flag.session_id]['flags'].append(flag)
        
        # Build sessions data for public flags
        sessions_data = []
        for session_id, data in sessions_dict.items():
            # Get chat history
            chat_history = get_chat_history(session_id)
            
            # If no Redis history, get from database
            if not chat_history:
                db_messages = ChatMessage.query.filter_by(session_id=session_id).order_by(ChatMessage.timestamp).all()
                chat_history = [{'role': msg.role, 'content': msg.content, 'timestamp': msg.timestamp.isoformat() if msg.timestamp else None} for msg in db_messages]
            
            # Get team info
            team = Team.query.get(data['team_id']) if data['team_id'] else None
            
            # Extract role info
            role_title = "Konverzace"
            role_brief = ""
            if chat_history and len(chat_history) > 1:
                first_msg = chat_history[0] if len(chat_history) > 1 else {"role": "", "content": ""}
                if first_msg.get('role') == 'system':
                    content = first_msg.get('content', '')
                    if 'v roli' in content:
                        import re
                        match = re.search(r"v roli '([^']+)'", content)
                        if match:
                            role_title = match.group(1)
                        match = re.search(r"'([^']+)' \(([^)]+)\)", content)
                        if match:
                            role_title = match.group(1)
                            role_brief = match.group(2)
            
            # Create flagged content list with summaries
            flagged_messages_list = []
            for f in data['flags']:
                flagged_messages_list.append({
                    'id': f.id,
                    'content': f.content,
                    'summary': f.summary,
                    'timestamp': f.timestamp.isoformat() if f.timestamp else None
                })
            
            sessions_data.append({
                'session': {
                    'id': session_id,
                    'role_title': role_title,
                    'role_brief': role_brief,
                    'created_at': data['flags'][0].timestamp.isoformat() if data['flags'] else None
                },
                'message_count': len(chat_history),
                'chat_history': chat_history,
                'flagged_messages': flagged_messages_list,
                'flagged_content_set': [f.content for f in data['flags']],
                'team': {'name': team.name} if team else None,
                'is_public': True
            })
        
        return render_template(
            "roleplay/conversations.html",
            sessions_data=sessions_data,
            pagination=None,
            show_flagged_only=False,
            show_public_flags=True,
            user_teams=current_user.teams if current_user.is_authenticated else []
        )
    
    # Get all chat sessions for the current user, ordered by most recent
    sessions_query = ChatSession.query.filter_by(user_id=current_user.id).order_by(ChatSession.created_at.desc())
    
    # If show_flagged_only is true, filter to only sessions with flagged messages
    if show_flagged_only:
        # Get session IDs that have flagged messages for this user
        flagged_session_ids = db.session.query(FlaggedResponse.session_id).filter_by(
            user_id=current_user.id
        ).distinct().all()
        flagged_session_ids = [sid[0] for sid in flagged_session_ids]
        
        if flagged_session_ids:
            sessions_query = sessions_query.filter(ChatSession.id.in_(flagged_session_ids))
        else:
            # No flagged sessions, return empty result
            sessions_query = ChatSession.query.filter_by(id='non_existent_id')
    
    # Paginate the results
    pagination = sessions_query.paginate(page=page, per_page=per_page, error_out=False)
    sessions = pagination.items
    
    # For each session, get the message count and chat history
    sessions_data = []
    for session in sessions:
        # Try to get chat history from Redis first, then from database
        chat_history = get_chat_history(session.id)
        
        # If no Redis history, get from database
        if not chat_history:
            db_messages = ChatMessage.query.filter_by(session_id=session.id).order_by(ChatMessage.timestamp).all()
            chat_history = [{'role': msg.role, 'content': msg.content, 'timestamp': msg.timestamp.isoformat() if msg.timestamp else None} for msg in db_messages]
        
        # Get flagged messages for this session
        flagged_messages = FlaggedResponse.query.filter_by(
            session_id=session.id,
            user_id=current_user.id
        ).all()
        
        # Create a list of flagged content for quick lookup (convert set to list for JSON serialization)
        flagged_content_list = [f.content for f in flagged_messages]
        
        # Extract role title and brief from chat history or use defaults
        role_title = "Konverzace"
        role_brief = ""
        
        if chat_history and len(chat_history) > 1:
            # Check if first message is system message with role info
            first_msg = chat_history[0] if len(chat_history) > 1 else {"role": "", "content": ""}
            if first_msg.get('role') == 'system':
                content = first_msg.get('content', '')
                # Try to extract role title from system message
                if 'v roli' in content:
                    # Extract role title from pattern "v roli 'Title'"
                    import re
                    match = re.search(r"v roli '([^']+)'", content)
                    if match:
                        role_title = match.group(1)
                    # Extract brief if available
                    match = re.search(r"'([^']+)' \(([^)]+)\)", content)
                    if match:
                        role_title = match.group(1)
                        role_brief = match.group(2)
        
        sessions_data.append({
            'session': {
                'id': session.id,
                'role_title': role_title,
                'role_brief': role_brief,
                'created_at': session.created_at.isoformat() if session.created_at else None
            },
            'message_count': len(chat_history),
            'chat_history': chat_history,
            'flagged_messages': [{'id': f.id, 'content': f.content, 'summary': f.summary, 'is_public': f.is_public, 'team_id': f.team_id} for f in flagged_messages],
            'flagged_content_set': flagged_content_list
        })
    
    return render_template(
        "roleplay/conversations.html",
        sessions_data=sessions_data,
        pagination=pagination,
        show_flagged_only=show_flagged_only,
        user_teams=current_user.teams
    )

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
        return redirect(url_for("public.index"))
    
    # Get user's teams
    user_teams_db = current_user.teams
    app.logger.info(f"--- Initial user_teams_db (current_user.teams): {list(user_teams_db)} ---")
    
    # Get all teams
    all_teams_db = Team.query.order_by(Team.name).all()
    app.logger.info(f"--- Initial all_teams_db: {list(all_teams_db)} ---")

    def process_team_description(team_list):
        processed_teams = []
        app.logger.info(f"--- process_team_description called with team_list: {team_list} ---")
        if not team_list:
            app.logger.warning("--- process_team_description received an empty or None team_list ---")
            return []
            
        for team_obj in team_list:
            # Initialize attributes
            team_obj.creator_id = None
            team_obj.display_description = "Tento tým nemá popis."

            if team_obj.description:
                try:
                    description_data = json.loads(team_obj.description)
                    if isinstance(description_data, dict):
                        team_obj.display_description = description_data.get("original_description", team_obj.description)
                        
                        parsed_creator_id = description_data.get("creator_id")
                        if parsed_creator_id is not None:
                            try:
                                team_obj.creator_id = int(parsed_creator_id)
                            except (ValueError, TypeError):
                                app.logger.warning(f"Team '{team_obj.name}': creator_id '{parsed_creator_id}' is not a valid integer. Kept as None.")
                                pass 
                    else:
                        team_obj.display_description = team_obj.description
                except (json.JSONDecodeError, TypeError):
                    app.logger.warning(f"Team '{team_obj.name}': Failed to parse description JSON. Raw description: {team_obj.description}")
                    team_obj.display_description = team_obj.description if team_obj.description else "Chyba při čtení popisu."
            
            processed_teams.append(team_obj)
        app.logger.info(f"--- process_team_description finished, processed_teams: {processed_teams} ---")
        return processed_teams
    
    def serialize_team(team_obj):
        """Serialize team object for JSON"""
        # Check if current user is a member of this team
        is_member = current_user in team_obj.members.all()
        is_creator = team_obj.creator_id == current_user.id
        
        members_list = []
        for member in team_obj.members.all():
            member_data = {
                'id': member.id
            }
            
            # Only show email/name if current user is a member of the team
            if is_member:
                member_data['email'] = member.email
                member_data['name'] = member.name if hasattr(member, 'name') and member.name else member.email
            else:
                # Show anonymized data for non-members
                member_data['email'] = None
                member_data['name'] = f'Člen {member.id}'
            
            members_list.append(member_data)
        
        # Get pending invitations count (only for creator)
        pending_invites_count = 0
        pending_invites = []
        if is_creator:
            pending_invitations = TeamInvitation.query.filter_by(
                team_id=team_obj.id,
                status='pending'
            ).all()
            pending_invites_count = len(pending_invitations)
            pending_invites = [
                {
                    'id': inv.id,
                    'invitee_email': inv.invitee_email,
                    'created_at': inv.created_at.isoformat() if inv.created_at else None
                }
                for inv in pending_invitations
            ]
        
        # Get flagged responses count (only for team members)
        flagged_responses_count = 0
        if is_member:
            flagged_responses_count = FlaggedResponse.query.filter_by(team_id=team_obj.id).count()
        
        return {
            'id': team_obj.id,
            'name': team_obj.name,
            'description': team_obj.description,
            'display_description': team_obj.display_description if hasattr(team_obj, 'display_description') else 'Tento tým nemá popis.',
            'created_at': team_obj.created_at.isoformat() if team_obj.created_at else None,
            'creator_id': team_obj.creator_id,
            'members': members_list,
            'member_count': len(members_list),
            'is_member': is_member,
            'is_creator': is_creator,
            'pending_invites_count': pending_invites_count,
            'pending_invites': pending_invites,
            'flagged_responses_count': flagged_responses_count
        }

    # Process teams
    user_teams_processed = process_team_description(list(user_teams_db)) 
    all_teams_processed = process_team_description(list(all_teams_db))

    # Debug logging
    app.logger.info("--- Debugging user_teams_processed in /teams route ---")
    if not user_teams_processed:
        app.logger.warning("--- user_teams_processed is empty or None. ---")
    for team_item in user_teams_processed:
        app.logger.info(f"Team Name: {team_item.name}, Team ID: {team_item.id}, Creator ID: {team_item.creator_id}")
        app.logger.info(f"Current User ID: {current_user.id}")
    app.logger.info("--- End Debugging /teams route ---")
    
    # Serialize teams for JavaScript
    user_teams_json = [serialize_team(team) for team in user_teams_processed]
    all_teams_json = [serialize_team(team) for team in all_teams_processed]
    
    # Get pending invitations for current user
    pending_invitations_count = TeamInvitation.query.filter_by(
        invitee_email=current_user.email,
        status='pending'
    ).count()
    
    return render_template(
        "roleplay/teams.html",
        user_teams=user_teams_processed,
        all_teams=all_teams_processed,
        user_teams_json=user_teams_json,
        all_teams_json=all_teams_json,
        pending_invitations_count=pending_invitations_count
    )

@roleplay.route("/admin-dashboard", methods=["GET"])
@login_required
def admin_dashboard():
    """
    Admin page to view all chats, teams, and flagged messages.
    Only accessible to super admin users.
    """
    if not current_user.is_super_admin:
        flash("Přístup odepřen: Nemáte oprávnění k zobrazení této stránky.", "danger")
        return redirect(url_for("roleplay.roleplay_home"))

    # Fetching data for summary cards
    total_users = User.query.count()
    time_24_hours_ago = datetime.utcnow() - timedelta(days=1)
    chats_last_24h = ChatSession.query.filter(ChatSession.created_at >= time_24_hours_ago).count()
    flags_last_24h = FlaggedResponse.query.filter(FlaggedResponse.timestamp >= time_24_hours_ago).count()

    # Pagination parameters
    page_chats = request.args.get('page_chats', 1, type=int)
    page_teams = request.args.get('page_teams', 1, type=int)
    page_flags = request.args.get('page_flags', 1, type=int)
    PER_PAGE = 12

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

@roleplay.route("/flag", methods=["POST"])
@login_required
def flag_response():
    """
    Flag an inappropriate assistant response from a chat session.
    
    Request JSON:
        {
            "session_id": UUID,
            "flagged_content": string,
            "summary": string (optional),
            "team_id": integer (optional),
            "is_public": boolean (optional)
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
    flagged_content = data.get("flagged_content")
    summary = data.get("summary")
    team_id = data.get("team_id")
    is_public = data.get("is_public", False)
    
    if not session_id:
        return jsonify({"error": "Chybějící session_id."}), 400
    
    if not flagged_content:
        return jsonify({"error": "Chybějící flagged_content."}), 400
    
    try:
        chat_session = ChatSession.query.get(session_id)
        if not chat_session:
            return jsonify({"error": "Relace chatu nebyla nalezena."}), 404

        # Validate team membership if team_id is provided
        if team_id:
            team = Team.query.get(team_id)
            if not team or current_user not in team.members.all():
                return jsonify({"error": "Nemáte oprávnění přiřadit označení k tomuto týmu."}), 403

        # Create new flagged response
        flagged_response_id = str(uuid.uuid4())
        new_flag = FlaggedResponse(
            id=flagged_response_id,
            user_id=current_user.id,
            session_id=session_id,
            content=flagged_content,
            summary=summary or "Úspěšně nachytaný AI asistent",
            team_id=team_id,
            is_public=is_public,
            timestamp=datetime.utcnow()
        )
        
        db.session.add(new_flag)
        db.session.commit()
        
        return jsonify({
            "success": True, 
            "flagged_response_id": flagged_response_id,
            "message": "Odpověď byla úspěšně označena."
        }), 201
        
    except Exception as e:
        db.session.rollback()
        print(f"Error flagging response: {str(e)}")
        traceback.print_exc()
        return jsonify({"error": f"Chyba při označování odpovědi: {str(e)}"}), 500

@roleplay.route("/unflag_message", methods=["POST"])
@login_required
def unflag_message():
    """
    Remove a flagged message from the user's flagged collection.
    
    JSON Body:
        session_id: The session ID
        content: The content of the message to unflag
    
    Returns:
        JSON response with success status
    """
    data = request.get_json()
    session_id = data.get('session_id')
    content = data.get('content')
    
    if not session_id or not content:
        return jsonify({'success': False, 'error': 'Missing session_id or content'}), 400
    
    # Find and delete the flagged response
    flagged = FlaggedResponse.query.filter_by(
        session_id=session_id,
        user_id=current_user.id,
        content=content
    ).first()
    
    if not flagged:
        return jsonify({'success': False, 'error': 'Flagged message not found'}), 404
    
    try:
        db.session.delete(flagged)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Message unflagged successfully'})
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error unflagging message: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

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
        
        # Update team_id if provided
        if "team_id" in data:
            team_id = data["team_id"]
            # Validate team membership if team_id is provided
            if team_id:
                team = Team.query.get(team_id)
                if not team or current_user not in team.members.all():
                    return jsonify({"success": False, "error": "Nemáte oprávnění přiřadit označení k tomuto týmu."}), 403
            flagged_response.team_id = team_id
        
        # Update is_public if provided
        if "is_public" in data:
            flagged_response.is_public = bool(data["is_public"])
        
        db.session.commit()
        
        return jsonify({"success": True, "message": "Označení bylo úspěšně aktualizováno."})
        
    except Exception as e:
        db.session.rollback()
        print(f"Error updating flagged summary: {str(e)}")
        traceback.print_exc()
        return jsonify({"success": False, "error": f"Chyba při aktualizaci shrnutí: {str(e)}"}), 500


# ==================== TEAM MANAGEMENT ROUTES ====================

@roleplay.route("/teams/create", methods=["POST"])
@login_required
def create_team():
    """Create a new team."""
    if not COMPETITION_RUNNING:
        return jsonify({"success": False, "error": "Soutěž již skončila."}), 403
    
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "Chybějící data."}), 400
    
    name = data.get("name", "").strip()
    description = data.get("description", "").strip()
    
    if not name:
        return jsonify({"success": False, "error": "Název týmu je povinný."}), 400
    
    if len(name) > 100:
        return jsonify({"success": False, "error": "Název týmu je příliš dlouhý (max 100 znaků)."}), 400
    
    try:
        # Check if team name already exists
        existing_team = Team.query.filter_by(name=name).first()
        if existing_team:
            return jsonify({"success": False, "error": "Tým s tímto názvem již existuje."}), 400
        
        # Create team with creator_id
        new_team = Team(
            name=name,
            description=json.dumps({
                "original_description": description,
                "creator_id": current_user.id
            }),
            creator_id=current_user.id
        )
        db.session.add(new_team)
        db.session.flush()  # Get the team ID
        
        # Add creator as first member
        new_team.members.append(current_user)
        
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": "Tým byl úspěšně vytvořen!",
            "team": {
                "id": new_team.id,
                "name": new_team.name,
                "description": description
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error creating team: {str(e)}")
        traceback.print_exc()
        return jsonify({"success": False, "error": f"Chyba při vytváření týmu: {str(e)}"}), 500


@roleplay.route("/teams/<int:team_id>/edit", methods=["PUT"])
@login_required
def edit_team(team_id):
    """Edit team details. Only team creator can edit."""
    if not COMPETITION_RUNNING:
        return jsonify({"success": False, "error": "Soutěž již skončila."}), 403
    
    team = Team.query.get(team_id)
    if not team:
        return jsonify({"success": False, "error": "Tým nenalezen."}), 404
    
    # Check if user is the creator
    if team.creator_id != current_user.id:
        return jsonify({"success": False, "error": "Pouze tvůrce týmu může upravovat tým."}), 403
    
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "Chybějící data."}), 400
    
    name = data.get("name", "").strip()
    description = data.get("description", "").strip()
    
    if not name:
        return jsonify({"success": False, "error": "Název týmu je povinný."}), 400
    
    try:
        # Check if new name conflicts with existing team
        if name != team.name:
            existing_team = Team.query.filter_by(name=name).first()
            if existing_team:
                return jsonify({"success": False, "error": "Tým s tímto názvem již existuje."}), 400
        
        team.name = name
        team.description = json.dumps({
            "original_description": description,
            "creator_id": current_user.id
        })
        
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": "Tým byl úspěšně aktualizován!"
        })
        
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error editing team: {str(e)}")
        traceback.print_exc()
        return jsonify({"success": False, "error": f"Chyba při úpravě týmu: {str(e)}"}), 500


@roleplay.route("/teams/<int:team_id>/delete", methods=["DELETE"])
@login_required
def delete_team(team_id):
    """Delete a team. Only team creator can delete."""
    if not COMPETITION_RUNNING:
        return jsonify({"success": False, "error": "Soutěž již skončila."}), 403
    
    team = Team.query.get(team_id)
    if not team:
        return jsonify({"success": False, "error": "Tým nenalezen."}), 404
    
    # Check if user is the creator
    if team.creator_id != current_user.id:
        return jsonify({"success": False, "error": "Pouze tvůrce týmu může smazat tým."}), 403
    
    try:
        team_name = team.name
        db.session.delete(team)
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": f"Tým '{team_name}' byl úspěšně smazán!"
        })
        
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error deleting team: {str(e)}")
        traceback.print_exc()
        return jsonify({"success": False, "error": f"Chyba při mazání týmu: {str(e)}"}), 500


@roleplay.route("/teams/<int:team_id>/leave", methods=["POST"])
@login_required
def leave_team(team_id):
    """Leave a team. Members can leave, but creator cannot."""
    if not COMPETITION_RUNNING:
        return jsonify({"success": False, "error": "Soutěž již skončila."}), 403
    
    team = Team.query.get(team_id)
    if not team:
        return jsonify({"success": False, "error": "Tým nenalezen."}), 404
    
    # Check if user is a member
    if current_user not in team.members:
        return jsonify({"success": False, "error": "Nejste členem tohoto týmu."}), 400
    
    # Creator cannot leave their own team
    if team.creator_id == current_user.id:
        return jsonify({"success": False, "error": "Tvůrce týmu nemůže opustit tým. Místo toho tým smažte."}), 403
    
    try:
        team.members.remove(current_user)
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": f"Opustili jste tým '{team.name}'."
        })
        
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error leaving team: {str(e)}")
        traceback.print_exc()
        return jsonify({"success": False, "error": f"Chyba při opouštění týmu: {str(e)}"}), 500


@roleplay.route("/teams/<int:team_id>/remove_member/<int:user_id>", methods=["POST"])
@login_required
def remove_team_member(team_id, user_id):
    """Remove a member from team. Only team creator can remove members."""
    if not COMPETITION_RUNNING:
        return jsonify({"success": False, "error": "Soutěž již skončila."}), 403
    
    team = Team.query.get(team_id)
    if not team:
        return jsonify({"success": False, "error": "Tým nenalezen."}), 404
    
    # Check if user is the creator
    if team.creator_id != current_user.id:
        return jsonify({"success": False, "error": "Pouze tvůrce týmu může odstraňovat členy."}), 403
    
    user_to_remove = User.query.get(user_id)
    if not user_to_remove:
        return jsonify({"success": False, "error": "Uživatel nenalezen."}), 404
    
    # Cannot remove self (creator)
    if user_id == current_user.id:
        return jsonify({"success": False, "error": "Nemůžete odstranit sebe. Místo toho tým smažte."}), 400
    
    # Check if user is actually a member
    if user_to_remove not in team.members:
        return jsonify({"success": False, "error": "Tento uživatel není členem týmu."}), 400
    
    try:
        team.members.remove(user_to_remove)
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": f"Člen byl odstraněn z týmu."
        })
        
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error removing team member: {str(e)}")
        traceback.print_exc()
        return jsonify({"success": False, "error": f"Chyba při odstraňování člena: {str(e)}"}), 500


@roleplay.route("/teams/<int:team_id>/invite", methods=["POST"])
@login_required
def invite_to_team(team_id):
    """Send invitation(s) to join a team. Only team creator can invite."""
    if not COMPETITION_RUNNING:
        return jsonify({"success": False, "error": "Soutěž již skončila."}), 403
    
    team = Team.query.get(team_id)
    if not team:
        return jsonify({"success": False, "error": "Tým nenalezen."}), 404
    
    # Check if user is the creator
    if team.creator_id != current_user.id:
        return jsonify({"success": False, "error": "Pouze tvůrce týmu může posílat pozvánky."}), 403
    
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "Chybějící data."}), 400
    
    emails = data.get("emails", [])
    message = data.get("message", "").strip()
    
    if not emails or not isinstance(emails, list):
        return jsonify({"success": False, "error": "Prosím zadejte alespoň jeden email."}), 400
    
    try:
        invited_count = 0
        errors = []
        
        for email in emails:
            email = email.strip().lower()
            
            if not email:
                continue
            
            # Check if email is valid (basic check)
            if "@" not in email:
                errors.append(f"{email}: Neplatný email")
                continue
            
            # Check if user exists
            user = User.query.filter_by(email=email).first()
            if not user:
                errors.append(f"{email}: Uživatel s tímto emailem neexistuje")
                continue
            
            # Check if already a member
            if user in team.members:
                errors.append(f"{email}: Již je členem týmu")
                continue
            
            # Check if already invited
            existing_invite = TeamInvitation.query.filter_by(
                team_id=team_id,
                invitee_email=email,
                status='pending'
            ).first()
            
            if existing_invite:
                errors.append(f"{email}: Již má nevyřízenou pozvánku")
                continue
            
            # Create invitation
            invitation = TeamInvitation(
                team_id=team_id,
                inviter_id=current_user.id,
                invitee_email=email,
                message=message,
                status='pending'
            )
            db.session.add(invitation)
            invited_count += 1
        
        db.session.commit()
        
        result = {
            "success": True,
            "message": f"Odesláno {invited_count} pozvánek!",
            "invited_count": invited_count
        }
        
        if errors:
            result["errors"] = errors
        
        return jsonify(result)
        
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error inviting to team: {str(e)}")
        traceback.print_exc()
        return jsonify({"success": False, "error": f"Chyba při posílání pozvánek: {str(e)}"}), 500


@roleplay.route("/invitations/pending", methods=["GET"])
@login_required
def get_pending_invitations():
    """Get all pending invitations for the current user."""
    try:
        invitations = TeamInvitation.query.filter_by(
            invitee_email=current_user.email,
            status='pending'
        ).order_by(TeamInvitation.created_at.desc()).all()
        
        result = []
        for inv in invitations:
            result.append({
                "id": inv.id,
                "team_id": inv.team_id,
                "team_name": inv.team.name if inv.team else "Neznámý tým",
                "inviter_email": inv.inviter.email if inv.inviter else "Neznámý",
                "message": inv.message,
                "created_at": inv.created_at.isoformat() if inv.created_at else None
            })
        
        return jsonify({
            "success": True,
            "invitations": result,
            "count": len(result)
        })
        
    except Exception as e:
        app.logger.error(f"Error getting pending invitations: {str(e)}")
        traceback.print_exc()
        return jsonify({"success": False, "error": f"Chyba při načítání pozvánek: {str(e)}"}), 500


@roleplay.route("/invitations/<int:invitation_id>/accept", methods=["POST"])
@login_required
def accept_invitation(invitation_id):
    """Accept a team invitation."""
    if not COMPETITION_RUNNING:
        return jsonify({"success": False, "error": "Soutěž již skončila."}), 403
    
    invitation = TeamInvitation.query.get(invitation_id)
    if not invitation:
        return jsonify({"success": False, "error": "Pozvánka nenalezena."}), 404
    
    # Check if invitation is for current user
    if invitation.invitee_email != current_user.email:
        return jsonify({"success": False, "error": "Tato pozvánka není pro vás."}), 403
    
    # Check if already processed
    if invitation.status != 'pending':
        return jsonify({"success": False, "error": "Tato pozvánka již byla vyřízena."}), 400
    
    try:
        team = invitation.team
        
        # Check if already a member
        if current_user in team.members:
            invitation.status = 'accepted'
            invitation.responded_at = datetime.utcnow()
            db.session.commit()
            return jsonify({"success": False, "error": "Již jste členem tohoto týmu."}), 400
        
        # Add user to team
        team.members.append(current_user)
        invitation.status = 'accepted'
        invitation.responded_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": f"Úspěšně jste se připojili k týmu '{team.name}'!"
        })
        
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error accepting invitation: {str(e)}")
        traceback.print_exc()
        return jsonify({"success": False, "error": f"Chyba při přijímání pozvánky: {str(e)}"}), 500


@roleplay.route("/invitations/<int:invitation_id>/decline", methods=["POST"])
@login_required
def decline_invitation(invitation_id):
    """Decline a team invitation."""
    invitation = TeamInvitation.query.get(invitation_id)
    if not invitation:
        return jsonify({"success": False, "error": "Pozvánka nenalezena."}), 404
    
    # Check if invitation is for current user
    if invitation.invitee_email != current_user.email:
        return jsonify({"success": False, "error": "Tato pozvánka není pro vás."}), 403
    
    # Check if already processed
    if invitation.status != 'pending':
        return jsonify({"success": False, "error": "Tato pozvánka již byla vyřízena."}), 400
    
    try:
        invitation.status = 'declined'
        invitation.responded_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": "Pozvánka byla odmítnuta."
        })
        
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error declining invitation: {str(e)}")
        traceback.print_exc()
        return jsonify({"success": False, "error": f"Chyba při odmítání pozvánky: {str(e)}"}), 500


@roleplay.route("/teams/<int:team_id>/pending_invitations", methods=["GET"])
@login_required
def get_team_pending_invitations(team_id):
    """Get pending invitations for a team. Only team creator can see this."""
    team = Team.query.get(team_id)
    if not team:
        return jsonify({"success": False, "error": "Tým nenalezen."}), 404
    
    # Check if user is the creator
    if team.creator_id != current_user.id:
        return jsonify({"success": False, "error": "Pouze tvůrce týmu může vidět pozvánky."}), 403
    
    try:
        invitations = TeamInvitation.query.filter_by(
            team_id=team_id,
            status='pending'
        ).order_by(TeamInvitation.created_at.desc()).all()
        
        result = []
        for inv in invitations:
            result.append({
                "id": inv.id,
                "invitee_email": inv.invitee_email,
                "message": inv.message,
                "created_at": inv.created_at.isoformat() if inv.created_at else None
            })
        
        return jsonify({
            "success": True,
            "invitations": result,
            "count": len(result)
        })
        
    except Exception as e:
        app.logger.error(f"Error getting team pending invitations: {str(e)}")
        traceback.print_exc()
        return jsonify({"success": False, "error": f"Chyba při načítání pozvánek: {str(e)}"}), 500

@roleplay.route("/generate_session_id", methods=["POST"])
@login_required
def generate_session_id():
    """Generate a unique session ID for WebSocket chat"""
    data = request.get_json()
    
    if not data:
        return jsonify({"error": "Chybějící data"}), 400
        
    role_id = data.get("role_id")
    role_title = data.get("role_title", "")
    role_brief = data.get("role_brief", "")
    subject = data.get("subject", "")
    user_custom_instructions = data.get("custom_instructions", "")

    if not role_id:
        return jsonify({"error": "Chybějící povinné pole: role_id"}), 400

    if not isinstance(user_custom_instructions, str) or not user_custom_instructions.strip():
        return jsonify({"error": "Instrukce pro AI nesmí být prázdné."}), 400

    if len(user_custom_instructions) > MAX_CUSTOM_INSTRUCTIONS_LENGTH:
        return jsonify({"error": f"Vlastní instrukce jsou příliš dlouhé (max {MAX_CUSTOM_INSTRUCTIONS_LENGTH} znaků)."}), 400
    
    try:
        prompt = prepare_session_prompt(
            role_title=role_title,
            custom_instructions=user_custom_instructions
        )
    except Exception as e:
        app.logger.error(f"Error preparing session prompt: {str(e)}")
        return jsonify({"error": "Nepodařilo se připravit roli. Zkuste to prosím znovu."}), 500
    
    # Prepare messages in LangChain native format (array of message dicts)
    # Only include system messages - frontend will send the first user message
    messages = [
        {
            "role": "system",
            "content": prompt
        },
    ]
    
    # Prepare role information for FastAPI
    role_information = {
        "user_id": current_user.id,
        "role": {
            "id": role_id,
            "title": role_title,
            "description": role_brief
        },
        "messages": messages  # LangChain-ready messages
    }
    
    # Generate session ID and store in Redis
    try:
        session_id = generate_session_id_for_roleplay_chat(role_information)
    except Exception as e:
        app.logger.error(f"Error creating roleplay Redis session: {str(e)}")
        return jsonify({"error": "Chyba při přípravě chat relace. Zkuste to prosím znovu."}), 503
    
    # Create ChatSession in database immediately for flagging support
    try:
        chat_session = ChatSession(
            id=session_id,
            user_id=current_user.id,
            role_id=role_id
        )
        db.session.add(chat_session)
        db.session.commit()
        app.logger.info(f"Created chat session {session_id} for user {current_user.id}")
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error creating chat session: {str(e)}")
        return jsonify({"error": "Chyba při vytváření relace chatu"}), 500
    
    return jsonify({"session_id": session_id})