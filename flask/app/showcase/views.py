from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash
from app.roleplay.chat_utils import generate_session_id_for_roleplay_chat
from app import app

from .setup import MAX_AI_RESPONSES, SHOWCASE_ACTIVE, personas, prepare_session_prompt

showcase = Blueprint("showcase", __name__)

@showcase.route("/")
def index():
    if not SHOWCASE_ACTIVE:
        flash("Ukázka není aktivní.", "warning")
        return redirect(url_for("public.index"))
    
    return render_template("showcase/index.html", personas=personas)

@showcase.route("/<persona_id>")
def chat(persona_id):
    if not SHOWCASE_ACTIVE:
        flash("Ukázka není aktivní.", "warning")
        return redirect(url_for("public.index"))
    
    persona = personas.get(persona_id)
    persona.id = persona_id

    if not persona:
        flash("Persona not found.", "danger")
        return redirect(url_for("showcase.index"))
    
    return render_template("showcase/chat.html", persona=persona, max_ai_responses=MAX_AI_RESPONSES)

@showcase.route("/generate_session_id", methods=["POST"])
def generate_session_id():
    """Generate a unique session ID for WebSocket chat"""
    data = request.get_json()
    
    if not data:
        return jsonify({"error": "Chybějící data"}), 400
        
    persona_id = data.get("persona")

    if not persona_id:
        return jsonify({"error": "Chybějící povinné pole: persona"}), 400

    persona = personas.get(persona_id)

    if not persona:
        return jsonify({"error": "Neplatné persona_id"}), 400
    
    try:
        prompt = prepare_session_prompt(
            persona=persona
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
        "user_id": "showcase_user",  # Static user ID for showcase
        "role": {
            "id": persona_id,
            "title": persona.name,
            "description": persona.description,
        },
        "messages": messages  # LangChain-ready messages
    }
    
    # Generate session ID and store in Redis
    try:
        session_id = generate_session_id_for_roleplay_chat(role_information)
    except Exception as e:
        app.logger.error(f"Error creating roleplay Redis session: {str(e)}")
        return jsonify({"error": "Chyba při přípravě chat relace. Zkuste to prosím znovu."}), 503
    
    return jsonify({"session_id": session_id})