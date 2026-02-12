import os
import uuid
from flask import Flask, request, redirect, jsonify, url_for  # Ensure jsonify and url_for are imported
from flask_login import LoginManager
from datetime import timedelta
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_mail import Mail
from flask_cors import CORS
import logging  # Added import
from werkzeug.middleware.proxy_fix import ProxyFix  # Added import
import re  # Added import for regular expressions
import sentry_sdk


if os.environ.get("SENTRY_DSN"):
    sentry_sdk.init(
        dsn=os.environ.get("SENTRY_DSN"),
        # Add data like request headers and IP for users,
        # see https://docs.sentry.io/platforms/python/data-management/data-collected/ for more info
        send_default_pii=True,
        # Set traces_sample_rate to 1.0 to capture 100%
        # of transactions for tracing.
        traces_sample_rate=1.0,
        # Profiling options require newer sentry-sdk versions.
    )

app = Flask(__name__)
# Don't trust X-Forwarded-Proto since we're handling HTTP locally and Cloudflare handles HTTPS
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=0, x_host=1, x_prefix=1)  # Changed x_proto=0

# Force HTTP scheme for URL generation
app.config['PREFERRED_URL_SCHEME'] = 'http'

app.jinja_env.add_extension('jinja2.ext.do')

# --- Basic Logging Configuration ---
# Configure a stream handler to output to console
stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.INFO)  # Log INFO level and above (includes WARNING, ERROR, CRITICAL)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
stream_handler.setFormatter(formatter)

# Add the handler to Flask's logger
app.logger.addHandler(stream_handler)
app.logger.setLevel(logging.INFO)

# Also configure the root logger for broader logging, e.g. from SQLAlchemy
logging.basicConfig(level=logging.INFO, handlers=[stream_handler])
# --- End Basic Logging Configuration ---

app.url_map.strict_slashes = False
CORS(app)

# Add request logging middleware
@app.before_request
def log_request_info():
    app.logger.info('=' * 80)
    app.logger.info(f'REQUEST: {request.method} {request.url}')
    app.logger.info(f'Headers: {dict(request.headers)}')
    app.logger.info(f'Remote Address: {request.remote_addr}')
    app.logger.info(f'Path: {request.path}')
    app.logger.info('=' * 80)

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", str(uuid.uuid4()))
basedir = os.path.abspath(os.path.dirname(__file__))
app.config["UPLOAD_FOLDER"] = "./app/static/uploads/"

app.config[
    "SQLALCHEMY_DATABASE_URI"
] = f"mysql+pymysql://root:{os.environ.get('MYSQL_ROOT_PASSWORD', '')}@mysql/edu?charset=utf8mb4"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SESSION_COOKIE_DOMAIN"] = False
app.config["JSON_SORT_KEYS"] = False

# Load super admins from environment variable (comma-separated email list)
super_admins_env = os.environ.get("SUPER_ADMINS", "")
app.config["SUPER_ADMINS"] = [email.strip() for email in super_admins_env.split(",") if email.strip()]

# Add the ProxyFix middleware if it's not already above this section
# from werkzeug.middleware.proxy_fix import ProxyFix 
# app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

db = SQLAlchemy(app)
Migrate(app, db)

# Add Jinja2 filter for converting newlines to <br> tags
@app.template_filter('nl2br')
def nl2br(value):
    """Convert newlines to <br> tags."""
    if value is None:
        return ""
    return value # I know this is not the best way to do it, but I don't want to break anything for now


# Add Jinja2 filter to strip HTML tags from strings
@app.template_filter('striptags')
def striptags(value):
    """Strip HTML tags from a string."""
    if value is None:
        return ""
    return re.sub(r'<[^>]*>', '', value)


@app.template_filter('truncate')
def truncate(s, length=255, end='...'):
    """Truncate a string to a certain length and append end characters."""
    if s is None:
        return ""
    if len(s) <= length:
        return s
    return s[:length] + end


app.logger.info("Flask app initialized and basic logging configured.")

mail_settings = {
    "MAIL_SERVER": os.environ.get("MAIL_SERVER", ""),
    "MAIL_PORT": os.environ.get("MAIL_PORT", 465),
    "MAIL_USE_TLS": False,
    "MAIL_USE_SSL": True,
    "MAIL_FROM": os.environ.get("MAIL_FROM", ""),
    "MAIL_USERNAME": os.environ.get("MAIL_USERNAME", ""),
    "MAIL_PASSWORD": os.environ.get("MAIL_PASSWORD", ""),
    "MAIL_DEBUG": False,
    "MAIL_SUPPRESS_SEND": False,
}
app.config.update(mail_settings)

mail = Mail(app)


@app.context_processor
def inject_env_variables():
    return dict(
        PROJECT_URL=os.environ.get("PROJECT_URL", "FILL_PROJECT_URL"),
        LIBRARY_URL=os.environ.get("LIBRARY_URL", "FILL_LIBRARY_URL"),
    )


@app.before_first_request
def create_tables():
    db.create_all()


# login config
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "public.login"
login_manager.login_message = "Přihlaste se prosím"
login_manager.login_message_category = "warning"


@login_manager.unauthorized_handler
def unauthorized_callback():
    """
    Handles unauthorized access attempts.
    For all requests, redirect to the login page.
    This ensures users always get redirected to the login page when not authenticated.
    """
    # Get the original path the user was trying to access
    original_path = request.path
    app.logger.info(f"Redirecting unauthenticated user to login page for path: {original_path}")
    
    # Instead of full URL which might include domain, just pass the path
    # This works better with the redirection logic in the login function
    return redirect(url_for('public.login', next=original_path))


# blueprints
from app.public.views import public
from app.admin.views import admin
from app.roleplay.views import roleplay


app.register_blueprint(public)
app.register_blueprint(admin, url_prefix="/admin")
app.register_blueprint(roleplay, url_prefix="/soutez")
"""
try:
    from app.super_admin.views import super_admin
    app.register_blueprint(super_admin, url_prefix="/super-admin")
except Exception as e:
    app.logger.error(f"Failed to register admin_panel blueprint: {e}")
    # Optionally, you can handle the error more gracefully or log it
"""

@app.errorhandler(404)
def resource_not_found(e):
    # try roborec.chat static files
    if "/static/uploads" in request.path:
        return redirect("https://roborec.chat" + request.path)
    return "404"

@app.errorhandler(403)
def access_forbidden(e):
    """Handle 403 Forbidden errors"""
    return '''
    <!DOCTYPE html>
    <html lang="cs">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Přístup zakázán - EDU AI Asistent</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
        <style>
            body {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                display: flex;
                align-items: center;
            }
            .error-container {
                background: white;
                border-radius: 1rem;
                box-shadow: 0 1rem 3rem rgba(0, 0, 0, 0.175);
                padding: 3rem;
                text-align: center;
                max-width: 500px;
                margin: 0 auto;
            }
            .error-icon {
                color: #dc3545;
                font-size: 4rem;
                margin-bottom: 1.5rem;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="error-container">
                <i class="fas fa-ban error-icon"></i>
                <h1 class="mb-3">Přístup zakázán</h1>
                <p class="text-muted mb-4">
                    Nemáte oprávnění pro přístup do administračního panelu. 
                    Pokud si myslíte, že jde o chybu, kontaktujte prosím správce systému.
                </p>
                <div class="d-grid gap-2 d-md-flex justify-content-md-center">
                    <a href="/" class="btn btn-primary">
                        <i class="fas fa-home me-2"></i>Domovská stránka
                    </a>
                    <a href="javascript:history.back()" class="btn btn-outline-secondary">
                        <i class="fas fa-arrow-left me-2"></i>Zpět
                    </a>
                </div>
            </div>
        </div>
    </body>
    </html>
    ''', 403