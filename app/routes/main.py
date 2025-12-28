from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    jsonify,
    request,
)
from flask_login import login_required, current_user
from app.extensions import db
from app.models.suggestion import Suggestion, SuggestionVote
from app.models.notification import Notification
from app.models.user import User
from app.email_utils import send_email
import secrets
import logging

main_bp = Blueprint("main", __name__)
logger = logging.getLogger(__name__)


@main_bp.route("/")
def index():
    """
    Page d'accueil (Landing Page).
    Si l'utilisateur est déjà connecté, on pourrait lui proposer un bouton vers son dashboard dans le template.
    """
    return render_template("index.html")


@main_bp.route("/confidentialite")
def confidentialite():
    """Page de politique de confidentialité."""
    return render_template("confidentialite.html")


@main_bp.route("/mentions-legales")
def mentions_legales():
    """Page des mentions légales."""
    return render_template("mentions_legales.html")


@main_bp.route("/roadmap")
def roadmap():
    """Page de la roadmap du projet."""
    return render_template("roadmap.html")


@main_bp.route("/image-search")
@login_required
def image_search():
    """Point d'entrée pour la recherche d'images par IA."""
    return render_template("image_search/index.html")


@main_bp.route("/defAI")
@login_required
def defAI_page():
    """
    Renvoie la page "defAI" si l'utilisateur est connecté et a un rôle valide.
    """
    user_role = None
    if current_user.role == "etudiant":
        user_role = "etudiant"
    elif current_user.role == "enseignant":
        user_role = "enseignant"
    elif current_user.role == "admin":
        user_role = "admin"

    if not user_role:
        flash("Accès non autorisé. Rôle utilisateur non reconnu.", "error")
        return redirect(url_for("main.index"))

    return render_template("chat/defAI.html", user_role=user_role)


@main_bp.route("/defAI/chat")
@login_required
def defAI_chat():
    """
    Redirige vers l'API du chat avec l'assistant IA.
    """
    try:
        return redirect(url_for("ai_assistant.chat"))
    except Exception as e:
        logger.error("Erreur lors de la redirection vers l'API du chat : {}".format(e))


@main_bp.route("/health")
def health_check():
    """
    Vérification de l'état de l'application (pour Render/Koyeb).
    """
    try:
        # Vérifier la connexion BDD
        db.session.execute(db.text("SELECT 1"))
        return jsonify({"status": "healthy", "database": "connected"}), 200
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 500


@main_bp.app_errorhandler(404)
def page_not_found(e):
    return render_template("errors/404.html"), 404


@main_bp.app_errorhandler(500)
def internal_server_error(e):
    return render_template("errors/500.html"), 500


@main_bp.route("/offline")
def offline():
    """
    Gère les erreurs de connectivité et rend le template offline.html
    """
    return render_template("offline.html"), 503


@main_bp.route("/suggestions")
def suggestions():
    """
    Page publique de la boîte à suggestions
    """
    suggestions_list = (
        Suggestion.query.filter_by(statut="ouverte")
        .order_by(Suggestion.date_creation.desc())
        .all()
    )

    suggestions_data = []
    for suggestion in suggestions_list:
        suggestions_data.append(
            {"suggestion": suggestion, "reponses": suggestion.reponses}
        )

    return render_template("suggestions.html", suggestions_data=suggestions_data)


@main_bp.route("/suggestions", methods=["POST"])
def submit_suggestion():
    """
    Soumission d'une nouvelle suggestion
    """
    contenu = request.form.get("contenu", "").strip()
    auteur_anonyme = request.form.get("auteur_anonyme", "").strip()
    email_contact = request.form.get("email_contact", "").strip()

    if not contenu:
        flash("Le contenu de la suggestion ne peut pas être vide.", "error")
        return redirect(url_for("main.suggestions"))

    if len(contenu) < 10:
        flash("La suggestion doit contenir au moins 10 caractères.", "error")
        return redirect(url_for("main.suggestions"))

    if len(contenu) > 1000:
        flash("La suggestion ne peut pas dépasser 1000 caractères.", "error")
        return redirect(url_for("main.suggestions"))

    suggestion = Suggestion(
        contenu=contenu,
        auteur_anonyme=auteur_anonyme if auteur_anonyme else None,
        email_contact=email_contact if email_contact else None,
        statut="ouverte",
    )

    db.session.add(suggestion)
    db.session.commit()

    try:
        admins = User.query.filter_by(role="admin").all()
        for admin in admins:
            notif = Notification(
                user_id=admin.id,
                message=f"Nouvelle suggestion soumise : {contenu[:50]}{'...' if len(contenu) > 50 else ''}",
                type="info",
            )
            db.session.add(notif)

            try:
                send_email(
                    to=admin.email,
                    subject="Nouvelle suggestion - DEFITECH",
                    template_name="suggestion_notification",
                    admin=admin,
                    suggestion=suggestion,
                )
            except Exception as e:
                print(f"Erreur lors de l'envoi de l'email : {e}")

        db.session.commit()
    except Exception as e:
        print(f"Erreur lors de la notification : {e}")

    flash("Votre suggestion a été soumise avec succès !", "success")
    return redirect(url_for("main.suggestions"))


@main_bp.route("/suggestions/vote", methods=["POST"])
def vote_suggestion():
    """
    Vote sur une suggestion (Oui/Non)
    """
    suggestion_id = request.form.get("suggestion_id", type=int)
    vote_type = request.form.get("vote_type")  # 'oui' ou 'non'

    if not suggestion_id or vote_type not in ["oui", "non"]:
        flash("Données de vote invalides.", "error")
        return redirect(url_for("main.suggestions"))

    suggestion = Suggestion.query.get_or_404(suggestion_id)

    user_id = current_user.id if current_user.is_authenticated else None
    session_id = request.cookies.get("suggestion_session_id")

    response = redirect(url_for("main.suggestions"))

    if not session_id:
        session_id = secrets.token_urlsafe(32)
        response.set_cookie(
            "suggestion_session_id", session_id, max_age=365 * 24 * 60 * 60
        )

    if suggestion.has_user_voted(user_id=user_id, session_id=session_id):
        flash("Vous avez déjà voté sur cette suggestion.", "warning")
        return response

    vote = SuggestionVote(
        suggestion_id=suggestion_id,
        user_id=user_id,
        session_id=session_id if not user_id else None,
        type_vote=vote_type,
    )

    db.session.add(vote)
    db.session.commit()

    action_text = "approuvé" if vote_type == "oui" else "rejeté"
    flash(f"Vous avez {action_text} cette suggestion.", "success")
    return response
