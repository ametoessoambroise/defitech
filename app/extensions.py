from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail
from flask_wtf.csrf import CSRFProtect
from flask_migrate import Migrate
from flask_socketio import SocketIO
import os

# Initialize extensions

db = SQLAlchemy()

login_manager = LoginManager()

mail = Mail()

csrf = CSRFProtect()

migrate = Migrate()

socketio = SocketIO(cors_allowed_origins="*")

# Configure login manager
login_manager.login_view = (
    "auth.login"  # Changed to auth.login as it will be in a blueprint
)
login_manager.login_message_category = "info"


# Initialize StudyBuddy AI
class StudyBuddyAIWrapper:
    """Wrapper pour initialiser StudyBuddyAI avec la configuration de l'application"""

    def __init__(self, app=None):
        self.study_buddy_ai = None
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        """Initialise StudyBuddyAI avec la configuration de l'application"""
        try:
            from app.ai.study_buddy_ai import StudyBuddyAI

            gemini_api_key = os.getenv("GEMINI_API_KEY")
            if not gemini_api_key:
                app.logger.warning(
                    "GEMINI_API_KEY non configuré. StudyBuddyAI ne fonctionnera pas correctement."
                )

            model = os.getenv(
                "GEMINI_MODEL", "gemini-2.0-flash"
            )  # Updated model default just in case
            self.study_buddy_ai = StudyBuddyAI(api_key=gemini_api_key, model=model)

            # Ajouter l'instance à l'application
            app.study_buddy_ai = self.study_buddy_ai

            return self.study_buddy_ai
        except ImportError:
            app.logger.error(
                "Module ai.study_buddy_ai manquant. StudyBuddyAI désactivé."
            )
            self.study_buddy_ai = None
            app.study_buddy_ai = None
            return None


# Créer une instance du wrapper
study_buddy_ai = StudyBuddyAIWrapper()


@login_manager.user_loader
def load_user(user_id):
    """
    Charge de charger un utilisateur par son ID.
    """
    try:
        from app.models.user import User

        return db.session.get(User, int(user_id))
    except Exception:
        return None
