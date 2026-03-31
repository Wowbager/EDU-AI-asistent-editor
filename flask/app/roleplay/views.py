import json
import traceback
import uuid
import os
import re
from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash
from flask_login import current_user, login_required
from app import app, db
from app.models import ChatSession, FlaggedResponse, Team, User, ChatMessage, TeamInvitation, team_membership
from datetime import datetime, timedelta
import openai
from sqlalchemy.orm import joinedload
from sqlalchemy import func

# Import utility functions and config from within roleplay module
from .chat_utils import (
    get_chat_history,
    generate_roles_from_subject,
    generate_role_instructions_preview,
    generate_session_id_for_roleplay_chat,
    delete_roleplay_session_bootstrap,
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
    ROLE_GENERATION_TIMEOUT,
    TEAM_INVITE_MAX_EMAILS_PER_REQUEST,
    TEAM_INVITE_MAX_PER_HOUR_PER_INVITER,
    TEAM_INVITE_MAX_PER_DAY_PER_TEAM,
    TEAM_INVITE_RESEND_COOLDOWN_HOURS,
    TEAM_INVITE_MAX_MESSAGE_LENGTH
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
    reuse_source = None
    reuse_from_session_id = (request.args.get("reuse_from_session_id") or "").strip()

    if reuse_from_session_id:
        source_session = ChatSession.query.get(reuse_from_session_id)
        has_public_flag = FlaggedResponse.query.filter_by(
            session_id=reuse_from_session_id,
            is_public=True,
        ).first() is not None
        can_reuse_source = bool(
            source_session and (
                source_session.user_id == current_user.id or has_public_flag
            )
        )

        if can_reuse_source:
            source_messages = ChatMessage.query.filter_by(
                session_id=source_session.id
            ).order_by(ChatMessage.message_index.asc()).all()

            role_title = (source_session.role_title or "").strip() or "Konverzace"
            role_brief = ""
            first_user_message = ""

            for message in source_messages:
                if not first_user_message and message.role == "user" and message.content:
                    first_user_message = str(message.content).strip()

                if message.role == "system" and message.content:
                    content = str(message.content)
                    if "v roli" in content:
                        match = re.search(r"v roli '([^']+)'", content)
                        if match:
                            role_title = match.group(1)

                        match = re.search(r"'([^']+)' \(([^)]+)\)", content)
                        if match:
                            role_title = match.group(1)
                            role_brief = match.group(2)
                    break

            instructions = (
                first_user_message[:MAX_CUSTOM_INSTRUCTIONS_LENGTH]
                if first_user_message
                else "Pokračování konverzace."
            )

            reuse_source = {
                "session_id": source_session.id,
                "role_id": source_session.role_id,
                "role_title": role_title,
                "role_brief": role_brief,
                "instructions": instructions,
            }
        else:
            flash("Tuto konverzaci nelze použít pro opětovné zahájení.", "warning")

    return render_template(
        "roleplay/index.html",
        user_teams=user_teams,
        reuse_source=reuse_source,
    )

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
                sanitized_title = re.sub(r"\s+", " ", str(role['title'])).strip()
                if not sanitized_title or len(sanitized_title) > 80:
                    print(f"Skipping invalid role title (length/content): {role.get('title')}")
                    continue

                validated_roles.append({
                    "id": str(role['id']),
                    "title": sanitized_title
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
        show_flagged_only: If 'true', show only conversations with flagged messages (default: 'false')
        show_public_flags: If 'true', show all publicly flagged conversations (default: 'false')
    
    Returns:
        The rendered conversations template
    """
    show_flagged_only = request.args.get('show_flagged_only', 'false').lower() == 'true'
    show_public_flags = request.args.get('show_public_flags', 'false').lower() == 'true'
    
    # If not showing public flags, require login
    if not show_public_flags and not current_user.is_authenticated:
        return redirect(url_for('public.login'))
    
    # If showing public flags, get all public flagged conversations (not just current user's)
    if show_public_flags:
        public_flags = FlaggedResponse.query.filter_by(
            is_public=True
        ).order_by(FlaggedResponse.timestamp.desc()).all()

        sessions_dict = {}
        for flag in public_flags:
            if flag.session_id not in sessions_dict:
                sessions_dict[flag.session_id] = {
                    'session_id': flag.session_id,
                    'flags': [],
                    'team_id': flag.team_id,
                }
            sessions_dict[flag.session_id]['flags'].append(flag)

        session_ids = list(sessions_dict.keys())
        sessions_by_id = {
            s.id: s for s in ChatSession.query.filter(ChatSession.id.in_(session_ids)).all()
        } if session_ids else {}

        team_ids = [entry['team_id'] for entry in sessions_dict.values() if entry.get('team_id')]
        teams_by_id = {
            t.id: t for t in Team.query.filter(Team.id.in_(team_ids)).all()
        } if team_ids else {}

        chat_history_by_session = {}
        missing_history_session_ids = []
        for sid in session_ids:
            history = get_chat_history(sid)
            if history is None:
                missing_history_session_ids.append(sid)
            else:
                chat_history_by_session[sid] = history

        if missing_history_session_ids:
            db_messages = ChatMessage.query.filter(
                ChatMessage.session_id.in_(missing_history_session_ids)
            ).order_by(ChatMessage.session_id.asc(), ChatMessage.message_index.asc()).all()

            grouped_db_history = {sid: [] for sid in missing_history_session_ids}
            for msg in db_messages:
                grouped_db_history.setdefault(msg.session_id, []).append({
                    'role': msg.role,
                    'content': msg.content,
                    'timestamp': msg.timestamp.isoformat() if msg.timestamp else None,
                })

            for sid in missing_history_session_ids:
                chat_history_by_session[sid] = grouped_db_history.get(sid, [])

        sessions_data = []
        for session_id, data in sessions_dict.items():
            chat_history = chat_history_by_session.get(session_id, [])
            session = sessions_by_id.get(session_id)
            team = teams_by_id.get(data['team_id']) if data.get('team_id') else None

            role_title = ((session.role_title if session else "") or "").strip() or "Konverzace"
            role_brief = ""

            if role_title == "Konverzace" and chat_history:
                for first_msg in chat_history:
                    if first_msg.get('role') == 'system':
                        content = first_msg.get('content', '')
                        if 'v roli' in content:
                            match = re.search(r"v roli '([^']+)'", content)
                            if match:
                                role_title = match.group(1)
                            match = re.search(r"'([^']+)' \(([^)]+)\)", content)
                            if match:
                                role_title = match.group(1)
                                role_brief = match.group(2)
                    break

            flagged_messages_list = [
                {
                    'id': flagged.id,
                    'content': flagged.content,
                    'summary': flagged.summary,
                    'is_public': flagged.is_public,
                    'team_id': flagged.team_id,
                    'message_index': flagged.message_index,
                    'timestamp': flagged.timestamp.isoformat() if flagged.timestamp else None,
                }
                for flagged in data['flags']
            ]

            problem_description = "Zatím nenachytány žádné podezřelé odpovědi."
            for flagged in flagged_messages_list:
                if flagged['summary']:
                    problem_description = flagged['summary']
                    break

            sessions_data.append({
                'session': {
                    'id': session_id,
                    'role_title': role_title,
                    'role_brief': role_brief,
                    'created_at': data['flags'][0].timestamp.isoformat() if data['flags'] else None,
                    'problem_description': problem_description,
                },
                'message_count': len(chat_history),
                'chat_history': chat_history,
                'flagged_messages': flagged_messages_list,
                'flagged_content_set': [f.content for f in data['flags']],
                'team': {'name': team.name} if team else None,
                'is_public': True,
                'is_posted_by_user': session.user_id == current_user.id if session else False,
            })

        return render_template(
            "roleplay/conversations.html",
            sessions_data=sessions_data,
            pagination=None,
            show_flagged_only=False,
            show_public_flags=True,
            user_teams=current_user.teams if current_user.is_authenticated else [],
            max_ai_responses=MAX_AI_RESPONSES,
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
    
    sessions = sessions_query.all()

    all_user_sessions = sorted(sessions, key=lambda s: (s.created_at or datetime.min, s.id or ""))
    title_totals = {}
    title_sequence_by_id = {}
    title_running_counts = {}
    for user_session in all_user_sessions:
        base_title = (user_session.role_title or "").strip() or "Konverzace"
        title_totals[base_title] = title_totals.get(base_title, 0) + 1
        title_running_counts[base_title] = title_running_counts.get(base_title, 0) + 1
        title_sequence_by_id[user_session.id] = title_running_counts[base_title]
    
    session_ids = [session.id for session in sessions]

    flagged_by_session = {sid: [] for sid in session_ids}
    if session_ids:
        all_flagged_messages = FlaggedResponse.query.filter(
            FlaggedResponse.session_id.in_(session_ids),
            FlaggedResponse.user_id == current_user.id,
        ).all()
        for flagged in all_flagged_messages:
            flagged_by_session.setdefault(flagged.session_id, []).append(flagged)

    chat_history_by_session = {}
    missing_history_session_ids = []
    for sid in session_ids:
        history = get_chat_history(sid)
        if history is None:
            missing_history_session_ids.append(sid)
        else:
            chat_history_by_session[sid] = history

    if missing_history_session_ids:
        db_messages = ChatMessage.query.filter(
            ChatMessage.session_id.in_(missing_history_session_ids)
        ).order_by(ChatMessage.session_id.asc(), ChatMessage.message_index.asc()).all()

        grouped_db_history = {sid: [] for sid in missing_history_session_ids}
        for msg in db_messages:
            grouped_db_history.setdefault(msg.session_id, []).append({
                'role': msg.role,
                'content': msg.content,
                'timestamp': msg.timestamp.isoformat() if msg.timestamp else None,
            })

        for sid in missing_history_session_ids:
            chat_history_by_session[sid] = grouped_db_history.get(sid, [])

    sessions_data = []
    for session in sessions:
        chat_history = chat_history_by_session.get(session.id, [])
        flagged_messages = flagged_by_session.get(session.id, [])
        
        # Create a list of flagged content for quick lookup (convert set to list for JSON serialization)
        flagged_content_list = [f.content for f in flagged_messages]
        
        # Extract role title and brief from chat history or use defaults
        role_title = (session.role_title or "").strip() or "Konverzace"
        role_brief = ""
        
        if role_title == "Konverzace" and chat_history and len(chat_history) > 0:
            for first_msg in chat_history:
                if first_msg.get('role') == 'system':
                    content = first_msg.get('content', '')
                    # Try to extract role title from system message
                    if 'v roli' in content:
                        # Extract role title from pattern "v roli 'Title'"
                        match = re.search(r"v roli '([^']+)'", content)
                        if match:
                            role_title = match.group(1)
                        # Extract brief if available
                        match = re.search(r"'([^']+)' \(([^)]+)\)", content)
                        if match:
                            role_title = match.group(1)
                            role_brief = match.group(2)
                break

        problem_description = "Zatím nenachytány žádné podezřelé odpovědi."
        if flagged_messages:
            for f in flagged_messages:
                if f.summary:
                    problem_description = f.summary
                    break

        display_role_title = role_title
        if title_totals.get(role_title, 0) > 1:
            display_role_title = f"{role_title} #{title_sequence_by_id.get(session.id, 1)}"
        
        sessions_data.append({
            'session': {
                'id': session.id,
                'role_title': role_title,
                'display_role_title': display_role_title,
                'role_brief': role_brief,
                'created_at': session.created_at.isoformat() if session.created_at else None,
                'problem_description': problem_description
            },
            'message_count': len(chat_history),
            'chat_history': chat_history,
            'flagged_messages': [
                {
                    'id': f.id,
                    'content': f.content,
                    'summary': f.summary,
                    'is_public': f.is_public,
                    'team_id': f.team_id,
                    'message_index': f.message_index,
                }
                for f in flagged_messages
            ],
            'flagged_content_set': flagged_content_list,
            'is_posted_by_user': session.user_id == current_user.id if session else False
        })
    
    return render_template(
        "roleplay/conversations.html",
        sessions_data=sessions_data,
        pagination=None,
        show_flagged_only=show_flagged_only,
        user_teams=current_user.teams,
        max_ai_responses=MAX_AI_RESPONSES
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
    
    user_teams_db = current_user.teams
    app.logger.info(f"--- Initial user_teams_db (current_user.teams): {list(user_teams_db)} ---")

    all_teams_db = Team.query.order_by(Team.name).all()
    app.logger.info(f"--- Initial all_teams_db: {list(all_teams_db)} ---")

    def process_team_description(team_list):
        processed_teams = []
        app.logger.info(f"--- process_team_description called with team_list: {team_list} ---")
        if not team_list:
            app.logger.warning("--- process_team_description received an empty or None team_list ---")
            return []

        for team_obj in team_list:
            team_obj.display_description = "Tento tým nemá popis."
            # Keep DB-backed creator_id as fallback; some legacy rows store it in description JSON.
            creator_id = team_obj.creator_id

            if team_obj.description:
                try:
                    description_data = json.loads(team_obj.description)
                    if isinstance(description_data, dict):
                        team_obj.display_description = description_data.get("original_description", team_obj.description)
                        parsed_creator_id = description_data.get("creator_id")
                        if parsed_creator_id is not None:
                            try:
                                creator_id = int(parsed_creator_id)
                            except (ValueError, TypeError):
                                app.logger.warning(
                                    f"Team '{team_obj.name}': creator_id '{parsed_creator_id}' is not a valid integer."
                                )
                    else:
                        team_obj.display_description = team_obj.description
                except (json.JSONDecodeError, TypeError):
                    app.logger.warning(
                        f"Team '{team_obj.name}': Failed to parse description JSON. Raw description: {team_obj.description}"
                    )
                    team_obj.display_description = team_obj.description if team_obj.description else "Chyba při čtení popisu."

            team_obj.creator_id = creator_id
            processed_teams.append(team_obj)

        app.logger.info(f"--- process_team_description finished, processed_teams: {processed_teams} ---")
        return processed_teams

    user_teams_processed = process_team_description(list(user_teams_db))
    all_teams_processed = process_team_description(list(all_teams_db))

    user_team_ids = {team.id for team in user_teams_processed}
    all_team_ids = [team.id for team in all_teams_processed]

    members_by_team = {team_id: [] for team_id in all_team_ids}
    if all_team_ids:
        member_rows = db.session.query(
            team_membership.c.team_id,
            User.id,
            User.email,
            User.name,
        ).join(User, User.id == team_membership.c.user_id).filter(
            team_membership.c.team_id.in_(all_team_ids)
        ).all()

        for team_id, member_id, member_email, member_name in member_rows:
            members_by_team.setdefault(team_id, []).append({
                'id': member_id,
                'email': member_email,
                'name': member_name,
            })

    flagged_counts_by_team = {team_id: 0 for team_id in all_team_ids}
    if all_team_ids:
        flagged_count_rows = db.session.query(
            FlaggedResponse.team_id,
            func.count(FlaggedResponse.id),
        ).filter(
            FlaggedResponse.team_id.in_(all_team_ids)
        ).group_by(FlaggedResponse.team_id).all()

        for team_id, flagged_count in flagged_count_rows:
            flagged_counts_by_team[team_id] = int(flagged_count)

    creator_team_ids = [team.id for team in all_teams_processed if team.creator_id == current_user.id]
    pending_invites_by_team = {team_id: [] for team_id in creator_team_ids}
    if creator_team_ids:
        pending_invites_rows = TeamInvitation.query.filter(
            TeamInvitation.team_id.in_(creator_team_ids),
            TeamInvitation.status == 'pending',
        ).order_by(TeamInvitation.created_at.desc()).all()

        for inv in pending_invites_rows:
            pending_invites_by_team.setdefault(inv.team_id, []).append({
                'id': inv.id,
                'invitee_email': inv.invitee_email,
                'created_at': inv.created_at.isoformat() if inv.created_at else None,
            })

    for team_obj in all_teams_processed:
        team_obj.member_count = len(members_by_team.get(team_obj.id, []))

    for team_obj in user_teams_processed:
        team_obj.member_count = len(members_by_team.get(team_obj.id, []))

    def serialize_team(team_obj):
        """Serialize team object for JSON"""
        is_member = team_obj.id in user_team_ids
        is_creator = team_obj.creator_id == current_user.id

        members_list = []
        for member in members_by_team.get(team_obj.id, []):
            member_data = {
                'id': member['id']
            }

            if is_member:
                member_data['email'] = member['email']
                member_data['name'] = member['name'] if member['name'] else member['email']
            else:
                member_data['email'] = None
                member_data['name'] = f"Člen {member['id']}"

            members_list.append(member_data)

        pending_invites = pending_invites_by_team.get(team_obj.id, []) if is_creator else []
        pending_invites_count = len(pending_invites)

        flagged_responses_count = flagged_counts_by_team.get(team_obj.id, 0) if is_member else 0

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
    """Operational admin workspace for moderation, publication control, teams, and statistics."""
    if not current_user.is_super_admin:
        flash("Přístup odepřen: Nemáte oprávnění k zobrazení této stránky.", "danger")
        return redirect(url_for("roleplay.roleplay_home"))

    now = datetime.utcnow()
    time_24_hours_ago = now - timedelta(hours=24)

    # Shared filters
    search_query = (request.args.get("q") or "").strip()
    user_email_filter = (request.args.get("user_email") or "").strip()
    visibility_filter = (request.args.get("visibility") or "all").strip().lower()
    selected_team_id = request.args.get("team_id", type=int)
    lookback_value = (request.args.get("days") or "30").strip().lower()
    if lookback_value == "all":
        since_dt = None
    else:
        try:
            lookback_days = int(lookback_value)
        except ValueError:
            lookback_days = 30
        if lookback_days not in [1, 7, 30, 90]:
            lookback_days = 30
        lookback_value = str(lookback_days)
        since_dt = now - timedelta(days=lookback_days)

    # Pagination params per section
    page_flags = request.args.get("page_flags", 1, type=int)
    page_published = request.args.get("page_published", 1, type=int)
    page_teams = request.args.get("page_teams", 1, type=int)
    per_page_flags = 15
    per_page_published = 10
    per_page_teams = 12

    total_users = User.query.count()
    total_chat_sessions = ChatSession.query.count()
    total_teams = Team.query.count()
    total_flags = FlaggedResponse.query.count()
    public_flags_count = FlaggedResponse.query.filter_by(is_public=True).count()
    private_flags_count = max(total_flags - public_flags_count, 0)
    chats_last_24h = ChatSession.query.filter(ChatSession.created_at >= time_24_hours_ago).count()
    flags_last_24h = FlaggedResponse.query.filter(FlaggedResponse.timestamp >= time_24_hours_ago).count()

    flagged_sessions_count = db.session.query(func.count(func.distinct(FlaggedResponse.session_id))).scalar() or 0
    published_sessions_count = db.session.query(
        func.count(func.distinct(FlaggedResponse.session_id))
    ).filter(FlaggedResponse.is_public.is_(True)).scalar() or 0

    moderation_query = FlaggedResponse.query.options(
        joinedload(FlaggedResponse.user),
        joinedload(FlaggedResponse.team),
        joinedload(FlaggedResponse.session),
    )

    if since_dt is not None:
        moderation_query = moderation_query.filter(FlaggedResponse.timestamp >= since_dt)

    if visibility_filter == "public":
        moderation_query = moderation_query.filter(FlaggedResponse.is_public.is_(True))
    elif visibility_filter == "private":
        moderation_query = moderation_query.filter(FlaggedResponse.is_public.is_(False))

    if selected_team_id:
        moderation_query = moderation_query.filter(FlaggedResponse.team_id == selected_team_id)

    if user_email_filter:
        moderation_query = moderation_query.filter(
            FlaggedResponse.user.has(User.email.ilike(f"%{user_email_filter}%"))
        )

    if search_query:
        moderation_query = moderation_query.filter(
            db.or_(
                FlaggedResponse.id.ilike(f"%{search_query}%"),
                FlaggedResponse.session_id.ilike(f"%{search_query}%"),
                FlaggedResponse.content.ilike(f"%{search_query}%"),
                FlaggedResponse.summary.ilike(f"%{search_query}%"),
                FlaggedResponse.user.has(User.email.ilike(f"%{search_query}%")),
            )
        )

    moderation_flags = moderation_query.order_by(FlaggedResponse.timestamp.desc()).paginate(
        page=page_flags,
        per_page=per_page_flags,
        error_out=False,
    )

    published_base = db.session.query(
        FlaggedResponse.session_id.label("session_id"),
        func.count(FlaggedResponse.id).label("public_flags_count"),
        func.max(FlaggedResponse.timestamp).label("latest_public_flag_at"),
    ).filter(
        FlaggedResponse.is_public.is_(True),
    ).group_by(FlaggedResponse.session_id)

    if since_dt is not None:
        published_base = published_base.filter(FlaggedResponse.timestamp >= since_dt)

    if selected_team_id:
        published_base = published_base.filter(FlaggedResponse.team_id == selected_team_id)

    if user_email_filter:
        published_base = published_base.filter(
            FlaggedResponse.user.has(User.email.ilike(f"%{user_email_filter}%"))
        )

    if search_query:
        published_base = published_base.filter(
            db.or_(
                FlaggedResponse.session_id.ilike(f"%{search_query}%"),
                FlaggedResponse.summary.ilike(f"%{search_query}%"),
                FlaggedResponse.user.has(User.email.ilike(f"%{search_query}%")),
            )
        )

    published_subquery = published_base.subquery()

    published_sessions_query = db.session.query(
        ChatSession,
        User.email.label("owner_email"),
        published_subquery.c.public_flags_count,
        published_subquery.c.latest_public_flag_at,
    ).join(
        published_subquery, ChatSession.id == published_subquery.c.session_id
    ).join(
        User, ChatSession.user_id == User.id
    )

    if search_query:
        published_sessions_query = published_sessions_query.filter(
            db.or_(
                ChatSession.id.ilike(f"%{search_query}%"),
                ChatSession.role_title.ilike(f"%{search_query}%"),
                User.email.ilike(f"%{search_query}%"),
            )
        )

    published_sessions_pagination = published_sessions_query.order_by(
        published_subquery.c.latest_public_flag_at.desc()
    ).paginate(page=page_published, per_page=per_page_published, error_out=False)

    published_session_ids = [row.ChatSession.id for row in published_sessions_pagination.items]
    message_counts_by_session = {}
    if published_session_ids:
        message_count_rows = db.session.query(
            ChatMessage.session_id,
            func.count(ChatMessage.id),
        ).filter(
            ChatMessage.session_id.in_(published_session_ids)
        ).group_by(ChatMessage.session_id).all()

        message_counts_by_session = {session_id: int(cnt) for session_id, cnt in message_count_rows}

    published_rows = []
    for row in published_sessions_pagination.items:
        published_rows.append({
            "session": row.ChatSession,
            "owner_email": row.owner_email,
            "public_flags_count": int(row.public_flags_count or 0),
            "latest_public_flag_at": row.latest_public_flag_at,
            "message_count": message_counts_by_session.get(row.ChatSession.id, 0),
        })

    teams_pagination = Team.query.order_by(Team.name.asc()).paginate(
        page=page_teams,
        per_page=per_page_teams,
        error_out=False,
    )

    teams_rows = []
    for team in teams_pagination.items:
        teams_rows.append({
            "team": team,
            "member_count": team.members.count(),
            "flagged_count": FlaggedResponse.query.filter_by(team_id=team.id).count(),
            "public_flagged_count": FlaggedResponse.query.filter_by(team_id=team.id, is_public=True).count(),
            "pending_invitations": TeamInvitation.query.filter_by(team_id=team.id, status="pending").count(),
        })

    top_team_rows = db.session.query(
        Team.name,
        func.count(FlaggedResponse.id).label("flag_count"),
    ).join(
        FlaggedResponse, FlaggedResponse.team_id == Team.id
    )
    if since_dt is not None:
        top_team_rows = top_team_rows.filter(FlaggedResponse.timestamp >= since_dt)
    top_team_rows = top_team_rows.group_by(
        Team.id,
        Team.name,
    ).order_by(
        func.count(FlaggedResponse.id).desc(),
        Team.name.asc(),
    ).limit(5).all()

    top_user_rows = db.session.query(
        User.email,
        func.count(FlaggedResponse.id).label("flag_count"),
    ).join(
        FlaggedResponse, FlaggedResponse.user_id == User.id
    )
    if since_dt is not None:
        top_user_rows = top_user_rows.filter(FlaggedResponse.timestamp >= since_dt)
    top_user_rows = top_user_rows.group_by(
        User.id,
        User.email,
    ).order_by(
        func.count(FlaggedResponse.id).desc(),
        User.email.asc(),
    ).limit(5).all()

    recent_activity = {
        "flags_24h": flags_last_24h,
        "flags_7d": FlaggedResponse.query.filter(
            FlaggedResponse.timestamp >= now - timedelta(days=7)
        ).count(),
        "sessions_24h": chats_last_24h,
        "sessions_7d": ChatSession.query.filter(
            ChatSession.created_at >= now - timedelta(days=7)
        ).count(),
    }

    all_teams = Team.query.order_by(Team.name.asc()).all()

    return render_template(
        "roleplay/admin_dashboard.html",
        total_users=total_users,
        total_chat_sessions=total_chat_sessions,
        total_teams=total_teams,
        total_flags=total_flags,
        public_flags_count=public_flags_count,
        private_flags_count=private_flags_count,
        flagged_sessions_count=flagged_sessions_count,
        published_sessions_count=published_sessions_count,
        chats_last_24h=chats_last_24h,
        flags_last_24h=flags_last_24h,
        moderation_flags=moderation_flags,
        published_sessions_pagination=published_sessions_pagination,
        published_rows=published_rows,
        teams_pagination=teams_pagination,
        teams_rows=teams_rows,
        top_team_rows=top_team_rows,
        top_user_rows=top_user_rows,
        recent_activity=recent_activity,
        all_teams=all_teams,
        lookback_value=lookback_value,
        visibility_filter=visibility_filter,
        selected_team_id=selected_team_id,
        user_email_filter=user_email_filter,
        search_query=search_query,
    )


@roleplay.route("/admin-dashboard/flag/<flagged_id>/visibility", methods=["POST"])
@login_required
def admin_set_flag_visibility(flagged_id):
    """Allow super admin to override any flagged response visibility."""
    if not current_user.is_super_admin:
        return jsonify({"success": False, "error": "Přístup odepřen."}), 403

    flagged_response = FlaggedResponse.query.get(flagged_id)
    if not flagged_response:
        return jsonify({"success": False, "error": "Označení nebylo nalezeno."}), 404

    raw_is_public = request.form.get("is_public")
    if raw_is_public is None and request.is_json:
        payload = request.get_json(silent=True) or {}
        raw_is_public = payload.get("is_public")

    if raw_is_public is None:
        flash("Nepodařilo se změnit viditelnost: chybí hodnota.", "danger")
        return redirect(url_for("roleplay.admin_dashboard", **request.args.to_dict()))

    is_public = str(raw_is_public).strip().lower() in ["1", "true", "yes", "on"]
    flagged_response.is_public = is_public

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error changing admin visibility for flag {flagged_id}: {str(e)}")
        if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
            return jsonify({"success": False, "error": "Změna viditelnosti se nezdařila."}), 500
        flash("Změna viditelnosti se nezdařila.", "danger")
        return redirect(url_for("roleplay.admin_dashboard", **request.args.to_dict()))

    if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
        return jsonify({"success": True, "is_public": flagged_response.is_public})

    flash("Viditelnost označení byla aktualizována.", "success")
    next_url = request.form.get("next")
    if next_url:
        return redirect(next_url)
    return redirect(url_for("roleplay.admin_dashboard", **request.args.to_dict()))


@roleplay.route("/admin-dashboard/reset-publications", methods=["POST"])
@login_required
def admin_reset_publications():
    """Set all published flagged responses back to private (competition reset)."""
    if not current_user.is_super_admin:
        return jsonify({"success": False, "error": "Přístup odepřen."}), 403

    try:
        updated_count = FlaggedResponse.query.filter(
            FlaggedResponse.is_public.is_(True)
        ).update(
            {FlaggedResponse.is_public: False},
            synchronize_session=False,
        )
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error resetting publications: {str(e)}")
        if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
            return jsonify({"success": False, "error": "Reset zveřejnění se nezdařil."}), 500
        flash("Reset zveřejnění se nezdařil.", "danger")
        return redirect(url_for("roleplay.admin_dashboard", **request.args.to_dict()))

    if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
        return jsonify({"success": True, "updated_count": int(updated_count or 0)})

    flash(f"Reset dokončen: {int(updated_count or 0)} označení bylo nastaveno jako soukromé.", "success")
    next_url = request.form.get("next")
    if next_url:
        return redirect(next_url)
    return redirect(url_for("roleplay.admin_dashboard", **request.args.to_dict()))


@roleplay.route("/admin-dashboard/session/<session_id>", methods=["GET"])
@login_required
def admin_session_detail(session_id):
    """Return complete session detail for admin transcript inspection."""
    if not current_user.is_super_admin:
        return jsonify({"success": False, "error": "Přístup odepřen."}), 403

    session = ChatSession.query.options(joinedload(ChatSession.user)).filter_by(id=session_id).first()
    if not session:
        return jsonify({"success": False, "error": "Relace nebyla nalezena."}), 404

    chat_history = get_chat_history(session_id)
    if chat_history is None:
        db_messages = ChatMessage.query.filter_by(session_id=session_id).order_by(ChatMessage.message_index.asc()).all()
        chat_history = [{
            "role": msg.role,
            "content": msg.content,
            "timestamp": msg.timestamp.isoformat() if msg.timestamp else None,
        } for msg in db_messages]

    flags = FlaggedResponse.query.options(
        joinedload(FlaggedResponse.user),
        joinedload(FlaggedResponse.team),
    ).filter_by(session_id=session_id).order_by(FlaggedResponse.timestamp.asc()).all()

    return jsonify({
        "success": True,
        "session": {
            "id": session.id,
            "role_id": session.role_id,
            "role_title": (session.role_title or "").strip() or "Konverzace",
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "updated_at": session.updated_at.isoformat() if session.updated_at else None,
            "owner_email": session.user.email if session.user else "Neznámý uživatel",
        },
        "chat_history": chat_history,
        "flags": [{
            "id": f.id,
            "content": f.content,
            "summary": f.summary,
            "is_public": f.is_public,
            "timestamp": f.timestamp.isoformat() if f.timestamp else None,
            "user_email": f.user.email if f.user else "Neznámý uživatel",
            "team_name": f.team.name if f.team else None,
        } for f in flags],
    })

@roleplay.route("/flag", methods=["POST"])
@login_required
def flag_response():
    """
    Flag an inappropriate assistant response from a chat session.
    
    Request JSON:
        {
            "session_id": UUID,
            "flagged_content": string,
            "message_index": integer (optional),
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
    message_index = data.get("message_index")
    summary = data.get("summary")
    team_id = data.get("team_id")
    is_public = data.get("is_public", False)
    
    if not session_id:
        return jsonify({"error": "Chybějící session_id."}), 400
    
    if not flagged_content:
        return jsonify({"error": "Chybějící flagged_content."}), 400

    if message_index in ("", None):
        message_index = None
    else:
        try:
            message_index = int(message_index)
        except (ValueError, TypeError):
            return jsonify({"error": "message_index musí být celé číslo."}), 400
    
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
            message_index=message_index,
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
        flagged_id: The flagged response ID (preferred)
        session_id: The session ID
        content: The content of the message to unflag (fallback for legacy records)
    
    Returns:
        JSON response with success status
    """
    data = request.get_json() or {}
    flagged_id = data.get('flagged_id')
    session_id = data.get('session_id')
    content = data.get('content')

    flagged = None
    if flagged_id:
        flagged = FlaggedResponse.query.filter_by(
            id=flagged_id,
            user_id=current_user.id,
        ).first()
    else:
        if not session_id or not content:
            return jsonify({'success': False, 'error': 'Missing flagged_id or session_id/content'}), 400

        # Legacy fallback: identify by session + content
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
    message = message[:TEAM_INVITE_MAX_MESSAGE_LENGTH]
    
    if not emails or not isinstance(emails, list):
        return jsonify({"success": False, "error": "Prosím zadejte alespoň jeden email."}), 400

    if len(emails) > TEAM_INVITE_MAX_EMAILS_PER_REQUEST:
        return jsonify({
            "success": False,
            "error": f"Najednou lze pozvat maximálně {TEAM_INVITE_MAX_EMAILS_PER_REQUEST} adres."
        }), 400
    
    try:
        email_pattern = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
        now_utc = datetime.utcnow()
        inviter_window_start = now_utc - timedelta(hours=1)
        team_window_start = now_utc - timedelta(days=1)
        resend_cooldown_start = now_utc - timedelta(hours=TEAM_INVITE_RESEND_COOLDOWN_HOURS)

        inviter_invites_last_hour = TeamInvitation.query.filter(
            TeamInvitation.inviter_id == current_user.id,
            TeamInvitation.created_at >= inviter_window_start
        ).count()

        team_invites_last_day = TeamInvitation.query.filter(
            TeamInvitation.team_id == team_id,
            TeamInvitation.created_at >= team_window_start
        ).count()

        if inviter_invites_last_hour >= TEAM_INVITE_MAX_PER_HOUR_PER_INVITER:
            return jsonify({
                "success": False,
                "error": "Dosáhli jste hodinového limitu pozvánek. Zkuste to později."
            }), 429

        if team_invites_last_day >= TEAM_INVITE_MAX_PER_DAY_PER_TEAM:
            return jsonify({
                "success": False,
                "error": "Tým dosáhl denního limitu pozvánek. Zkuste to zítra."
            }), 429

        # Normalize and deduplicate input emails while preserving order
        normalized_emails = []
        seen_emails = set()
        for raw_email in emails:
            if not isinstance(raw_email, str):
                continue
            normalized_email = raw_email.strip().lower()
            if normalized_email and normalized_email not in seen_emails:
                normalized_emails.append(normalized_email)
                seen_emails.add(normalized_email)

        member_emails = {member.email for member in team.members.all()}
        existing_users = User.query.filter(User.email.in_(normalized_emails)).all() if normalized_emails else []
        users_by_email = {user.email: user for user in existing_users}

        existing_pending_invites = TeamInvitation.query.filter(
            TeamInvitation.team_id == team_id,
            TeamInvitation.invitee_email.in_(normalized_emails),
            TeamInvitation.status == 'pending'
        ).all() if normalized_emails else []
        existing_pending_email_set = {inv.invitee_email for inv in existing_pending_invites}

        recent_invites = TeamInvitation.query.filter(
            TeamInvitation.team_id == team_id,
            TeamInvitation.invitee_email.in_(normalized_emails),
            TeamInvitation.created_at >= resend_cooldown_start
        ).all() if normalized_emails else []
        recent_invite_email_set = {inv.invitee_email for inv in recent_invites}

        invited_count = 0
        invalid_count = 0
        skipped_count = 0
        limit_hit = False
        warnings = []
        
        for email in normalized_emails:
            if invited_count + inviter_invites_last_hour >= TEAM_INVITE_MAX_PER_HOUR_PER_INVITER:
                limit_hit = True
                break

            if invited_count + team_invites_last_day >= TEAM_INVITE_MAX_PER_DAY_PER_TEAM:
                limit_hit = True
                break

            if email == current_user.email:
                skipped_count += 1
                continue
            
            if not email_pattern.match(email):
                invalid_count += 1
                continue
            
            # Existing users already in team are skipped (generic response, no enumeration leak)
            user = users_by_email.get(email)
            if user and email in member_emails:
                skipped_count += 1
                continue

            # Skip if pending invitation already exists
            if email in existing_pending_email_set:
                skipped_count += 1
                continue

            # Cooldown protection to avoid repeated sending to the same target
            if email in recent_invite_email_set:
                skipped_count += 1
                continue
            
            invitation = TeamInvitation(
                team_id=team_id,
                inviter_id=current_user.id,
                invitee_email=email,
                message=message,
                status='pending'
            )
            db.session.add(invitation)
            invited_count += 1

        if invalid_count > 0:
            warnings.append("Některé adresy mají neplatný formát a byly přeskočeny.")
        if skipped_count > 0:
            warnings.append("Některé adresy nebyly zpracovány (duplicitní, nedávno pozvané nebo již členové týmu).")
        if limit_hit:
            warnings.append("Byl dosažen bezpečnostní limit, zbývající adresy nebyly zpracovány.")
        
        db.session.commit()
        
        processed_count = invited_count + invalid_count + skipped_count
        result = {
            "success": True,
            "message": "Pozvánky byly zpracovány.",
            "invited_count": invited_count,
            "processed_count": processed_count,
            "skipped_count": invalid_count + skipped_count,
            "limit_hit": limit_hit
        }
        
        if warnings:
            result["warnings"] = warnings
            result["errors"] = warnings
        
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
        invitations = TeamInvitation.query.options(
            joinedload(TeamInvitation.team),
            joinedload(TeamInvitation.inviter),
        ).filter_by(
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
        invitations = TeamInvitation.query.options(
            joinedload(TeamInvitation.inviter),
        ).filter_by(
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
            role_id=role_id,
            role_title=role_title
        )
        db.session.add(chat_session)
        db.session.commit()
        app.logger.info(f"Created chat session {session_id} for user {current_user.id}")
    except Exception as e:
        db.session.rollback()
        delete_roleplay_session_bootstrap(session_id)
        app.logger.error(f"Error creating chat session: {str(e)}")
        return jsonify({"error": "Chyba při vytváření relace chatu"}), 500
    
    return jsonify({"session_id": session_id})