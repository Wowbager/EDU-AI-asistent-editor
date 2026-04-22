from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash

from .setup import MAX_AI_RESPONSES, SHOWCASE_ACTIVE, personas

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
    if not persona:
        flash("Persona not found.", "danger")
        return redirect(url_for("showcase.index"))
    
    return render_template("showcase/chat.html", persona=persona, max_ai_responses=MAX_AI_RESPONSES)