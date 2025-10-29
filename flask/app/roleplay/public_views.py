from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_login import login_required, current_user
from app.models import ChatSession, FlaggedResponse, ChatMessage, User, Team
from app import db
from sqlalchemy import desc
import json

roleplay = Blueprint('roleplay', __name__)

@roleplay.route('/public/ulovky')
def public_ulovky():
    """Display public flagged conversations."""
    # Get all public flagged responses with session and user info
    flagged_responses = db.session.query(FlaggedResponse)\
        .filter(FlaggedResponse.is_public == True)\
        .join(ChatSession)\
        .join(User)\
        .order_by(desc(FlaggedResponse.timestamp))\
        .all()
    
    # Group by session to avoid duplicates
    sessions_data = {}
    for flag in flagged_responses:
        session_id = flag.session_id
        if session_id not in sessions_data:
            sessions_data[session_id] = {
                'session': flag.session,
                'user': flag.user,
                'team': flag.team if flag.team_id else None,
                'flagged_count': 0,
                'latest_flag': flag.timestamp
            }
        sessions_data[session_id]['flagged_count'] += 1
        if flag.timestamp > sessions_data[session_id]['latest_flag']:
            sessions_data[session_id]['latest_flag'] = flag.timestamp
    
    return render_template('roleplay/public_ulovky.html', sessions_data=sessions_data)

# Removed the duplicate public_conversation_detail function
