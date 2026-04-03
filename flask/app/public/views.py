import os
from flask import (
    render_template,
    url_for,
    flash,
    redirect,
    request,
    session,
    Blueprint,
    jsonify,
)
from flask_login import login_user, current_user
from flask.helpers import safe_join
from app import db, basedir, app, oauth
from cryptography.fernet import Fernet
from hashids import Hashids
from app.mail import send_email
from app.models import User, Course
from app.public.forms import (
    RegistrationForm,
    LoginForm,
    ResetPasswordForm,
    ResetPasswordRequestForm,
)
import requests
import json
from authlib.integrations.base_client.errors import OAuthError
from datetime import datetime
from urllib.parse import urlparse

public = Blueprint("public", __name__)

cipher_suite = Fernet(b"CLbOShYydTCn6udFzYOXj5C4OqrQ8Rz15hTtL4sSLDI=")
hasher = Hashids("7qsnqSGiOlZdQOUQzXrM")


@public.route("/", methods=["GET", "POST"])
def index():
    return redirect(url_for("public.login"))

'''
@public.route("/course/<hash>")
def share_webchat(hash):
    try: 
        # course_id = cipher_suite.decrypt(hash.encode()).decode()
        course_id = hasher.decode(hash)[0]
        course = Course.query.filter_by(id=course_id).first()
        if not course:
            raise Exception()
    except:
        return "course not found"

    # Use f-string for cleaner formatting
    return f"""
    <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no">
    <script>
    localStorage.removeItem("chat_session");
    !function(){{
        let e=document.createElement("script"),t=document.head||document.getElementsByTagName("head")[0];
        e.src="https://cdn.jsdelivr.net/npm/rasa-webchat@1.0.1/lib/index.js";
        e.async=!0;
        e.onload=(()=>{{ // This function runs after the webchat script is loaded
            window.WebChat.default({{
                customData:{{current_url:window.location.href,custom_course:{str(course_id)}}},
                initPayload: "/get_started",
                socketUrl:'{os.environ.get("RASA_URL", "FILL_RASA_URL")}',
                title: "{str(course.name)}",
                inputTextFieldHint: "",
                customMessageDelay: (message) => {{
                    return 750;
                }}
            }},null);

            // Add logic to open the chat widget after initialization
            setTimeout(function() {{
                const widgetContainer = document.querySelector(".rw-widget-container");
                // Check if widget exists and is not already open
                if (widgetContainer && ![...widgetContainer.classList].includes("rw-chat-open")) {{
                    const launcher = document.querySelector('.rw-launcher');
                    if (launcher) {{
                        launcher.click();
                    }}
                }}
            }}, 500); // Small delay to ensure widget DOM is ready
        }});
        t.insertBefore(e,t.firstChild)
    }}();
    </script>
    <style>
    @media (max-width: 576px) {{.rw-replies .rw-reply {{font-size: 14px;}}}}
    body {{
        background-image: url('{os.environ.get("PROJECT_URL", "FILL_PROJECT_URL")}/static/media/img/chat-background.jpg');
    }}
    @media screen and (min-width: 800px) {{
        .rw-messages-container {{
            height: 550px !important;
            max-height: 65vh !important;
        }}
        .rw-widget-container .rw-conversation-container {{
            width: 450px !important;
        }}
      }}
    .rw-conversation-container .rw-image-frame {{
        height: auto !important;
    }}

    .rw-conversation-container .rw-send .rw-send-icon {{
          fill: #135afe !important;
    }}

    .rw-messages-container {{
        background-color: #eeeeee !important;
        background-image: url('{os.environ.get("PROJECT_URL", "FILL_PROJECT_URL")}/static/uploads/back-tabs-250.png');
    }}

    .rw-conversation-container .rw-response {{
        background-color: white !important;
        line-height: 1.5 !important;
    }}

    .rw-conversation-container .rw-new-message {{
        background-color: white;
    }}

    .rw-conversation-container .rw-sender {{
        background-color: white;
    }}

    .rw-conversation-container .rw-send {{
        background: white;
    }}
    </style>
    <!-- Removed the old window.onload script block -->
    """
'''

@public.route("/course/<hash>")
def share_webchat(hash):
    try: 
        course_id = hasher.decode(hash)[0]
        course = Course.query.filter_by(id=course_id).first()
        if not course:
            raise Exception()
    except:
        return "course not found"
    
    # Use production URL by default, fall back to localhost for local dev
    backend_url = os.environ.get("WEBCHAT_BACKEND_URL", "https://webchat.edu-ai.eu").rstrip("/")
    
    # Generate conversation ID server-side
    import random
    import string
    conversation_id = 'test-' + ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    
    return f"""
<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no" />
    <title>{course.name} (ID: {course_id})</title>
  </head>
  <body>
    <script>
    localStorage.removeItem("chat_session");
    !function(){{
        let e=document.createElement("script"),t=document.head||document.getElementsByTagName("head")[0];
        e.src="https://cdn.jsdelivr.net/npm/rasa-webchat@1.0.1/lib/index.js";
        e.async=!0;
        e.onload=(()=>{{
            window.WebChat.default({{
                customData:{{current_url:window.location.href,custom_course: {course_id}}},
                initPayload: "/get_started",
                socketUrl:'{backend_url}',
                title: "{course.name}",
                subtitle: "Test Mode - ID: {course_id}",
                inputTextFieldHint: "",
                customMessageDelay: (message) => {{
                    return 750;
                }}
            }},null);

            // Auto-open the chat widget
            setTimeout(function() {{
                const widgetContainer = document.querySelector(".rw-widget-container");
                if (widgetContainer && ![...widgetContainer.classList].includes("rw-chat-open")) {{
                    const launcher = document.querySelector('.rw-launcher');
                    if (launcher) {{
                        launcher.click();
                    }}
                }}
            }}, 500);
        }});
        t.insertBefore(e,t.firstChild)
    }}();
    </script>
    
    <style>
      body {{
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
        margin: 0;
        padding: 20px;
        background: #f5f5f5;
        background-image: url('{os.environ.get("PROJECT_URL", "")}/static/media/img/chat-background.jpg');
        background-size: cover;
      }}
      
      @media (max-width: 576px) {{
        .rw-replies .rw-reply {{
          font-size: 14px;
        }}
      }}
      
      @media screen and (min-width: 800px) {{
        .rw-messages-container {{
          height: 550px !important;
          max-height: 65vh !important;
        }}
        .rw-widget-container .rw-conversation-container {{
          width: 450px !important;
        }}
      }}
      
      .rw-conversation-container .rw-image-frame {{
        height: auto !important;
      }}
      
      .rw-conversation-container .rw-send .rw-send-icon {{
        fill: #135afe !important;
      }}
      
      .rw-messages-container {{
        background-color: #eeeeee !important;
        background-image: url('{os.environ.get("PROJECT_URL", "")}/static/uploads/back-tabs-250.png');
      }}
      
      .rw-conversation-container .rw-response {{
        background-color: white !important;
        line-height: 1.5 !important;
      }}
      
      .rw-conversation-container .rw-new-message {{
        background-color: white;
      }}
      
      .rw-conversation-container .rw-sender {{
        background-color: white;
      }}
      
      .rw-conversation-container .rw-send {{
        background: white;
      }}
    </style>
  </body>
</html>
"""

@public.route("/register", methods=["GET", "POST"])
def register():
    if os.getenv("ALLOW_REGISTER") != "1":
        flash("Registrace není povolena!", "warning")
        return redirect(url_for("public.login"))

    form = RegistrationForm()

    if form.validate_on_submit():
        user = User(name=form.name.data, email=form.email.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        db.session.refresh(user)

        flash("Díky za registraci!", "info")
        return redirect(url_for("public.login"))

    return render_template("public/register.html", form=form)


@public.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    form = ResetPasswordRequestForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user:
            send_email(
                subject="Reset hesla",
                recipients=[user.email],
                html=render_template(
                    "public/email.html",
                    reset_url=url_for(
                        "public.reset_password_token",
                        token=user.get_reset_password_token(),
                        _external=True,
                    ),
                    project_url=os.environ.get("PROJECT_URL", "FILL_PROJECT_URL"),
                ),
            )

            flash("Email s odkazem pro reset hesla byl odeslán", "info")
        return redirect(url_for("public.login"))

    return render_template("public/reset_password_request.html", form=form)


@public.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password_token(token):
    if current_user.is_authenticated:
        return redirect(url_for("admin.courses"))

    user = User.verify_reset_password_token(token)
    if not user:
        return redirect(url_for("public.login"))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        db.session.commit()
        flash("Nové heslo bylo nastaveno!", "success")
        return redirect(url_for("public.login"))
    return render_template("public/reset_password.html", form=form)


@public.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("roleplay.roleplay_home"))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user is None:
            flash("Špatné heslo!", "danger")
            return redirect(url_for("public.login"))

        if user.check_password(form.password.data):
            login_user(user)
            next_page = _sanitize_next_url(request.args.get("next"))
            if next_page:
                return redirect(next_page)
            
            # If no valid next parameter, go to courses
            return redirect(url_for("roleplay.roleplay_home"))
        else:
            flash("Špatné heslo!", "danger")

    return render_template("public/login.html", form=form)


def _sanitize_next_url(next_page):
    if not next_page:
        return None
    if "://" in next_page:
        parsed = urlparse(next_page)
        if parsed.path and parsed.path.startswith("/"):
            return parsed.path
        return None
    if next_page.startswith("/"):
        return next_page
    return None


@public.route("/auth/google")
def auth_google():
    if current_user.is_authenticated:
        return redirect(url_for("roleplay.roleplay_home"))

    google_client = oauth.create_client("google")
    if not google_client:
        flash("Google přihlášení není nakonfigurováno.", "danger")
        return redirect(url_for("public.login"))

    session.pop("post_auth_next", None)
    next_page = _sanitize_next_url(request.args.get("next"))
    if next_page:
        session["post_auth_next"] = next_page
    redirect_uri = app.config.get("GOOGLE_CALLBACK_URL") or url_for("public.auth_google_callback", _external=True)
    return google_client.authorize_redirect(redirect_uri)


@public.route("/auth/google/callback")
def auth_google_callback():
    google_client = oauth.create_client("google")
    if not google_client:
        flash("Google přihlášení není nakonfigurováno.", "danger")
        return redirect(url_for("public.login"))

    try:
        token = google_client.authorize_access_token()
    except OAuthError:
        flash("Google přihlášení se nepodařilo. Zkuste to prosím znovu.", "danger")
        return redirect(url_for("public.login"))

    user_info = token.get("userinfo")
    if not user_info:
        try:
            user_info = google_client.parse_id_token(token)
        except Exception:
            user_info = None

    if not user_info:
        flash("Nepodařilo se načíst Google profil.", "danger")
        return redirect(url_for("public.login"))

    email = (user_info.get("email") or "").lower().strip()
    google_sub = user_info.get("sub")
    email_verified = bool(user_info.get("email_verified"))

    if not email or not google_sub:
        flash("Google přihlášení nevrátilo kompletní údaje.", "danger")
        return redirect(url_for("public.login"))

    existing_by_email = User.query.filter_by(email=email).first()
    if existing_by_email and not email_verified and existing_by_email.google_sub != google_sub:
        flash("Google účet musí mít ověřený e-mail pro propojení s existujícím účtem.", "warning")
        return redirect(url_for("public.login"))

    user = User.query.filter_by(google_sub=google_sub).first()
    if not user and email_verified:
        user = existing_by_email

    if not user:
        user = User(
            email=email,
            name=(user_info.get("name") or email.split("@")[0])[:255],
            auth_provider="google",
            google_sub=google_sub,
        )
        if email_verified:
            user.email_verified_at = datetime.utcnow()
        db.session.add(user)
    else:
        user.auth_provider = user.auth_provider or "google"
        if not user.google_sub:
            user.google_sub = google_sub
        if email_verified and not user.email_verified_at:
            user.email_verified_at = datetime.utcnow()

    db.session.commit()
    login_user(user)

    next_page = _sanitize_next_url(session.pop("post_auth_next", None))
    if next_page:
        return redirect(next_page)
    return redirect(url_for("roleplay.roleplay_home"))
