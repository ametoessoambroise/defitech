from flask import Flask
from markupsafe import Markup, escape
import json

import os
import logging
from datetime import datetime
from dotenv import load_dotenv
from app.extensions import (
    db,
    login_manager,
    mail,
    csrf,
    migrate,
    socketio,
    study_buddy_ai,
)
from app.services.defai_permissions import DEFAI_ALLOWED_ENDPOINTS
from app.sockets.videoconference import register_socketio_handlers

# Load environment variables from .env file
env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
load_dotenv(dotenv_path=env_path)

# Configure logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_app(config_class=None):
    app = Flask(__name__)

    # Load configuration
    # Assuming config is loaded from env vars or Config class.
    # For now, I'll copy some config setup from original app.py if needed,
    # but using a Config object is cleaner.
    # Since I don't have a config.py yet, I'll put basic config here or read from env.

    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-key")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
        "SQLALCHEMY_DATABASE_URI", "sqlite:///app.db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    app.config["WTF_CSRF_ENABLED"] = os.getenv("WTF_CSRF_ENABLED", "true").lower() in (
        "true",
        "1",
        "t",
    )
    app.config["WTF_CSRF_SECRET_KEY"] = os.getenv(
        "WTF_CSRF_SECRET_KEY", app.config["SECRET_KEY"]
    )

    app.config["MAIL_SERVER"] = os.getenv("MAIL_SERVER")
    app.config["MAIL_PORT"] = int(os.getenv("MAIL_PORT", 587))
    app.config["MAIL_USE_TLS"] = os.getenv("MAIL_USE_TLS", "true").lower() in (
        "true",
        "1",
        "t",
    )
    app.config["MAIL_USERNAME"] = os.getenv("MAIL_USERNAME")
    app.config["MAIL_PASSWORD"] = os.getenv("MAIL_PASSWORD")
    app.config["MAIL_DEFAULT_SENDER"] = os.getenv("MAIL_DEFAULT_SENDER")

    app.config["UPLOAD_FOLDER"] = os.path.join(app.root_path, "static", "uploads")

    # DefAI Config
    app.config["DEFAI_ENABLED"] = os.getenv("DEFAI_ENABLED", "true").lower() in (
        "true",
        "1",
        "t",
    )
    app.config["DEFAI_ACCESS_KEY"] = os.getenv("DEFAI_ACCESS_KEY", "defai-internal-key")
    app.config["DEFAI_ALLOWED_ENDPOINTS"] = DEFAI_ALLOWED_ENDPOINTS

    # Socket.IO Config
    app.config["SOCKET_IO_CSRF_PROTECTION"] = False

    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    mail.init_app(app)
    csrf.init_app(app)
    migrate.init_app(app, db)
    socketio.init_app(app, cookie=False, cors_allowed_origins="*")
    study_buddy_ai.init_app(app)

    # Initialize models
    from app.models import init_models

    init_models()

    login_manager.login_view = "auth.login"

    # Register Blueprints
    from app.routes.auth import auth_bp
    from app.routes.admin import admin_bp
    from app.routes.teachers import teachers_bp
    from app.routes.students import students_bp
    from app.routes.main import main_bp
    from app.routes.videoconference import bp as videoconference_bp
    from app.routes.study_buddy import study_buddy_bp
    from app.routes.notifications import notifications_bp

    from app.routes.role_endpoints import role_data_bp
    from app.routes.analytics import analytics_bp
    from app.routes.bug_reports import bug_reports as bug_report_bp
    from app.routes.career_craft import career_craft_bp
    from app.routes.chat import chat_bp
    from app.routes.community import community_bp
    from app.routes.profiles import profile_bp
    from app.routes.resources import resources_bp
    from app.routes.study_planner import study_planner_bp
    from app.routes.ai_assistant import ai_assistant_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(teachers_bp)
    app.register_blueprint(students_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(videoconference_bp)
    app.register_blueprint(study_buddy_bp)
    app.register_blueprint(role_data_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(bug_report_bp)
    app.register_blueprint(career_craft_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(community_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(resources_bp)
    app.register_blueprint(study_planner_bp)
    app.register_blueprint(ai_assistant_bp)
    app.register_blueprint(notifications_bp)

    # Register SocketIO handlers
    register_socketio_handlers(socketio)

    # Register SocketIO CSRF Middleware
    SocketIOCSRFMiddleware(app)

    @app.context_processor
    def inject_global_variables():
        try:
            from app.models.global_notification import GlobalNotification

            now = datetime.now()
            notifications = GlobalNotification.get_notifications_actives()
        except Exception:
            notifications = []
            now = datetime.now()

        return dict(
            global_notifications=notifications,
            global_notifications_date_now=now,
            get_global_notifications=(
                GlobalNotification.get_notifications_actives
                if "GlobalNotification" in globals() or "GlobalNotification" in locals()
                else lambda: []
            ),
            now=now,
        )

    @app.template_filter("nl2br")
    def nl2br_filter(value):
        """Convert newlines to <br/> and escape HTML."""
        if value is None:
            return ""
        text_val = str(value).replace("\r\n", "\n").replace("\r", "\n")
        escaped = escape(text_val)
        return Markup(escaped.replace("\n", "<br/>"))

    @app.template_filter("from_json")
    @app.template_filter("loads")
    def from_json_filter(value):
        """Convert JSON string to Python object."""
        if not value:
            return []
        try:
            if isinstance(value, str):
                return json.loads(value)
            return value
        except (json.JSONDecodeError, TypeError):
            return []

    # Initialize AI Generator
    import app.services.ai_image_generator as ai_gen

    model_path = os.path.join(
        os.path.dirname(app.root_path), "ImageSearch", "data", "image_model.h5"
    )
    encoder_path = os.path.join(
        os.path.dirname(app.root_path), "ImageSearch", "data", "label_encoder.pkl"
    )
    app.ai_generator = ai_gen.AIImageGenerator(model_path, encoder_path)

    return app


class SocketIOCSRFMiddleware:
    def __init__(self, app):
        self.app = app
        self.init_app(app)

    def init_app(self, app):
        app.before_request(self.disable_csrf_for_socketio)

    def disable_csrf_for_socketio(self):
        from flask import request, g

        if (
            request.path.startswith("/socket.io/")
            or request.path.startswith("/socket.io")
            or "socket.io" in request.path
        ):
            g.csrf_exempt = True
            return None

        user_agent = request.headers.get("User-Agent", "").lower()
        if (
            "socket.io" in user_agent
            or "engineering" in user_agent
            or request.headers.get("X-Socket-IO")
        ):
            g.csrf_exempt = True
