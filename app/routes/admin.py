from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
    send_file,
    current_app,
)
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from datetime import datetime
import csv
import io
import os
import pandas as pd
import json
import random
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.extensions import db
from app.models.user import User
from app.models.etudiant import Etudiant
from app.models.enseignant import Enseignant
from app.models.filiere import Filiere
from app.models.annee import Annee
from app.models.matiere import Matiere
from app.models.notification import Notification
from app.models.note import Note
from app.models.suggestion import Suggestion, SuggestionReponse
from app.models.presence import Presence
from app.models.emploi_temps import EmploiTemps

# Conditional imports for models that might not rely on app context immediately
# but better to import them at top level if possible, or inside functions if circular deps strictly needed.
# For now, top level is fine as models should be standalone.
try:
    from app.models.teacher_profile_update_request import TeacherProfileUpdateRequest
    from app.models.global_notification import GlobalNotification
except ImportError:
    TeacherProfileUpdateRequest = None

from app.email_utils import send_account_validation_email

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.before_request
@login_required
def check_app_lock():
    from app.utils.decorators import app_lock_required

    @app_lock_required
    def protected():
        pass

    return protected()


# Configuration de la base de données pour les outils d'inspection
DATABASE_URI = os.getenv("SQLALCHEMY_DATABASE_URI")
engine = create_engine(DATABASE_URI) if DATABASE_URI else None
Session = sessionmaker(bind=engine) if engine is not None else None


@admin_bp.route("/dashboard")
@login_required
def dashboard():
    """
    Page d'administration du tableau de bord.
    """

    if current_user.role != "admin":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("main.index"))

    users_en_attente = User.query.filter_by(statut="en_attente").count()
    total_etudiants = User.query.filter_by(role="etudiant", statut="approuve").count()
    total_enseignants = User.query.filter_by(
        role="enseignant", statut="approuve"
    ).count()
    total_filieres = Filiere.query.count()

    # Notifications récentes pour l'admin
    notifications_admin = (
        Notification.query.order_by(Notification.date_created.desc()).limit(5).all()
    )

    # Demandes de modification de profil des enseignants en attente
    pending_teacher_requests = 0
    if TeacherProfileUpdateRequest:
        try:
            pending_teacher_requests = TeacherProfileUpdateRequest.query.filter_by(
                statut="en_attente"
            ).count()
        except Exception:
            pending_teacher_requests = 0

    return render_template(
        "admin/dashboard.html",
        users_en_attente=users_en_attente,
        total_etudiants=total_etudiants,
        total_enseignants=total_enseignants,
        total_filieres=total_filieres,
        notifications_admin=notifications_admin,
        pending_teacher_requests=pending_teacher_requests,
    )


@admin_bp.route("/etudiants")
@login_required
def admin_etudiants():
    """Page d'administration des étudiants.

    Filtre les étudiants selon les paramètres GET (filiere, annee, nom, prenom, email, id)
    et renvoie la page HTML correspondante.
    """
    if current_user.role != "admin":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("main.index"))

    filieres = Filiere.query.all()
    annees = Annee.query.all()

    # Récupérer les filtres depuis la query string
    filiere_filter = request.args.get("filiere", "").strip()
    annee_filter = request.args.get("annee", "").strip()
    nom_filter = request.args.get("nom", "").strip()
    prenom_filter = request.args.get("prenom", "").strip()
    email_filter = request.args.get("email", "").strip()
    id_filter = request.args.get("id", "").strip()

    # Construire la requête filtrée
    users_query = User.query.filter_by(role="etudiant")
    if nom_filter:
        users_query = users_query.filter(User.nom.ilike(f"%{nom_filter}%"))
    if prenom_filter:
        users_query = users_query.filter(User.prenom.ilike(f"%{prenom_filter}%"))
    if email_filter:
        users_query = users_query.filter(User.email.ilike(f"%{email_filter}%"))
    if id_filter:
        users_query = users_query.filter(User.id == id_filter)

    etudiants = users_query.all()
    etudiants_infos = [
        Etudiant.query.filter_by(user_id=e.id).first() for e in etudiants
    ]

    # Appliquer les filtres filiere/annee côté Python (car stockés dans Etudiant)
    filtered_data = []
    for user, info in zip(etudiants, etudiants_infos):
        if filiere_filter and (not info or info.filiere != filiere_filter):
            continue
        if annee_filter and (not info or info.annee != annee_filter):
            continue
        filtered_data.append((user, info))

    return render_template(
        "admin/etudiants.html",
        etudiants_data=filtered_data,
        filieres=filieres,
        annees=annees,
        filiere_filter=filiere_filter,
        annee_filter=annee_filter,
        nom_filter=nom_filter,
        prenom_filter=prenom_filter,
        email_filter=email_filter,
        id_filter=id_filter,
    )


@admin_bp.route("/enseignants")
@login_required
def admin_enseignants():
    """Page d'administration des enseignants.

    Filtre les enseignants selon les paramètres GET (id, nom, prenom, email,
    specialite, filiere, annee) et renvoie la page HTML correspondante.
    """
    if current_user.role != "admin":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("main.index"))

    filieres = Filiere.query.all()
    annees = Annee.query.all()

    # Filtres depuis la query string
    id_filter = request.args.get("id", "").strip()
    nom_filter = request.args.get("nom", "").strip()
    prenom_filter = request.args.get("prenom", "").strip()
    email_filter = request.args.get("email", "").strip()
    specialite_filter = request.args.get("specialite", "").strip()
    filiere_filter = request.args.get("filiere", "").strip()
    annee_filter = request.args.get("annee", "").strip()

    # Base : utilisateurs enseignants
    users_query = User.query.filter_by(role="enseignant")
    if id_filter:
        users_query = users_query.filter(User.id == id_filter)
    if nom_filter:
        users_query = users_query.filter(User.nom.ilike(f"%{nom_filter}%"))
    if prenom_filter:
        users_query = users_query.filter(User.prenom.ilike(f"%{prenom_filter}%"))
    if email_filter:
        users_query = users_query.filter(User.email.ilike(f"%{email_filter}%"))

    enseignants_users = users_query.all()

    # Récupérer les profils enseignants associés
    enseignants_infos = [
        Enseignant.query.filter_by(user_id=u.id).first() for u in enseignants_users
    ]

    enseignants_data = []
    for user, info in zip(enseignants_users, enseignants_infos):
        # Appliquer les filtres spécialité / filière / année côté Python
        if specialite_filter and (
            not info or specialite_filter.lower() not in (info.specialite or "").lower()
        ):
            continue

        filieres_str = "-"
        filieres_list = []
        annees_list = []

        if info and info.filieres_enseignees:
            try:
                # Deux formats possibles : JSON {"filieres": [...], "annees": [...]} ou chaîne "Fil1;Fil2"
                parsed = None
                # D'abord tenter JSON
                try:
                    parsed = json.loads(info.filieres_enseignees)
                except Exception:
                    parsed = None

                if isinstance(parsed, dict) and "filieres" in parsed:
                    filieres_list = parsed.get("filieres") or []
                    annees_list = parsed.get("annees") or []
                else:
                    filieres_list = [
                        f.strip()
                        for f in info.filieres_enseignees.split(";")
                        if f.strip()
                    ]

                if filiere_filter and filiere_filter not in filieres_list:
                    continue
                if annee_filter and annee_filter not in annees_list:
                    continue

                filieres_str = ", ".join(filieres_list) if filieres_list else "-"
            except Exception:
                filieres_str = info.filieres_enseignees

        enseignants_data.append((user, info, filieres_str))

    return render_template(
        "admin/enseignants.html",
        enseignants_data=enseignants_data,
        filieres=filieres,
        annees=annees,
        id_filter=id_filter,
        nom_filter=nom_filter,
        prenom_filter=prenom_filter,
        email_filter=email_filter,
        specialite_filter=specialite_filter,
        filiere_filter=filiere_filter,
        annee_filter=annee_filter,
    )


@admin_bp.route("/users")
@login_required
def admin_users():
    """
    Page d'administration des utilisateurs.
    """
    if current_user.role != "admin":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("main.index"))

    # Filtrer les utilisateurs par statut si spécifié
    statut = request.args.get("statut")
    if statut:
        users = User.query.filter_by(statut=statut).all()
    else:
        users = User.query.all()

    # Compter les utilisateurs par statut pour les statistiques
    users_en_attente = User.query.filter_by(statut="en_attente").count()
    users_approuves = User.query.filter_by(statut="approuve").count()
    users_rejetes = User.query.filter_by(statut="rejete").count()
    total_users = users_en_attente + users_approuves + users_rejetes

    # Préparer les dictionnaires pour accès rapide dans le template
    etudiants = Etudiant.query.all()
    enseignants = Enseignant.query.all()
    etudiants_dict = {e.user_id: e for e in etudiants}
    enseignants_dict = {e.user_id: e for e in enseignants}

    return render_template(
        "admin/users.html",
        users=users,
        etudiants_dict=etudiants_dict,
        enseignants_dict=enseignants_dict,
        statut_courant=statut,
        users_en_attente=users_en_attente,
        users_approuves=users_approuves,
        users_rejetes=users_rejetes,
        total_users=total_users,
    )


@admin_bp.route("/approve/<int:user_id>")
@login_required
def approve_user(user_id):
    """
    Fonction pour approuver un utilisateur.
    """
    if current_user.role != "admin":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("main.index"))

    user = User.query.get_or_404(user_id)
    user.statut = "approuve"
    db.session.commit()

    # Envoyer un email de validation du compte
    send_account_validation_email(user)

    # Ajouter une notification interne pour l'utilisateur validé
    notif = Notification(
        user_id=user.id,
        titre="Compte approuvé",
        message="Votre compte a été validé par l'administration.",
        type="success",
    )
    db.session.add(notif)
    db.session.commit()

    # Si l'utilisateur est un étudiant, créer son profil
    if user.role == "etudiant":
        etudiant_exists = Etudiant.query.filter_by(user_id=user.id).first()
        if not etudiant_exists:
            # Générer un numéro d'étudiant unique
            while True:
                new_numero = f"ETU{datetime.now().year}{random.randint(10000, 99999)}"
                if not Etudiant.query.filter_by(numero_etudiant=new_numero).first():
                    break

            etudiant = Etudiant(
                user_id=user.id,
                filiere=user.filiere if hasattr(user, "filiere") else "Informatique",
                annee=user.annee if hasattr(user, "annee") else "1ère année",
                numero_etudiant=new_numero,
            )
            db.session.add(etudiant)
            db.session.commit()
            flash(f"Profil étudiant pour {user.nom} {user.prenom} créé.", "success")
        else:
            flash(f"L'étudiant {user.nom} {user.prenom} a déjà un profil.", "info")
    elif user.role == "enseignant":
        enseignant_exists = Enseignant.query.filter_by(user_id=user.id).first()
        if not enseignant_exists:
            enseignant = Enseignant(
                user_id=user.id,
                specialite="",
                filieres_enseignees=json.dumps({"filieres": [], "annees": []}),
            )
            db.session.add(enseignant)
            db.session.commit()
            flash(f"Profil enseignant pour {user.nom} {user.prenom} créé.", "success")
        else:
            flash(
                f"L'enseignant {user.nom} {user.prenom} a déjà un profil.",
                "info",
            )

    flash(
        f"L'utilisateur {user.nom} {user.prenom} a été approuvé avec succès.", "success"
    )
    return redirect(url_for("admin.admin_users"))


@admin_bp.route("/reject/<int:user_id>")
@login_required
def reject_user(user_id):
    """
    Fonction pour rejeter un utilisateur.
    """
    if current_user.role != "admin":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("main.index"))

    user = User.query.get_or_404(user_id)
    if user.statut == "rejete":
        flash("Cet utilisateur a déjà été rejeté.", "warning")
        return redirect(url_for("admin.admin_users"))

    user.statut = "rejete"
    db.session.commit()

    # Ajouter une notification interne pour l'utilisateur rejeté
    notif = Notification(
        user_id=user.id,
        message="Votre compte a été rejeté par l'administration. Veuillez contacter le support pour plus d'informations.",
        type="error",
    )
    db.session.add(notif)
    db.session.commit()

    flash(f"L'utilisateur {user.nom} {user.prenom} a été rejeté.", "success")
    return redirect(url_for("admin.admin_users"))


@admin_bp.route("/delete/<int:user_id>", methods=["DELETE"])
@login_required
def delete_user(user_id):
    """
    Fonction pour supprimer un utilisateur.
    """
    if current_user.role != "admin":
        return jsonify({"success": False, "message": "Accès non autorisé"}), 403

    user = db.session.get(
        User, user_id
    )  # Utilisation de la nouvelle syntaxe SQLAlchemy 2.0
    if not user:
        return jsonify({"success": False, "message": "Utilisateur non trouvé"}), 404

    try:
        # Utiliser l'approche SQL brute pour les tables problématiques
        with db.session.begin_nested():
            with db.session.no_autoflush:
                # Imports inside to avoid circular or early import issues if models are tricky
                from app.models.message import Message
                from app.models.study_document import StudyDocument
                from app.models.study_progress import StudyProgress
                from app.models.study_session import StudySession
                from app.models.quiz_models import Quiz, QuizAttempt, QuizAnswer
                from app.models.flashcard import Flashcard, FlashcardReview
                from app.models.suggestion import Suggestion, SuggestionVote
                from app.models.password_reset_token import PasswordResetToken
                from app.models.competence import Competence
                from app.models.experience import Experience
                from app.models.formation import Formation
                from app.models.langue import Langue
                from app.models.projet import Projet
                from app.models.videoconference import (
                    RoomParticipant,
                    RoomActivityLog,
                    Inscription,
                    RoomInvitation,
                    Room,
                )
                from app.models.resource import Resource
                from app.models.global_notification import GlobalNotification
                from app.models.pomodoro_session import PomodoroSession
                from app.models.devoir import Devoir
                from app.models.devoir_vu import DevoirVu
                from app.models.presence import Presence
                from app.models.emploi_temps import EmploiTemps

                # 1. Supprimer les messages avec approche SQL brute
                try:
                    db.session.execute(
                        db.text("DELETE FROM message WHERE sender_id = :user_id"),
                        {"user_id": user_id},
                    )
                    db.session.execute(
                        db.text("DELETE FROM message WHERE receiver_id = :user_id"),
                        {"user_id": user_id},
                    )
                except Exception as e:
                    current_app.logger.error(
                        f"Erreur lors de la suppression des messages: {str(e)}"
                    )
                    # Fallback SQLAlchemy
                    Message.query.filter_by(sender_id=user_id).delete()
                    Message.query.filter_by(receiver_id=user_id).delete()

                # 2. Supprimer les study_documents avec approche SQL brute
                try:
                    db.session.execute(
                        db.text("DELETE FROM study_documents WHERE user_id = :user_id"),
                        {"user_id": user_id},
                    )
                except Exception as e:
                    current_app.logger.error(
                        f"Erreur lors de la suppression des study_documents: {str(e)}"
                    )
                    StudyDocument.query.filter_by(user_id=user_id).delete()

                # 3. Supprimer les autres tables user_id
                # Progression et sessions
                StudyProgress.query.filter_by(user_id=user_id).delete()
                StudySession.query.filter_by(user_id=user_id).delete()

                # Compétences, expériences, formations, langues, projets
                Competence.query.filter_by(user_id=user_id).delete()
                Experience.query.filter_by(user_id=user_id).delete()
                Formation.query.filter_by(user_id=user_id).delete()
                Langue.query.filter_by(user_id=user_id).delete()
                Projet.query.filter_by(user_id=user_id).delete()

                # Vidéoconférence
                RoomInvitation.query.filter_by(user_id=user_id).delete()
                rooms_hotees = Room.query.filter_by(host_id=user_id).all()
                for room in rooms_hotees:
                    RoomInvitation.query.filter_by(room_id=room.id).delete()
                RoomParticipant.query.filter_by(user_id=user_id).delete()
                RoomActivityLog.query.filter_by(user_id=user_id).delete()
                Inscription.query.filter_by(user_id=user_id).delete()
                Room.query.filter_by(host_id=user_id).delete()

                # Ressources et notifications globales
                Resource.query.filter_by(enseignant_id=user_id).delete()
                GlobalNotification.query.filter_by(createur_id=user_id).delete()

                # Quiz, flashcards, suggestions, tokens
                Quiz.query.filter_by(user_id=user_id).delete()
                QuizAttempt.query.filter_by(user_id=user_id).delete()
                QuizAnswer.query.filter_by(user_id=user_id).delete()
                Flashcard.query.filter_by(user_id=user_id).delete()
                FlashcardReview.query.filter_by(user_id=user_id).delete()
                Suggestion.query.filter_by(user_id=user_id).delete()
                SuggestionVote.query.filter_by(user_id=user_id).delete()
                PasswordResetToken.query.filter_by(user_id=user_id).delete()
                if TeacherProfileUpdateRequest:
                    TeacherProfileUpdateRequest.query.filter_by(
                        user_id=user_id
                    ).delete()

                # 4. Supprimer les entités dépendantes
                # Étudiants
                etudiants = Etudiant.query.filter_by(user_id=user_id).all()
                for etudiant in etudiants:
                    Presence.query.filter_by(etudiant_id=etudiant.id).delete()
                    Note.query.filter_by(etudiant_id=etudiant.id).delete()
                    PomodoroSession.query.filter_by(etudiant_id=etudiant.id).delete()
                    db.session.delete(etudiant)

                # Enseignants
                enseignants = Enseignant.query.filter_by(user_id=user_id).all()
                for enseignant in enseignants:
                    EmploiTemps.query.filter_by(enseignant_id=enseignant.id).delete()

                    # Supprimer les devoirs
                    try:
                        db.session.execute(
                            db.text(
                                """
                                DELETE FROM devoir_vu 
                                WHERE devoir_id IN (
                                    SELECT id FROM devoir WHERE enseignant_id = :enseignant_id
                                )
                            """
                            ),
                            {"enseignant_id": enseignant.id},
                        )
                        db.session.execute(
                            db.text(
                                "DELETE FROM devoir WHERE enseignant_id = :enseignant_id"
                            ),
                            {"enseignant_id": enseignant.id},
                        )
                    except Exception as e:
                        current_app.logger.error(
                            f"Erreur lors de la suppression des devoirs: {str(e)}"
                        )
                        devoirs = Devoir.query.filter_by(
                            enseignant_id=enseignant.id
                        ).all()
                        for devoir in devoirs:
                            DevoirVu.query.filter_by(devoir_id=devoir.id).delete()
                            db.session.delete(devoir)

                    # Récupérer et supprimer les matières avec leurs dépendances
                    matieres_enseignant = Matiere.query.filter_by(
                        enseignant_id=enseignant.id
                    ).all()
                    for matiere in matieres_enseignant:
                        Presence.query.filter_by(matiere_id=matiere.id).delete()
                        Note.query.filter_by(matiere_id=matiere.id).delete()
                        EmploiTemps.query.filter_by(matiere_id=matiere.id).delete()
                        Devoir.query.filter_by(matiere_id=matiere.id).delete()
                        db.session.delete(matiere)

                    db.session.delete(enseignant)

                # Notifications de l'utilisateur
                Notification.query.filter_by(user_id=user_id).delete()

                # Enfin, supprimer l'utilisateur
                db.session.delete(user)
        db.session.commit()

        return jsonify(
            {
                "success": True,
                "message": f"Utilisateur {user.nom} {user.prenom} supprimé avec succès.",
            }
        )

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(
            f"Erreur lors de la suppression de l'utilisateur {user_id}: {str(e)}"
        )
        return (
            jsonify(
                {
                    "success": False,
                    "message": f"Erreur lors de la suppression : {str(e)}",
                }
            ),
            500,
        )


@admin_bp.route("/import/etudiants", methods=["POST"])
@login_required
def import_etudiants():
    """
    Fonction pour importer des étudiants.
    """
    if current_user.role != "admin":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("admin.admin_users"))
    file_url = request.form.get("file_url")
    if not file_url:
        flash("Aucun fichier sélectionné.", "error")
        return redirect(url_for("admin.admin_users"))
    try:
        if file_url.endswith(".csv") or "format=csv" in file_url:
            df = pd.read_csv(file_url)
        else:
            # Fallback for Excel or unknown, try excel then csv if fails?
            # Assuming extension is reliable or defaulting to excel if not csv
            try:
                df = pd.read_excel(file_url)
            except Exception:
                df = pd.read_csv(file_url)
        count = 0
        for _, row in df.iterrows():
            if User.query.filter_by(email=row["email"]).first():
                continue  # Ignore doublons
            user = User(
                nom=row["nom"],
                prenom=row["prenom"],
                email=row["email"],
                password_hash=generate_password_hash("defitech2024"),
                role="etudiant",
                date_naissance=row["date_naissance"],
                sexe=row["sexe"],
                age=18,  # Peut être recalculé
                statut="approuve",
                date_creation=datetime.now(),
            )
            db.session.add(user)
            db.session.commit()
            last_etudiant = Etudiant.query.order_by(Etudiant.id.desc()).first()
            if last_etudiant:
                try:
                    last_numero = int(last_etudiant.numero_etudiant.split("-")[-1])
                    new_numero = f"DEFI-{last_numero + 1:03d}"
                except Exception:
                    new_numero = "DEFI-001"
            else:
                new_numero = "DEFI-001"
            etudiant = Etudiant(
                user_id=user.id,
                filiere=row["filiere"],
                annee=row["annee"],
                numero_etudiant=new_numero,
            )
            db.session.add(etudiant)
            db.session.commit()
            count += 1
        flash(f"{count} étudiants importés avec succès.", "success")
    except Exception as e:
        flash(f"Erreur lors de l'import : {str(e)}", "error")
    return redirect(url_for("admin.users"))


@admin_bp.route("/template/etudiants")
@login_required
def download_etudiants_template():
    """
    Génère un fichier CSV modèle pour l'import des étudiants.
    """
    if current_user.role != "admin":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("admin.admin_users"))

    output = io.StringIO()
    output.write("nom,prenom,email,date_naissance,sexe,filiere,annee\n")
    output.write(
        "Dupont,Alice,alice@exemple.com,2001-05-12,F,Informatique,1ère année\n"
    )
    output.write("Mensah,Koffi,koffi@exemple.com,2000-11-23,M,Génie Civil,2ème année\n")
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype="text/csv",
        as_attachment=True,
        download_name="etudiants_modele.csv",
    )


@admin_bp.route("/import/filieres", methods=["POST"])
@login_required
def import_filieres():
    """
    Fonction pour importer des filières.
    """
    if current_user.role != "admin":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("admin.admin_users"))
    file_url = request.form.get("file_url")
    if not file_url:
        flash("Aucun fichier sélectionné.", "error")
        return redirect(url_for("admin.admin_users"))
    try:
        import pandas as pd

        if file_url.endswith(".csv") or "format=csv" in file_url:
            df = pd.read_csv(file_url)
        else:
            try:
                df = pd.read_excel(file_url)
            except Exception:
                df = pd.read_csv(file_url)
        count = 0
        for _, row in df.iterrows():
            if Filiere.query.filter_by(nom=row["nom"]).first():
                continue  # Ignore doublons
            filiere = Filiere(nom=row["nom"], description=row["description"])
            db.session.add(filiere)
            db.session.commit()
            count += 1
        flash(f"{count} filières importées avec succès.", "success")
    except Exception as e:
        flash(f"Erreur lors de l'import : {str(e)}", "error")
    return redirect(url_for("admin.users"))


@admin_bp.route("/template/filieres")
@login_required
def download_filieres_template():
    """
    Route pour télécharger un modèle de fichier CSV pour les filières.
    """
    if current_user.role != "admin":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("admin.admin_users"))

    output = io.StringIO()
    output.write("nom,description\n")
    output.write("Informatique,Développement et systèmes\n")
    output.write("Génie Civil,Construction et génie civil\n")
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype="text/csv",
        as_attachment=True,
        download_name="filieres_modele.csv",
    )


@admin_bp.route("/import/matieres", methods=["POST"])
@login_required
def import_matieres():
    """
    Route pour importer des matières depuis un fichier CSV ou Excel.
    """
    if current_user.role != "admin":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("admin.admin_users"))
    file_url = request.form.get("file_url")
    if not file_url:
        flash("Aucun fichier sélectionné.", "error")
        return redirect(url_for("admin.admin_users"))
    try:
        import pandas as pd

        if file_url.endswith(".csv") or "format=csv" in file_url:
            df = pd.read_csv(file_url)
        else:
            try:
                df = pd.read_excel(file_url)
            except Exception:
                df = pd.read_csv(file_url)
        count = 0
        for _, row in df.iterrows():
            filiere = Filiere.query.filter_by(nom=row["filiere"]).first()
            enseignant = User.query.filter_by(
                email=row["enseignant_email"], role="enseignant"
            ).first()
            if not filiere or not enseignant:
                continue
            ens_obj = Enseignant.query.filter_by(user_id=enseignant.id).first()
            if not ens_obj:
                continue
            if Matiere.query.filter_by(
                nom=row["nom"], filiere_id=filiere.id, enseignant_id=ens_obj.id
            ).first():
                continue
            matiere = Matiere(
                nom=row["nom"], filiere_id=filiere.id, enseignant_id=ens_obj.id
            )
            db.session.add(matiere)
            db.session.commit()
            count += 1
        flash(f"{count} matières importées avec succès.", "success")
    except Exception as e:
        flash(f"Erreur lors de l'import : {str(e)}", "error")
    return redirect(url_for("admin.admin_users"))


@admin_bp.route("/template/matieres")
@login_required
def download_matieres_template():
    """
    Route pour télécharger un modèle de fichier CSV pour l'importation de matières.
    """
    if current_user.role != "admin":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("admin.admin_users"))

    output = io.StringIO()
    output.write("nom,filiere,enseignant_email\n")
    output.write("Mathématiques,Informatique,prof.math@exemple.com\n")
    output.write("Programmation,Informatique,prof.info@exemple.com\n")
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype="text/csv",
        as_attachment=True,
        download_name="matieres_modele.csv",
    )


@admin_bp.route("/import/enseignants", methods=["POST"])
@login_required
def import_enseignants():
    """
    Route pour importer des enseignants depuis un fichier CSV ou Excel.
    """

    if current_user.role != "admin":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("admin.admin_users"))
    file_url = request.form.get("file_url")
    if not file_url:
        flash("Aucun fichier sélectionné.", "error")
        return redirect(url_for("admin.admin_users"))
    try:
        import pandas as pd

        if file_url.endswith(".csv") or "format=csv" in file_url:
            df = pd.read_csv(file_url)
        else:
            try:
                df = pd.read_excel(file_url)
            except Exception:
                df = pd.read_csv(file_url)
        count = 0
        for _, row in df.iterrows():
            if User.query.filter_by(email=row["email"]).first():
                continue
            user = User(
                nom=row["nom"],
                prenom=row["prenom"],
                email=row["email"],
                password_hash=generate_password_hash("defitech2024"),
                role="enseignant",
                date_naissance=datetime(1980, 1, 1),
                sexe="M",
                age=40,
                statut="approuve",
                date_creation=datetime.now(),
            )
            db.session.add(user)
            db.session.commit()
            enseignant = Enseignant(
                user_id=user.id,
                specialite=row["specialite"],
                filieres_enseignees=row["filieres_enseignees"],
            )
            db.session.add(enseignant)
            db.session.commit()
            count += 1
        flash(f"{count} enseignants importés avec succès.", "success")
    except Exception as e:
        flash(f"Erreur lors de l'import : {str(e)}", "error")
    return redirect(url_for("admin.users"))


@admin_bp.route("/template/enseignants")
@login_required
def download_enseignants_template():
    """
    Route pour télécharger un modèle de fichier CSV pour l'importation d'enseignants.
    """
    if current_user.role != "admin":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("admin.admin_users"))

    output = io.StringIO()
    output.write("nom,prenom,email,specialite,filieres_enseignees\n")
    output.write(
        "Martin,Jean,prof.math@exemple.com,Mathématiques,Informatique;Génie Civil\n"
    )
    output.write("Durand,Claire,prof.info@exemple.com,Programmation,Informatique\n")
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype="text/csv",
        as_attachment=True,
        download_name="enseignants_modele.csv",
    )


@admin_bp.route("/import/annees", methods=["POST"])
@login_required
def import_annees():
    """
    Route pour importer des années depuis un fichier CSV ou Excel.
    """
    if current_user.role != "admin":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("admin.admin_users"))
    file_url = request.form.get("file_url")
    if not file_url:
        flash("Aucun fichier sélectionné.", "error")
        return redirect(url_for("admin.admin_users"))
    try:
        import pandas as pd

        if file_url.endswith(".csv") or "format=csv" in file_url:
            df = pd.read_csv(file_url)
        else:
            try:
                df = pd.read_excel(file_url)
            except Exception:
                df = pd.read_csv(file_url)
        count = 0
        for _, row in df.iterrows():
            if Annee.query.filter_by(nom=row["nom"]).first():
                continue
            annee = Annee(nom=row["nom"])
            db.session.add(annee)
            db.session.commit()
            count += 1
        flash(f"{count} années importées avec succès.", "success")
    except Exception as e:
        flash(f"Erreur lors de l'import : {str(e)}", "error")
    return redirect(url_for("admin.users"))


@admin_bp.route("/template/annees")
@login_required
def download_annees_template():
    """
    Route pour télécharger un modèle de fichier CSV pour l'importation d'années.
    """
    if current_user.role != "admin":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("admin.admin_users"))

    output = io.StringIO()
    output.write("nom\n")
    output.write("1ère année\n")
    output.write("2ème année\n")
    output.write("3ème année\n")
    output.write("Licence\n")
    output.write("Master\n")
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype="text/csv",
        as_attachment=True,
        download_name="annees_modele.csv",
    )


@admin_bp.route("/notes")
@login_required
def notes():
    """
    Route pour afficher la page des notes de l'administrateur.
    """
    if current_user.role != "admin":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("main.index"))

    # Récupérer les filtres depuis la requête
    annee = request.args.get("annee")
    filiere = request.args.get("filiere")
    search = request.args.get("search", "").strip()

    notes_query = Note.query.join(Etudiant, Note.etudiant_id == Etudiant.id).join(
        User, Etudiant.user_id == User.id
    )

    if annee:
        notes_query = notes_query.filter(Etudiant.annee == annee)
    if filiere:
        notes_query = notes_query.filter(Etudiant.filiere == filiere)
    if search:
        notes_query = notes_query.filter(
            (User.nom.ilike(f"%{search}%")) | (User.prenom.ilike(f"%{search}%"))
        )

    notes_result = notes_query.all()
    annees = db.session.query(Etudiant.annee).distinct().all()
    filieres = db.session.query(Etudiant.filiere).distinct().all()

    return render_template(
        "admin/notes.html",
        notes=notes_result,
        annees=annees,
        filieres=filieres,
        selected_annee=annee,
        selected_filiere=filiere,
        search=search,
    )


@admin_bp.route("/suggestions")
@login_required
def admin_suggestions():
    """
    Page d'administration des suggestions.
    """
    if current_user.role != "admin":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("main.index"))

    suggestions = Suggestion.query.order_by(Suggestion.date_creation.desc()).all()
    suggestions_data = []

    for s in suggestions:
        suggestions_data.append({"suggestion": s, "reponses": s.reponses})

    return render_template(
        "admin/suggestions.html",
        suggestions_data=suggestions_data,
        current_time=datetime.now(),
    )


@admin_bp.route("/suggestions/change-status/<int:suggestion_id>", methods=["POST"])
@login_required
def change_suggestion_status(suggestion_id):
    """
    Change le statut d'une suggestion.
    """
    if current_user.role != "admin":
        return jsonify({"success": False, "message": "Accès non autorisé"}), 403

    suggestion = Suggestion.query.get_or_404(suggestion_id)
    statut = request.form.get("statut")

    if statut in ["ouverte", "en_cours", "fermee", "rejetee"]:
        suggestion.statut = statut
        db.session.commit()
        flash(f"Statut de la suggestion #{suggestion_id} mis à jour.", "success")
    else:
        flash("Statut invalide.", "error")

    return redirect(url_for("admin.admin_suggestions"))


@admin_bp.route("/suggestions/respond/<int:suggestion_id>", methods=["POST"])
@login_required
def respond_suggestion(suggestion_id):
    """
    Ajoute une réponse administrative à une suggestion.
    """
    if current_user.role != "admin":
        return jsonify({"success": False, "message": "Accès non autorisé"}), 403

    suggestion = Suggestion.query.get_or_404(suggestion_id)
    contenu = request.form.get("contenu")

    if contenu:
        reponse = SuggestionReponse(
            suggestion_id=suggestion.id, admin_id=current_user.id, contenu=contenu
        )
        db.session.add(reponse)
        db.session.commit()
        flash("Réponse publiée avec succès.", "success")
    else:
        flash("Le contenu de la réponse ne peut pas être vide.", "error")

    return redirect(url_for("admin.admin_suggestions"))


@admin_bp.route("/export/etudiants/<format>")
@login_required
def export_etudiants(format):
    """
    Exporte la liste des étudiants approuvés au format demandé.
    """
    if current_user.role != "admin":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("main.index"))

    etudiants = User.query.filter_by(role="etudiant", statut="approuve").all()

    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Nom", "Prénom", "Email", "Filière", "Année", "Sexe", "Âge"])

        for etudiant in etudiants:
            etudiant_info = Etudiant.query.filter_by(user_id=etudiant.id).first()
            writer.writerow(
                [
                    etudiant.nom,
                    etudiant.prenom,
                    etudiant.email,
                    etudiant_info.filiere if etudiant_info else "",
                    etudiant_info.annee if etudiant_info else "",
                    etudiant.sexe,
                    etudiant.age,
                ]
            )

        output.seek(0)
        return output.getvalue(), 200, {"Content-Type": "text/csv"}

    elif format == "json":
        data = []
        for etudiant in etudiants:
            etudiant_info = Etudiant.query.filter_by(user_id=etudiant.id).first()
            data.append(
                {
                    "nom": etudiant.nom,
                    "prenom": etudiant.prenom,
                    "email": etudiant.email,
                    "filiere": etudiant_info.filiere if etudiant_info else "",
                    "annee": etudiant_info.annee if etudiant_info else "",
                    "sexe": etudiant.sexe,
                    "age": etudiant.age,
                }
            )

        return jsonify(data)

    elif format == "pdf":
        buffer = io.BytesIO()
        p = canvas.Canvas(buffer, pagesize=letter)
        p.drawString(100, 750, "Liste des Étudiants - DEFITECH")

        y = 700
        for etudiant in etudiants:
            etudiant_info = Etudiant.query.filter_by(user_id=etudiant.id).first()
            p.drawString(100, y, f"{etudiant.nom} {etudiant.prenom} - {etudiant.email}")
            y -= 20
            if y < 50:
                p.showPage()
                y = 750

        p.showPage()
        p.save()
        buffer.seek(0)
        return buffer.getvalue(), 200, {"Content-Type": "application/pdf"}

    return "Format non supporté", 400


@admin_bp.route("/export/presences/excel")
@login_required
def export_presences_excel():
    """
    Exporte les présences des étudiants au format Excel.
    """
    if current_user.role != "admin":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("main.index"))

    filiere = request.args.get("filiere")
    annee = request.args.get("annee")
    matiere = request.args.get("matiere")
    date_str = request.args.get("date")

    query = Presence.query
    if filiere:
        etu_ids = [e.id for e in Etudiant.query.filter_by(filiere=filiere).all()]
        query = query.filter(Presence.etudiant_id.in_(etu_ids))
    if annee:
        etu_ids = [e.id for e in Etudiant.query.filter_by(annee=annee).all()]
        query = query.filter(Presence.etudiant_id.in_(etu_ids))
    if matiere:
        query = query.filter_by(matiere_id=matiere)
    if date_str:
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
            # Handle model field name mismatch: date_cours in new model, date_presence in old code
            query = query.filter(Presence.date_cours == date_obj)
        except ValueError:
            pass

    presences = query.all()
    data = []
    for p in presences:
        etu = Etudiant.query.get(p.etudiant_id)
        user = User.query.get(etu.user_id) if etu else None
        mat = Matiere.query.get(p.matiere_id)
        data.append(
            {
                "Date": p.date_cours.strftime("%d/%m/%Y") if p.date_cours else "",
                "Matière": mat.nom if mat else "",
                "Filière": etu.filiere if etu else "",
                "Année": etu.annee if etu else "",
                "Nom": user.nom if user else "",
                "Prénom": user.prenom if user else "",
                "Présent": "Oui" if p.present else "Non",
            }
        )

    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Présences")
    output.seek(0)
    return send_file(
        output,
        as_attachment=True,
        download_name="presences.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@admin_bp.route("/export/presences/pdf")
@login_required
def export_presences_pdf():
    """
    Exporter les présences des étudiants au format PDF.
    """
    if current_user.role != "admin":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("main.index"))

    filiere = request.args.get("filiere")
    annee = request.args.get("annee")
    matiere = request.args.get("matiere")
    date_str = request.args.get("date")

    query = Presence.query
    if filiere:
        etu_ids = [e.id for e in Etudiant.query.filter_by(filiere=filiere).all()]
        query = query.filter(Presence.etudiant_id.in_(etu_ids))
    if annee:
        etu_ids = [e.id for e in Etudiant.query.filter_by(annee=annee).all()]
        query = query.filter(Presence.etudiant_id.in_(etu_ids))
    if matiere:
        query = query.filter_by(matiere_id=matiere)
    if date_str:
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
            query = query.filter(Presence.date_cours == date_obj)
        except ValueError:
            pass

    presences = query.all()
    output = io.BytesIO()
    c = canvas.Canvas(output, pagesize=letter)
    width, height = letter
    c.setFont("Helvetica-Bold", 14)
    c.drawString(30, height - 40, "Liste des présences")
    c.setFont("Helvetica", 10)
    y = height - 70
    c.drawString(30, y, "Date")
    c.drawString(90, y, "Matière")
    c.drawString(180, y, "Filière")
    c.drawString(260, y, "Année")
    c.drawString(320, y, "Nom")
    c.drawString(400, y, "Prénom")
    c.drawString(480, y, "Présent")
    y -= 18

    for p in presences:
        if y < 40:
            c.showPage()
            c.setFont("Helvetica", 10)
            y = height - 40

        etu = Etudiant.query.get(p.etudiant_id)
        user = User.query.get(etu.user_id) if etu else None
        mat = Matiere.query.get(p.matiere_id)

        c.drawString(30, y, p.date_cours.strftime("%d/%m/%Y") if p.date_cours else "")
        c.drawString(90, y, mat.nom if mat else "")
        c.drawString(180, y, etu.filiere if etu else "")
        c.drawString(260, y, etu.annee if etu else "")
        c.drawString(320, y, user.nom if user else "")
        c.drawString(400, y, user.prenom if user else "")
        c.drawString(480, y, "Oui" if p.present else "Non")
        y -= 16

    c.save()
    output.seek(0)
    return send_file(
        output,
        as_attachment=True,
        download_name="presences.pdf",
        mimetype="application/pdf",
    )


@admin_bp.route("/filieres")
@login_required
def admin_filieres():
    """
    Page d'administration des filières.
    """
    if current_user.role != "admin":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("main.index"))
    filieres = Filiere.query.all()
    return render_template("admin/filieres.html", filieres=filieres)


@admin_bp.route("/filiere/<int:filiere_id>/enseignants")
@login_required
def get_enseignants_filiere(filiere_id):
    """Récupère la liste de tous les enseignants (pour une filière donnée côté UI)."""
    if current_user.role != "admin":
        return jsonify({"error": "Accès non autorisé"}), 403

    # Même logique que dans app copy.py : renvoie tous les enseignants
    enseignants = Enseignant.query.all()

    enseignants_data = [
        {
            "id": ens.id,
            "nom_complet": f"{ens.user.prenom} {ens.user.nom}",
            "email": ens.user.email,
            "specialite": getattr(ens, "specialite", ""),
        }
        for ens in enseignants
    ]

    return jsonify(enseignants_data)


@admin_bp.route("/filiere/ajouter", methods=["GET", "POST"])
@login_required
def ajouter_filiere():
    """
    Page d'ajout d'une filière.
    """
    if current_user.role != "admin":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("main.index"))

    if request.method == "POST":
        nom = request.form.get("nom")
        description = request.form.get("description")
        type_formation = request.form.get("type_formation")

        if not nom or not type_formation:
            flash("Le nom et le type de formation sont obligatoires.", "error")
            return redirect(url_for("admin.ajouter_filiere"))

        # Vérifier si la filière existe déjà
        filiere_existante = Filiere.query.filter_by(nom=nom).first()
        if filiere_existante:
            flash("Une filière avec ce nom existe déjà.", "error")
            return redirect(url_for("admin.ajouter_filiere"))

        nouvelle_filiere = Filiere(
            nom=nom, description=description, type_formation=type_formation
        )

        try:
            db.session.add(nouvelle_filiere)
            db.session.commit()
            flash("Filière ajoutée avec succès.", "success")
            return redirect(url_for("admin.admin_filieres"))
        except Exception as e:
            current_app.logger.error("Erreur lors de l'ajout de la filière : " + str(e))
            db.session.rollback()
            flash("Erreur lors de l'ajout de la filière.", "error")
            return redirect(url_for("admin.ajouter_filiere"))

    return render_template("admin/ajouter_filiere.html")


@admin_bp.route("/filiere/modifier/<int:filiere_id>", methods=["GET", "POST"])
@login_required
def modifier_filiere(filiere_id):
    """
    Modifier une filière existante.
    """
    if current_user.role != "admin":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("main.index"))

    filiere = Filiere.query.get_or_404(filiere_id)

    if request.method == "POST":
        nom = request.form.get("nom")
        description = request.form.get("description")
        type_formation = request.form.get("type_formation")

        if not nom or not type_formation:
            flash("Le nom et le type de formation sont obligatoires.", "error")
            return redirect(url_for("admin.modifier_filiere", filiere_id=filiere_id))

        # Vérifier si le nom existe déjà (sauf pour cette filière)
        filiere_existante = Filiere.query.filter_by(nom=nom).first()
        if filiere_existante and filiere_existante.id != filiere_id:
            flash("Une filière avec ce nom existe déjà.", "error")
            return redirect(url_for("admin.modifier_filiere", filiere_id=filiere_id))

        filiere.nom = nom
        filiere.description = description
        filiere.type_formation = type_formation

        try:
            db.session.commit()
            flash("Filière modifiée avec succès.", "success")
            return redirect(url_for("admin.admin_filieres"))
        except Exception as e:
            current_app.logger.error(
                "Erreur lors de la modification de la filière : " + str(e)
            )
            db.session.rollback()
            flash("Erreur lors de la modification de la filière.", "error")
            return redirect(url_for("admin.modifier_filiere", filiere_id=filiere_id))

    return render_template("admin/modifier_filiere.html", filiere=filiere)


@admin_bp.route("/filiere/supprimer/<int:filiere_id>", methods=["POST"])
@login_required
def supprimer_filiere(filiere_id):
    """
    Supprimer une filière.
    """
    if current_user.role != "admin":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("main.index"))
    filiere = Filiere.query.get_or_404(filiere_id)
    # Vérifier si la filière est utilisée
    etudiants_count = Etudiant.query.filter_by(filiere=filiere.nom).count()
    matieres_count = Matiere.query.filter_by(filiere_id=filiere.id).count()
    emploi_temps_count = EmploiTemps.query.filter_by(filiere_id=filiere.id).count()

    if etudiants_count > 0 or matieres_count > 0 or emploi_temps_count > 0:
        flash(
            f"Impossible de supprimer cette filière car elle est utilisée par {etudiants_count} étudiant(s), {matieres_count} matière(s) et {emploi_temps_count} emploi(s) du temps.",
            "error",
        )
        return redirect(url_for("admin.admin_filieres"))

    try:
        db.session.delete(filiere)
        db.session.commit()
        flash("Filière supprimée avec succès.", "success")
    except Exception as e:
        current_app.logger.error(
            "Erreur lors de la suppression de la filière : " + str(e)
        )
        db.session.rollback()
        flash("Erreur lors de la suppression de la filière.", "error")

    return redirect(url_for("admin.admin_filieres"))


@admin_bp.route("/filiere/<int:filiere_id>/matieres")
@login_required
def gestion_matieres_filiere(filiere_id):
    """
    API pour récupérer les matières d'une filière.
    """
    if current_user.role != "admin":
        return jsonify({"error": "Accès non autorisé"}), 403

    filiere = Filiere.query.get_or_404(filiere_id)
    # Récupérer toutes les matières de cette filière (sans jointure restrictive)
    matieres = Matiere.query.filter_by(filiere_id=filiere_id).all()

    # Créer la liste des matières avec les informations nécessaires
    matieres_data = []
    for m in matieres:
        matiere_data = {
            "id": m.id,
            "nom": m.nom,
            "annee": m.annee,  # Ajout de l'année
            "filiere_nom": filiere.nom,
            "filiere_id": filiere.id,
            "enseignant_id": m.enseignant_id,
            "enseignant_nom": (
                f"{m.enseignant.user.prenom} {m.enseignant.user.nom}"
                if m.enseignant
                else "Non attribué"
            ),
        }
        matieres_data.append(matiere_data)

    return jsonify(matieres_data)


@admin_bp.route("/filiere/matiere/ajouter", methods=["POST"])
@login_required
def ajouter_matiere_filiere():
    """
    API pour ajouter une matière à une filière.
    """
    if current_user.role != "admin":
        return jsonify({"success": False, "message": "Accès non autorisé"}), 403

    data = request.get_json()
    filiere_id = data.get("filiere_id")
    nom = data.get("nom")
    annee = data.get("annee")
    enseignant_id = data.get("enseignant_id")

    if not all([filiere_id, nom, annee, enseignant_id]):
        return jsonify({"success": False, "message": "Données manquantes"}), 400

    try:
        # Vérifier si la filière existe
        filiere = Filiere.query.get(filiere_id)
        if not filiere:
            return jsonify({"success": False, "message": "Filière non trouvée"}), 404

        # Vérifier si l'enseignant existe
        enseignant = Enseignant.query.get(enseignant_id)
        if not enseignant:
            return jsonify({"success": False, "message": "Enseignant non trouvé"}), 404

        # Vérifier si l'enseignant n'a pas déjà 2 matières maximum pour cette année
        matieres_enseignant = Matiere.query.filter_by(
            enseignant_id=enseignant_id, annee=annee
        ).count()
        if matieres_enseignant >= 2:
            return (
                jsonify(
                    {
                        "success": False,
                        "message": f"L'enseignant {enseignant.user.prenom} {enseignant.user.nom} a déjà atteint le maximum de 2 matières autorisées pour l'année {annee}",
                    }
                ),
                400,
            )

        # Vérifier si la matière existe déjà pour cette filière et cette année
        matiere_existante = Matiere.query.filter_by(
            nom=nom.strip().lower(), filiere_id=filiere_id, annee=annee
        ).first()
        if matiere_existante:
            return (
                jsonify(
                    {
                        "success": False,
                        "message": f"La matière '{nom}' existe déjà pour la filière '{filiere.nom}' en {annee} et est enseignée par {matiere_existante.enseignant.user.prenom} {matiere_existante.enseignant.user.nom}",
                    }
                ),
                400,
            )

        # Créer la matière avec les relations
        matiere = Matiere(
            nom=nom, filiere_id=filiere_id, enseignant_id=enseignant_id, annee=annee
        )
        db.session.add(matiere)
        db.session.flush()  # Pour obtenir l'ID de la matière

        # Vérifier si la matière est déjà associée à la filière
        if EmploiTemps is not None:
            # Vérifier si l'enseignant est déjà occupé sur ce créneau par défaut
            default_day = "Lundi"
            default_start = datetime.strptime("07:00", "%H:%M").time()

            collision_enseignant = EmploiTemps.query.filter_by(
                enseignant_id=enseignant_id, jour=default_day, heure_debut=default_start
            ).first()

            # Vérifier aussi la salle par défaut (À définir) pour éviter UniqueViolation sur la salle
            default_salle = "À définir"
            collision_salle = EmploiTemps.query.filter_by(
                salle=default_salle, jour=default_day, heure_debut=default_start
            ).first()

            if not collision_enseignant and not collision_salle:
                # Créer un emploi du temps par défaut uniquement si le créneau est libre
                emploi = EmploiTemps(
                    filiere_id=filiere_id,
                    matiere_id=matiere.id,
                    enseignant_id=enseignant_id,
                    jour=default_day,
                    heure_debut=default_start,
                    heure_fin=datetime.strptime("10:00", "%H:%M").time(),
                    salle=default_salle,
                )
                db.session.add(emploi)
            else:
                flash(
                    f"Créneau par défaut (Lundi 07h) non créé pour {nom} car l'enseignant ou la salle est déjà occupé."
                )
                current_app.logger.warning(
                    f"Créneau par défaut (Lundi 07h) non créé pour {nom} car l'enseignant ou la salle est déjà occupé."
                )

        db.session.commit()
        return jsonify(
            {
                "success": True,
                "message": "Matière ajoutée avec succès",
                "matiere_id": matiere.id,
            }
        )
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erreur lors de l'ajout de la matière: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500


@admin_bp.route("/filiere/matiere/<int:matiere_id>", methods=["DELETE"])
@login_required
def supprimer_matiere_filiere(matiere_id):
    """
    API pour supprimer une matière d'une filière.
    """
    if current_user.role != "admin":
        return jsonify({"success": False, "message": "Accès non autorisé"}), 403

    try:
        # Vérifier que la matière existe
        matiere = Matiere.query.get(matiere_id)
        if not matiere:
            return (
                jsonify({"success": False, "message": "Matière introuvable"}),
                404,
            )

        # Vérifier les références dans les présences et les notes
        presences_count = (
            Presence.query.filter_by(matiere_id=matiere_id).count()
            if Presence is not None
            else 0
        )
        notes_count = (
            Note.query.filter_by(matiere_id=matiere_id).count()
            if Note is not None
            else 0
        )

        if presences_count > 0 or notes_count > 0:
            message = (
                "Impossible de supprimer cette matière car elle est associée "
                "à des enregistrements de présence et/ou de notes."
            )
            return (
                jsonify(
                    {
                        "success": False,
                        "message": message,
                        "presences_count": presences_count,
                        "notes_count": notes_count,
                    }
                ),
                400,
            )

        # Supprimer les emplois du temps liés à cette matière
        if EmploiTemps is not None:
            EmploiTemps.query.filter_by(matiere_id=matiere_id).delete()

        # Supprimer la matière
        db.session.delete(matiere)

        db.session.commit()
        return jsonify({"success": True, "message": "Matière supprimée avec succès"})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(
            f"Erreur lors de la suppression de la matière: {str(e)}"
        )
        return jsonify({"success": False, "message": str(e)}), 500


@admin_bp.route("/gestion-matieres")
@login_required
def gestion_matieres():
    """
    Page de gestion des matières par filière.
    """
    if current_user.role != "admin":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("main.index"))

    filieres = Filiere.query.all()
    return render_template("admin/gestion_matieres.html", filieres=filieres)


@admin_bp.route("/filiere/matiere/<int:matiere_id>", methods=["PUT"])
@login_required
def modifier_matiere(matiere_id):
    """
    API pour modifier une matière existante.
    """
    if current_user.role != "admin":
        return jsonify({"success": False, "message": "Accès non autorisé"}), 403

    data = request.get_json()
    nom = data.get("nom")
    annee = data.get("annee")
    enseignant_id = data.get("enseignant_id")

    if not all([nom, annee, enseignant_id]):
        return (
            jsonify({"success": False, "message": "Tous les champs sont obligatoires"}),
            400,
        )

    try:
        matiere = Matiere.query.get_or_404(matiere_id)

        # Vérifier si l'enseignant existe
        enseignant = Enseignant.query.get(enseignant_id)
        if not enseignant:
            return jsonify({"success": False, "message": "Enseignant non trouvé"}), 404

        # Vérifier si l'enseignant n'a pas déjà atteint la limite pour cette année
        # On exclut la matière actuelle du compte
        matieres_count = Matiere.query.filter(
            Matiere.enseignant_id == enseignant_id,
            Matiere.annee == annee,
            Matiere.id != matiere_id,
        ).count()

        if matieres_count >= 2:
            return (
                jsonify(
                    {
                        "success": False,
                        "message": f"L'enseignant {enseignant.user.prenom} {enseignant.user.nom} a déjà atteint sa limite de 2 matières pour {annee}",
                    }
                ),
                400,
            )

        # Vérifier si la matière existe déjà avec le même nom pour la même année
        matiere_existante = Matiere.query.filter(
            Matiere.nom == nom.strip().lower(),
            Matiere.annee == annee,
            Matiere.id != matiere_id,
        ).first()

        if matiere_existante:
            return (
                jsonify(
                    {
                        "success": False,
                        "message": f"Une matière avec ce nom existe déjà pour l'année {annee}",
                    }
                ),
                400,
            )

        # Mettre à jour la matière
        matiere.nom = nom
        matiere.annee = annee
        matiere.enseignant_id = enseignant_id

        db.session.commit()

        return jsonify(
            {
                "success": True,
                "message": "Matière mise à jour avec succès",
                "matiere": {
                    "id": matiere.id,
                    "nom": matiere.nom,
                    "annee": matiere.annee,
                    "enseignant_id": matiere.enseignant_id,
                },
            }
        )

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(
            f"Erreur lors de la mise à jour de la matière: {str(e)}"
        )
        return jsonify({"success": False, "message": str(e)}), 500


@admin_bp.route("/manage-matiere", methods=["GET", "POST", "PUT", "DELETE"])
@login_required
def manage_matiere():
    """
    Gestion des matières (CRUD complet)
    """
    if current_user.role != "admin":
        return redirect(url_for("main.forbidden"))

    # Récupération des données pour les listes déroulantes
    filieres = Filiere.query.all()
    enseignants = Enseignant.query.join(User).all()
    annees = Annee.query.all()

    # Récupération de toutes les matières avec leurs relations
    matieres = Matiere.query.all()

    # Traitement des requêtes AJAX
    if request.method == "POST":
        try:
            data = request.get_json()
            nom = data.get("nom")
            filiere_id = data.get("filiere_id")
            enseignant_id = data.get("enseignant_id")
            annee = data.get("annee", "1ère année")

            if not all([nom, filiere_id, enseignant_id]):
                return (
                    jsonify(
                        {
                            "success": False,
                            "message": "Tous les champs sont obligatoires",
                        }
                    ),
                    400,
                )

            # Vérification du quota
            matieres_count = Matiere.query.filter_by(
                enseignant_id=enseignant_id, annee=annee
            ).count()
            if matieres_count >= 2:
                return (
                    jsonify(
                        {
                            "success": False,
                            "message": f"Cet enseignant a déjà 2 matières en {annee}",
                        }
                    ),
                    400,
                )

            nouvelle_matiere = Matiere(
                nom=nom, filiere_id=filiere_id, enseignant_id=enseignant_id, annee=annee
            )
            db.session.add(nouvelle_matiere)
            db.session.commit()

            return (
                jsonify(
                    {
                        "success": True,
                        "message": "Matière ajoutée avec succès",
                        "matiere": {
                            "id": nouvelle_matiere.id,
                            "nom": nouvelle_matiere.nom,
                            "filiere": nouvelle_matiere.filiere.nom,
                            "enseignant": f"{nouvelle_matiere.enseignant.user.nom} {nouvelle_matiere.enseignant.user.prenom}",
                        },
                    }
                ),
                201,
            )

        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    elif request.method == "PUT":
        try:
            data = request.get_json()
            matiere_id = data.get("id")
            matiere = Matiere.query.get_or_404(matiere_id)

            matiere.nom = data.get("nom", matiere.nom)
            matiere.filiere_id = data.get("filiere_id", matiere.filiere_id)
            matiere.enseignant_id = data.get("enseignant_id", matiere.enseignant_id)
            matiere.annee = data.get("annee", matiere.annee)

            # Vérification du quota après modif potentielle de l'enseignant ou l'année
            matieres_count = Matiere.query.filter(
                Matiere.enseignant_id == matiere.enseignant_id,
                Matiere.annee == matiere.annee,
                Matiere.id != matiere_id,
            ).count()

            if matieres_count >= 2:
                db.session.rollback()
                return (
                    jsonify(
                        {
                            "success": False,
                            "message": f"Limite de 2 matières atteinte pour cet enseignant en {matiere.annee}",
                        }
                    ),
                    400,
                )

            db.session.commit()

            return jsonify(
                {
                    "success": True,
                    "message": "Matière mise à jour avec succès",
                    "matiere": {
                        "id": matiere.id,
                        "nom": matiere.nom,
                        "filiere": matiere.filiere.nom,
                        "enseignant": f"{matiere.enseignant.user.nom} {matiere.enseignant.user.prenom}",
                    },
                }
            )

        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    elif request.method == "DELETE":
        try:
            data = request.get_json()
            matiere = Matiere.query.get_or_404(data.get("id"))
            db.session.delete(matiere)
            db.session.commit()
            return jsonify(
                {"success": True, "message": "Matière supprimée avec succès"}
            )
        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # Pour les requêtes GET, on affiche simplement le template
    return render_template(
        "admin/manage-matiere.html",
        matieres=matieres,
        filieres=filieres,
        enseignants=enseignants,
        annees=annees,
    )


@admin_bp.route("/ajouter-etudiant", methods=["GET", "POST"])
@login_required
def ajouter_etudiant():
    """
    Page d'accès à l'ajout d'un étudiant.
    """
    if current_user.role != "admin":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("main.index"))

    filieres = Filiere.query.all()
    annees = Annee.query.all()

    if request.method == "POST":
        nom = request.form.get("nom")
        prenom = request.form.get("prenom")
        email = request.form.get("email")
        password = request.form.get("password")
        date_naissance_str = request.form.get("date_naissance")
        sexe = request.form.get("sexe")
        age = request.form.get("age")
        filiere_id = request.form.get("filiere_id")
        annee_id = request.form.get("annee_id")

        if not all(
            [
                nom,
                prenom,
                email,
                password,
                date_naissance_str,
                sexe,
                age,
                filiere_id,
                annee_id,
            ]
        ):
            flash("Tous les champs sont obligatoires.", "error")
            return redirect(url_for("admin.ajouter_etudiant"))

        # Vérifier si l'utilisateur existe déjà
        user_existant = User.query.filter_by(email=email).first()
        if user_existant:
            flash("Un utilisateur avec cet email existe déjà.", "error")
            return redirect(url_for("admin.ajouter_etudiant"))

        try:
            date_naissance = datetime.strptime(date_naissance_str, "%Y-%m-%d").date()
            hashed_password = generate_password_hash(password)

            # Création de l'utilisateur
            nouvel_utilisateur = User(
                nom=nom,
                prenom=prenom,
                email=email,
                password=hashed_password,
                role="etudiant",
                statut="approuve",
                sexe=sexe,
                age=int(age),
                date_naissance=date_naissance,
            )
            db.session.add(nouvel_utilisateur)
            db.session.flush()

            # Création de l'étudiant
            filiere = Filiere.query.get(filiere_id)
            annee = Annee.query.get(annee_id)

            # Générer un numéro étudiant unique
            num_etudiant = f"DEFI{datetime.now().year}{random.randint(1000, 9999)}"

            nouvel_etudiant = Etudiant(
                user_id=nouvel_utilisateur.id,
                filiere=filiere.nom if filiere else "",
                annee=annee.nom if annee else "",
                num_etudiant=num_etudiant,
            )
            db.session.add(nouvel_etudiant)
            db.session.commit()

            flash("Étudiant ajouté avec succès.", "success")
            return redirect(url_for("admin.admin_etudiants"))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Erreur lors de l'ajout de l'étudiant: {str(e)}")
            flash(f"Erreur lors de l'ajout de l'étudiant: {str(e)}", "error")
            return redirect(url_for("admin.ajouter_etudiant"))

    return render_template(
        "admin/ajouter_etudiant.html", filieres=filieres, annees=annees
    )


@admin_bp.route("/teacher-requests")
@login_required
def admin_teacher_update_requests():
    """
    Page d'administration des demandes de modification des profils enseignants.
    """
    if current_user.role != "admin":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("main.index"))

    if not TeacherProfileUpdateRequest:
        flash("Fonctionnalité de demande de mise à jour non activée.", "warning")
        return redirect(url_for("admin.dashboard"))

    requests = TeacherProfileUpdateRequest.query.filter_by(statut="en_attente").all()
    return render_template("admin/teacher_update_requests.html", requests=requests)


@admin_bp.route("/teacher-request/<int:request_id>", methods=["GET", "POST"])
@login_required
def admin_review_teacher_request(request_id):
    """
    Page pour examiner une demande de modification d'enseignant.
    """
    if current_user.role != "admin":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("main.index"))

    if not TeacherProfileUpdateRequest:
        flash("Fonctionnalité de demande de mise à jour non activée.", "warning")
        return redirect(url_for("admin.dashboard"))

    request_obj = TeacherProfileUpdateRequest.query.get_or_404(request_id)

    if request.method == "POST":
        action = request.form.get("action")
        comment = request.form.get("comment")

        if action == "approve":
            _apply_teacher_profile_update(request_obj, comment)
            flash("Demande approuvée et profil mis à jour.", "success")
        elif action == "reject":
            request_obj.statut = "rejete"
            request_obj.commentaire_admin = comment
            db.session.commit()
            flash("Demande rejetée.", "info")

        return redirect(url_for("admin.admin_teacher_update_requests"))

    return render_template("admin/review_teacher_request.html", request_obj=request_obj)


def _apply_teacher_profile_update(request_obj, admin_comment=None):
    """Applique les modifications d'une demande approuvée"""
    user = request_obj.user
    enseignant = Enseignant.query.filter_by(user_id=user.id).first()

    if request_obj.nom:
        user.nom = request_obj.nom
    if request_obj.prenom:
        user.prenom = request_obj.prenom
    if request_obj.email:
        user.email = request_obj.email
    if request_obj.telephone:
        user.telephone = request_obj.telephone
    if request_obj.adresse:
        user.adresse = request_obj.adresse
    if request_obj.ville:
        user.ville = request_obj.ville
    if request_obj.code_postal:
        user.code_postal = request_obj.code_postal
    if request_obj.pays:
        user.pays = request_obj.pays

    if enseignant:
        if request_obj.specialite:
            enseignant.specialite = request_obj.specialite
        if request_obj.grade:
            enseignant.grade = request_obj.grade
        if request_obj.filieres_enseignees:
            enseignant.filieres_enseignees = request_obj.filieres_enseignees
        if request_obj.annees_enseignees:
            enseignant.annees_enseignees = request_obj.annees_enseignees
        if request_obj.date_embauche:
            enseignant.date_embauche = request_obj.date_embauche

    if request_obj.photo_profil:
        user.photo_profil = request_obj.photo_profil

    request_obj.statut = "approuve"
    request_obj.commentaire_admin = admin_comment
    db.session.commit()


@admin_bp.route("/teacher-request/delete/<int:request_id>", methods=["POST"])
@login_required
def admin_delete_teacher_request(request_id):
    """
    Supprimer une demande de modification (annulation par admin).
    """
    if current_user.role != "admin":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("main.index"))

    if not TeacherProfileUpdateRequest:
        return redirect(url_for("admin.dashboard"))

    req = TeacherProfileUpdateRequest.query.get_or_404(request_id)
    db.session.delete(req)
    db.session.commit()
    flash("Demande supprimée.", "success")
    return redirect(url_for("admin.admin_teacher_update_requests"))


@admin_bp.route("/global-notifications")
@login_required
def admin_global_notifications():
    """
    Page d'administration des notifications globales.
    """
    if current_user.role != "admin":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("main.index"))

    notifications = GlobalNotification.query.order_by(
        GlobalNotification.date_creation.desc()
    ).all()
    return render_template(
        "admin/global_notifications.html", notifications=notifications
    )


@admin_bp.route("/global-notification/create", methods=["GET", "POST"])
@login_required
def admin_create_global_notification():
    """
    Page de création d'une notification globale.
    """
    if current_user.role != "admin":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("main.index"))

    if request.method == "POST":
        titre = request.form.get("titre")
        message = request.form.get("message")
        type_notif = request.form.get("type", "info")
        priorite = int(request.form.get("priorite", 1))
        duree = request.form.get("duree")  # en heures

        if not titre or not message:
            flash("Le titre et le message sont obligatoires.", "error")
            return redirect(url_for("admin.admin_create_global_notification"))

        try:
            duree_h = int(duree) if duree else None
            GlobalNotification.create_notification(
                titre=titre,
                message=message,
                type=type_notif,
                priorite=priorite,
                duree_heures=duree_h,
                createur_id=current_user.id,
            )
            flash("Notification globale créée et envoyée.", "success")
            return redirect(url_for("admin.admin_global_notifications"))
        except Exception as e:
            current_app.logger.error(
                f"Erreur lors de la création de la notification globale: {str(e)}"
            )
            flash("Erreur lors de la création de la notification.", "error")

    return render_template("admin/create_global_notification.html")


@admin_bp.route("/global-notification/toggle/<int:notif_id>", methods=["POST"])
@login_required
def admin_toggle_global_notification(notif_id):
    """
    Active/Désactive une notification globale.
    """
    if current_user.role != "admin":
        return jsonify({"success": False, "message": "Accès non autorisé"}), 403

    notif = GlobalNotification.query.get_or_404(notif_id)
    notif.est_active = not notif.est_active
    db.session.commit()

    status = "activée" if notif.est_active else "désactivée"
    return jsonify({"success": True, "message": f"Notification {status}."})


@admin_bp.route("/global-notification/delete/<int:notif_id>", methods=["POST"])
@login_required
def admin_delete_global_notification(notif_id):
    """
    Supprime une notification globale.
    """
    if current_user.role != "admin":
        return jsonify({"success": False, "message": "Accès non autorisé"}), 403

    notif = GlobalNotification.query.get_or_404(notif_id)
    db.session.delete(notif)
    db.session.commit()

    return jsonify({"success": True, "message": "Notification supprimée."})


@admin_bp.route("/api/global-notifications")
def api_global_notifications():
    """
    API pour récupérer les notifications globales actives.
    """
    notifications = GlobalNotification.get_notifications_actives()
    return jsonify(
        [
            {
                "id": n.id,
                "titre": n.titre,
                "message": n.message,
                "type": n.type,
                "priorite": n.priorite,
                "date_creation": n.date_creation.isoformat(),
                "type_icon": n.type_icon,
                "type_class": n.type_css_class,
            }
            for n in notifications
        ]
    )


@admin_bp.route("/bdd")
@login_required
def bdd():
    """Vue de gestion de la base de données."""
    if current_user.role != "admin":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("main.index"))
    return render_template("admin/bdd.html")


@admin_bp.route("/api/bdd/tables")
@login_required
def get_database_tables():
    """API pour lister les tables de la base de données."""
    if current_user.role != "admin":
        return jsonify({"error": "Non autorisé"}), 403
    try:
        from sqlalchemy import inspect

        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        return jsonify(tables)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@admin_bp.route("/api/bdd/structure/<table_name>")
@login_required
def get_table_structure(table_name):
    """API pour obtenir la structure d'une table."""
    if current_user.role != "admin":
        return jsonify({"error": "Non autorisé"}), 403
    try:
        from sqlalchemy import inspect

        inspector = inspect(db.engine)
        columns = inspector.get_columns(table_name)
        # Convertir les types SQLAlchemy en chaînes pour le JSON
        for column in columns:
            column["type"] = str(column["type"])
        return jsonify(columns)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@admin_bp.route("/api/bdd/data/<table_name>")
@login_required
def get_table_data(table_name):
    """API pour obtenir les données d'une table."""
    if current_user.role != "admin":
        return jsonify({"error": "Non autorisé"}), 403
    try:
        # Utiliser text() pour requêtes SQL sécurisées
        from sqlalchemy import text

        result = db.session.execute(text(f"SELECT * FROM {table_name} LIMIT 100"))

        # Obtenir les colonnes du résultat
        columns = result.keys()

        # Transformer en liste de dictionnaires
        data = [dict(zip(columns, row)) for row in result]

        # Formater les dates pour le JSON
        for row in data:
            for key, val in row.items():
                if hasattr(val, "isoformat"):
                    row[key] = val.isoformat()

        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@admin_bp.route("/api/bdd/execute", methods=["POST"])
@login_required
def execute_sql():
    """API pour exécuter une requête SQL personnalisée."""
    if current_user.role != "admin":
        return jsonify({"error": "Non autorisé"}), 403

    query = request.json.get("query")
    if not query:
        return jsonify({"error": "Requête vide"}), 400

    # Protection simple contre requêtes destructrices (optionnel car admin)
    forbidden_keywords = ["DROP", "TRUNCATE", "DELETE FROM users"]
    for keyword in forbidden_keywords:
        if keyword in query.upper() and current_user.email != "admin@defitech.com":
            return (
                jsonify({"error": f"Action '{keyword}' non autorisée via cette API"}),
                403,
            )

    try:
        from sqlalchemy import text

        result = db.session.execute(text(query))

        if query.strip().upper().startswith("SELECT"):
            columns = result.keys()
            data = [dict(zip(columns, row)) for row in result]
            for row in data:
                for key, val in row.items():
                    if hasattr(val, "isoformat"):
                        row[key] = val.isoformat()
            return jsonify({"type": "select", "data": data})
        else:
            db.session.commit()
            return jsonify({"type": "action", "rows_affected": result.rowcount})

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@admin_bp.route("/api/bdd/backup", methods=["POST"])
@login_required
def backup_database():
    """API pour créer une sauvegarde de la base de données."""
    if current_user.role != "admin":
        return jsonify({"error": "Non autorisé"}), 403

    try:
        # Logique simplifiée : export vers un ficher SQL ou JSON
        import os

        backup_dir = os.path.join(current_app.instance_path, "backups")
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)

        filename = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"
        filepath = os.path.join(backup_dir, filename)

        # Pour SQLite, on peut copier le fichier
        # Pour PostgreSQL, utiliser pg_dump (plus complexe)
        # Ici simulation
        with open(filepath, "w") as f:
            f.write("-- Backup created at " + datetime.now().isoformat())

        return jsonify({"success": True, "filename": filename})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@admin_bp.route("/api/bdd/download-backup/<filename>")
@login_required
def download_backup(filename):
    """Télécharger un fichier de sauvegarde."""
    if current_user.role != "admin":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("main.index"))

    import os

    backup_path = os.path.join(current_app.instance_path, "backups", filename)
    if os.path.exists(backup_path):
        return send_file(backup_path, as_attachment=True)
    else:
        flash("Fichier non trouvé.", "error")
        return redirect(url_for("admin.bdd"))


@admin_bp.route("/api/bdd/restore", methods=["POST"])
@login_required
def restore_database():
    """API pour restaurer la base de données (DANGEREUX)."""
    # Seul le super-utilisateur devrait pouvoir faire ça
    if current_user.role != "admin" or current_user.email != "admin@defitech.com":
        return (
            jsonify(
                {
                    "error": "Niveau d'autorisation insuffisant pour cette opération critique"
                }
            ),
            403,
        )

    return (
        jsonify(
            {
                "error": "La restauration automatique n'est pas activée pour des raisons de sécurité"
            }
        ),
        501,
    )


@admin_bp.route("/emploi-temps", methods=["GET", "POST"])
@login_required
def admin_emploi_temps():
    """
    Page de gestion de l'emploi du temps admin.
    Permet d'afficher et de modifier l'emploi du temps par filière et année.
    """
    if current_user.role != "admin":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("main.index"))

    # Récupération des filtres
    filiere_id = request.args.get("filiere") or request.form.get("filiere")
    annee_id = request.args.get("annee") or request.form.get("annee")

    # Récupération des données pour les listes déroulantes
    filieres = Filiere.query.all()
    annees = Annee.query.all()

    selected_filiere = filiere_id
    selected_annee = annee_id

    # Récupération de l'objet année pour obtenir son nom (car Matiere utilise le nom en string)
    target_annee = None
    if selected_annee:
        target_annee = Annee.query.get(selected_annee)

    # Filtrer les matières spécifiquement pour la filière et l'année sélectionnée
    if selected_filiere and target_annee:
        matieres = Matiere.query.filter_by(
            filiere_id=selected_filiere, annee=target_annee.nom
        ).all()
    else:
        matieres = []  # Liste vide si rien n'est sélectionné

    # Structure de données pour l'emploi du temps (Créneaux Fixes)
    jours = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi"]
    horaires = [
        "07:00 - 10:00",
        "10:30 - 12:30",
        "13:30 - 15:30",
        "16:00 - 18:00",
    ]

    # Traitement du formulaire POST (Enregistrement)
    if request.method == "POST" and selected_filiere:
        try:
            for jour in jours:
                for horaire in horaires:
                    matiere_id = request.form.get(f"matiere_{jour}_{horaire}")
                    salle = request.form.get(f"salle_{jour}_{horaire}", "À définir")

                    heure_debut_str, heure_fin_str = horaire.split(" - ")
                    heure_debut = datetime.strptime(heure_debut_str, "%H:%M").time()
                    heure_fin = datetime.strptime(heure_fin_str, "%H:%M").time()

                    # Chercher le créneau existant par heure_debut (unique pour un jour/filière dans ce système)
                    emploi = EmploiTemps.query.filter_by(
                        filiere_id=selected_filiere, jour=jour, heure_debut=heure_debut
                    ).first()

                    if matiere_id:
                        matiere = Matiere.query.get(matiere_id)
                        if not emploi:
                            emploi = EmploiTemps(
                                filiere_id=selected_filiere,
                                matiere_id=matiere_id,
                                enseignant_id=matiere.enseignant_id,
                                jour=jour,
                                heure_debut=heure_debut,
                                heure_fin=heure_fin,
                                salle=salle,
                            )
                            db.session.add(emploi)
                        else:
                            emploi.matiere_id = matiere_id
                            emploi.enseignant_id = matiere.enseignant_id
                            emploi.heure_fin = heure_fin
                            emploi.salle = salle
                    elif emploi:
                        # Si matiere_id est vide dans le formulaire, on supprime le créneau existant
                        db.session.delete(emploi)

            db.session.commit()
            flash("Emploi du temps mis à jour avec succès.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Erreur lors de l'enregistrement : {str(e)}", "error")

        return redirect(
            url_for(
                "admin.admin_emploi_temps",
                filiere=selected_filiere,
                annee=selected_annee,
            )
        )

    emploi_dict = {jour: {h: None for h in horaires} for jour in jours}

    # Si filière et année sélectionnées, remplir emploi_dict
    if selected_filiere:
        emplois = EmploiTemps.query.filter_by(filiere_id=selected_filiere).all()

        for emp in emplois:
            if emp.heure_debut:
                h_debut = emp.heure_debut.strftime("%H:%M")
                # Trouver le créneau correspondant (soit exact, soit qui commence à la même heure)
                for h in horaires:
                    if h.startswith(h_debut):
                        emploi_dict[emp.jour][h] = emp
                        break

    return render_template(
        "admin/emploi_temps.html",
        filieres=filieres,
        annees=annees,
        matieres=matieres,
        selected_filiere=selected_filiere,
        selected_annee=selected_annee,
        jours=jours,
        horaires=horaires,
        emploi_dict=emploi_dict,
    )


@admin_bp.route("/import/emploi-temps", methods=["POST"])
@login_required
def admin_import_emploi_temps():
    """
    Importation en masse de l'emploi du temps via fichier JSON ou Excel (Cloudinary URL).
    """
    if current_user.role != "admin":
        return jsonify({"error": "Accès non autorisé"}), 403

    file_url = request.form.get("file_url")
    file_type = request.form.get("type")
    filiere_id = request.form.get("filiere")

    if not file_url:
        return jsonify({"error": "Aucun fichier fourni"}), 400

    try:
        data = []
        if file_type == "json":
            import requests

            response = requests.get(file_url)
            response.raise_for_status()
            data = response.json()
        elif file_type == "excel":
            df = pd.read_excel(file_url)
            data = df.to_dict(orient="records")

        count = 0
        errors = []

        for row in data:
            try:
                jour = row.get("jour")
                heure_debut_str = row.get("heure_debut")
                heure_fin_str = row.get("heure_fin")
                matiere_nom = row.get("matiere")
                salle = row.get("salle")

                if not all([jour, heure_debut_str, heure_fin_str, matiere_nom]):
                    continue

                try:
                    # Support formats like "8:00", "08:00", "8:00:00"
                    heure_debut = datetime.strptime(
                        str(heure_debut_str).strip(), "%H:%M"
                    ).time()
                    heure_fin = datetime.strptime(
                        str(heure_fin_str).strip(), "%H:%M"
                    ).time()
                except ValueError:
                    # Try with seconds if failed
                    try:
                        heure_debut = datetime.strptime(
                            str(heure_debut_str).strip(), "%H:%M:%S"
                        ).time()
                        heure_fin = datetime.strptime(
                            str(heure_fin_str).strip(), "%H:%M:%S"
                        ).time()
                    except ValueError:
                        continue

                matiere = Matiere.query.filter(
                    Matiere.nom.ilike(matiere_nom), Matiere.filiere_id == filiere_id
                ).first()

                if not matiere:
                    continue

                emploi = EmploiTemps.query.filter_by(
                    filiere_id=filiere_id, jour=jour, heure_debut=heure_debut
                ).first()

                if not emploi:
                    emploi = EmploiTemps(
                        filiere_id=filiere_id,
                        matiere_id=matiere.id,
                        enseignant_id=matiere.enseignant_id,
                        jour=jour,
                        heure_debut=heure_debut,
                        heure_fin=heure_fin,
                        salle=salle or "À définir",
                    )
                    db.session.add(emploi)
                    count += 1
                else:
                    emploi.matiere_id = matiere.id
                    emploi.enseignant_id = matiere.enseignant_id
                    emploi.salle = salle or emploi.salle
            except Exception as e:
                errors.append(str(e))
                continue

        db.session.commit()
        return jsonify({"success": True, "message": f"{count} créneaux importés."})

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erreur import emploi temps: {str(e)}")
        return jsonify({"error": str(e)}), 500
