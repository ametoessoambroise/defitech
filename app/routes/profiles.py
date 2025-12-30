"""
Ce fichier contient les routes pour les profils des utilisateurs.

Les routes sont :

- /profile/ : redirige vers la page de profil personnel
- /profile/mon-profil : affiche et permet de modifier le profil de l'utilisateur connecté
- /profile/<int:user_id> : affiche le profil d'un autre utilisateur (avec vérifications d'accès)
- /profile/supprimer-compte : supprime le compte de l'utilisateur connecté

"""

import os
from flask import (
    Blueprint,
    abort,
    render_template,
    redirect,
    url_for,
    flash,
    request,
    current_app,
)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app.extensions import db
from app.forms import UpdateProfileForm
from app.models.user import User
from functools import wraps

# Création du blueprint pour les profils
profile_bp = Blueprint("profile", __name__, url_prefix="/profile")

# Configuration pour le téléchargement des fichiers
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "avif"}


def allowed_file(filename):
    """
    Vérifie si l'extension du fichier est autorisée.

    Args:
        filename (str): Nom du fichier à vérifier

    Returns:
        bool: True si l'extension est autorisée, False sinon
    """
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def role_required(*roles):
    """
    Décorateur pour vérifier si l'utilisateur connecté a le rôle requis pour accéder à une fonction.

    Args:
        *roles (str): Les rôles autorisés pour accéder à la fonction

    Returns:
        function: La fonction décorée
    """

    def decorator(f):
        """
        Décorateur pour vérifier si l'utilisateur connecté a le rôle requis pour accéder à une fonction.

        Vérifie si l'utilisateur connecté a le rôle requis pour accéder à la fonction décorée.
        Si l'utilisateur n'a pas le rôle requis, une erreur est flashée et l'utilisateur est redirigé vers la page d'accueil.

        :param f: La fonction à décorer
        :return: La fonction décorée
        """

        @wraps(f)
        def decorated_function(*args, **kwargs):
            if current_user.role not in roles:
                flash("Accès non autorisé.", "danger")
                return redirect(url_for("main.index"))
            return f(*args, **kwargs)

        return decorated_function

    return decorator


@profile_bp.route("/")
@login_required
def index():
    """
    Redirige vers la page 'mon-profil' de l'utilisateur connecté.

    Cette fonction est l'endpoint de la route '/' du blueprint 'profile_bp'.
    Elle redirige vers la page 'mon-profil' en utilisant la fonction 'url_for'.

    Retourne :
    - Une réponse HTTP redirigée vers la page 'mon-profil' de l'utilisateur connecté.
    """
    return redirect(url_for("profile.mon_profil"))


@profile_bp.route("/<int:user_id>")
@login_required
def view_profile(user_id):
    """
    Affiche le profil d'un autre utilisateur.

    Cette fonction est l'endpoint de la route '/<int:user_id>' du blueprint 'profile_bp'.
    Elle récupère l'utilisateur correspondant à l'ID spécifié et l'affiche.

    Paramètres:
    - user_id (int): L'ID de l'utilisateur dont on souhaite afficher le profil.

    Retourne :
    - Une réponse HTTP avec le profil de l'utilisateur spécifié.

    Notes :
    - L'accès à ce profil est contrôlé :
        - Les étudiants peuvent voir les profils d'autres étudiants de la même filière.
        - Les enseignants peuvent voir les profils d'autres utilisateurs.
    - Si l'utilisateur n'existe pas, une erreur 404 est renvoyée.
    - Si l'utilisateur essaie d'accéder à un profil qu'il n'est pas autorisé à voir, une erreur 403 est renvoyée.
    """

    user = User.query.get_or_404(user_id)

    # Vérifier les permissions d'accès
    if current_user.role == "etudiant" and user.role == "etudiant":
        # Les étudiants peuvent voir les profils d'autres étudiants de la même filière
        if hasattr(current_user, "etudiant") and hasattr(user, "etudiant"):
            if current_user.etudiant.filiere != user.etudiant.filiere:
                abort(403)
    elif current_user.role == "enseignant" and user.role == "etudiant":
        # Les enseignants peuvent voir les profils des étudiants de leurs filières
        if hasattr(current_user, "enseignant") and hasattr(user, "etudiant"):
            # Vérifier si l'enseignant enseigne dans la filière de l'étudiant
            from app.models import Matiere, Filiere

            filiere = Filiere.query.filter_by(nom=user.etudiant.filiere).first()
            if filiere:
                matieres = Matiere.query.filter_by(
                    filiere_id=filiere.id, enseignant_id=current_user.enseignant.id
                ).all()
                if not matieres:
                    abort(403)
    elif current_user.role != "admin" and current_user.id != user.id:
        abort(403)

    return render_template("profile/view_profile.html", user=user)


@profile_bp.route("/mon-profil", methods=["GET", "POST"])
@login_required
def mon_profil():
    """
    Page de profil de l'utilisateur connecté.

    Cette fonction affiche le profil de l'utilisateur connecté et permet
    de modifier les informations du profil. Pour les enseignants, une demande
    de modification doit être approuvée par un administrateur avant que les
    modifications soient prises en compte.

    Paramètres :
    - None

    Retourne :
    - Une réponse HTTP avec la page de profil de l'utilisateur connecté,
      préremplie avec les informations actuelles.

    Notes :
    - Pour les enseignants : une demande de modification est créée si le
      profil existe déjà et que les informations sont modifiées.
    - Pour les autres rôles : les informations du profil sont directement
      modifiées sans validation administrative.
    """
    form = UpdateProfileForm()

    # Récupérer les options pour les champs select
    from app.models.filiere import Filiere
    from app.models.annee import Annee
    from app.models import TeacherProfileUpdateRequest

    filieres = Filiere.query.all()
    annees = Annee.query.all()

    # Convertir en liste de tuples pour SelectMultipleField
    form.filieres_enseignees.choices = [(f.nom, f.nom) for f in filieres]
    form.annees_enseignees.choices = [(a.nom, a.nom) for a in annees]

    if form.validate_on_submit():
        # Vérifier si l'utilisateur a un profil enseignant
        if current_user.role == "enseignant" and current_user.enseignant:
            # Pour les enseignants avec profil : créer une demande de modification
            return _handle_teacher_profile_update_request(form)
        else:
            # Pour les autres rôles ou enseignants sans profil : modification directe
            return _handle_direct_profile_update(form)

    # Pré-remplir le formulaire avec les données actuelles de l'utilisateur
    _populate_form_with_current_data(form)

    # Récupérer les demandes de modification en attente pour les enseignants
    pending_requests = []
    approved_requests = []
    rejected_requests = []

    if current_user.role == "enseignant":
        all_requests = (
            TeacherProfileUpdateRequest.query.filter_by(user_id=current_user.id)
            .order_by(TeacherProfileUpdateRequest.date_creation.desc())
            .all()
        )

        for req in all_requests:
            if req.statut == "en_attente":
                pending_requests.append(req)
            elif req.statut == "approuve":
                approved_requests.append(req)
            elif req.statut == "rejete":
                rejected_requests.append(req)

    return render_template(
        "profile/mon_profil.html",
        form=form,
        pending_requests=pending_requests,
        approved_requests=approved_requests,
        rejected_requests=rejected_requests,
    )


def _handle_teacher_profile_update_request(form):
    """Gère la création d'une demande de modification pour un enseignant"""
    from app.models import TeacherProfileUpdateRequest

    # Vérifier si une demande est déjà en attente
    existing_request = TeacherProfileUpdateRequest.query.filter_by(
        user_id=current_user.id, statut="en_attente"
    ).first()

    if existing_request:
        flash("Une demande de modification est déjà en cours d'examen.", "warning")
        return redirect(url_for("profile.mon_profil"))

    # Récupérer l'enseignant actuel
    enseignant = current_user.enseignant
    if not enseignant:
        flash("Profil enseignant non trouvé.", "error")
        return redirect(url_for("profile.mon_profil"))

    # Récupérer les données des checkboxes
    filieres_enseignees = request.form.getlist("filieres_enseignees")
    annees_enseignees = request.form.getlist("annees_enseignees")

    # Créer la demande de modification
    update_request = TeacherProfileUpdateRequest(
        user_id=current_user.id,
        # Informations personnelles
        nom=form.nom.data,
        prenom=form.prenom.data,
        email=form.email.data,
        telephone=form.telephone.data,
        adresse=form.adresse.data,
        ville=form.ville.data,
        code_postal=form.code_postal.data,
        pays=form.pays.data,
        # Informations enseignant
        specialite=form.specialite.data,
        grade=form.grade.data,
        filieres_enseignees=(
            ",".join(filieres_enseignees) if filieres_enseignees else None
        ),
        annees_enseignees=",".join(annees_enseignees) if annees_enseignees else None,
        date_embauche=form.date_embauche.data,
    )

    # Gestion de la photo de profil
    if form.photo_profil.data:
        import os
        from werkzeug.utils import secure_filename

        file = form.photo_profil.data
        if file.filename != "":
            if allowed_file(file.filename):
                filename = f"teacher_request_{current_user.id}_{secure_filename(file.filename)}"
                file_path = os.path.join(
                    current_app.config["UPLOAD_FOLDER"], "profile_pics", filename
                )
                file.save(file_path)
                update_request.photo_profil = filename

    # Sauvegarder la demande (avec ou sans photo)
    db.session.add(update_request)
    db.session.commit()

    # Notifier tous les administrateurs
    from app.models import User
    from app.models.notification import Notification

    admins = User.query.filter_by(role="admin").all()
    for admin in admins:
        notif = Notification(
            user_id=admin.id,
            titre="Demande de modification de profil",
            message=f"L'enseignant {current_user.prenom} {current_user.nom} a soumis une demande de modification de profil. Cliquez pour examiner.",
            type="teacher_request",
            element_id=update_request.id,
            element_type="teacher_request",
        )
        db.session.add(notif)

        # Envoyer un email à l'admin
        try:
            from app.email_utils import send_teacher_profile_request_email

            send_teacher_profile_request_email(admin, current_user, update_request)
        except Exception as e:
            print(f"Erreur lors de l'envoi de l'email à {admin.email}: {e}")

    db.session.commit()

    flash(
        "Votre demande de modification a été soumise et est en attente d'approbation par l'administration.",
        "success",
    )
    return redirect(url_for("profile.mon_profil"))


def _handle_direct_profile_update(form):
    """Gère la modification directe du profil (pour non-enseignants)"""
    import os

    # Mise à jour des informations de base
    current_user.nom = form.nom.data
    current_user.prenom = form.prenom.data
    current_user.email = form.email.data
    current_user.date_naissance = form.date_naissance.data
    current_user.sexe = form.sexe.data

    # Nouveaux champs de contact
    current_user.telephone = form.telephone.data
    current_user.adresse = form.adresse.data
    current_user.ville = form.ville.data
    current_user.code_postal = form.code_postal.data
    current_user.pays = form.pays.data
    current_user.linkedin = form.linkedin.data
    current_user.github = form.github.data
    current_user.bio = form.bio.data

    # Mise à jour du mot de passe si fourni
    if form.nouveau_mot_de_passe.data:
        from werkzeug.security import generate_password_hash

        current_user.password_hash = generate_password_hash(
            form.nouveau_mot_de_passe.data
        )

    # Gestion de la photo de profil via Cloudinary URL
    if form.photo_profil_url.data:
        # Si une URL est fournie (via Cloudinary)
        current_user.photo_profil = form.photo_profil_url.data

        # Supprimer l'ancienne photo si c'était un fichier local (commence pas par http)
        # Note: ceci est optionnel, car on migre tout vers le cloud.
        # Idéalement on ne supprime pas les fichiers Cloudinary directement ici sans API admin

    # Fallback: Gestion de l'upload fichier classique (Si le JS a échoué ou bypassé)
    elif form.photo_profil.data:
        file = form.photo_profil.data
        if file.filename != "":
            # Ce cas ne devrait plus arriver si on force le JS, mais on garde pour compatibilité
            # OU on le commente pour forcer Cloudinary
            pass
            # ... old logic ...

    # Old logic for cleanup (Legacy local file removal)
    # if current_user.photo_profil and not current_user.photo_profil.startswith('http'):
    #     try:
    #         os.remove(...)
    #     except...

    db.session.commit()
    flash("Profil mis à jour avec succès!", "success")
    return redirect(url_for("profile.mon_profil"))


def _populate_form_with_current_data(form):
    """Pré-remplit le formulaire avec les données actuelles de l'utilisateur"""
    form.nom.data = current_user.nom
    form.prenom.data = current_user.prenom
    form.email.data = current_user.email
    form.date_naissance.data = current_user.date_naissance
    form.sexe.data = current_user.sexe

    # Nouveaux champs de contact
    form.telephone.data = current_user.telephone
    form.adresse.data = current_user.adresse
    form.ville.data = current_user.ville
    form.code_postal.data = current_user.code_postal
    form.pays.data = current_user.pays
    form.linkedin.data = current_user.linkedin
    form.github.data = current_user.github
    form.bio.data = current_user.bio

    # Si l'utilisateur est un enseignant, pré-remplir ses champs spécifiques
    if current_user.role == "enseignant":
        try:
            # Vérifier si l'utilisateur a un profil enseignant sans le charger complètement
            if hasattr(current_user, "enseignant") and current_user.enseignant:
                enseignant = current_user.enseignant
                form.specialite.data = enseignant.specialite
                form.grade.data = enseignant.grade
                form.date_embauche.data = enseignant.date_embauche

                # Filieres et années enseignées
                if enseignant.filieres_enseignees:
                    try:
                        # Les données sont stockées comme CSV, pas JSON
                        filieres_list = [
                            f.strip()
                            for f in enseignant.filieres_enseignees.split(",")
                            if f.strip()
                        ]
                        form.filieres_enseignees.data = filieres_list
                    except Exception:
                        form.filieres_enseignees.data = []

                if (
                    hasattr(enseignant, "annees_enseignees")
                    and enseignant.annees_enseignees
                ):
                    try:
                        # Les données sont stockées comme CSV, pas JSON
                        annees_list = [
                            a.strip()
                            for a in enseignant.annees_enseignees.split(",")
                            if a.strip()
                        ]
                        form.annees_enseignees.data = annees_list
                    except Exception:
                        form.annees_enseignees.data = []
        except Exception as e:
            # En cas d'erreur de chargement (colonne manquante, etc.), ignorer silencieusement
            print(f"Erreur lors du chargement du profil enseignant: {e}")
            pass


@profile_bp.route("/supprimer-compte", methods=["POST"])
@login_required
def supprimer_compte():
    """
    Supprime le compte de l'utilisateur actuel.

    Cette fonction effectue les opérations suivantes :

    - Supprime la photo de profil si ce n'est pas l'image par défaut.
    - Supprime d'abord les enregistrements liés (étudiant, enseignant, etc.)
    - Puis supprime l'utilisateur de la base de données.
    - Redirige vers la page de connexion avec un message de succès.

    Cette fonction est utilisée pour permettre aux utilisateurs de supprimer leur propre compte.
    Elle est utilisée comme endpoint de la route '/supprimer-compte' du blueprint 'profile_bp'.

    Cette fonction n'accepte que les demandes POST.

    Retourne:
        Une redirection vers la page de connexion avec un message de succès.

    """
    try:
        with db.session.begin_nested():  # Utilisation d'une sous-transaction
            with db.session.no_autoflush:  # Désactiver l'autoflush pour éviter les flush prématurés
                # 1. Gérer les messages envoyés par l'utilisateur (approche directe)
                from app.models.message import Message

                try:
                    # Supprimer les messages où l'utilisateur est l'expéditeur
                    db.session.execute(
                        db.text("DELETE FROM message WHERE sender_id = :user_id"),
                        {"user_id": current_user.id},
                    )
                    # Supprimer les messages où l'utilisateur est le destinataire
                    db.session.execute(
                        db.text("DELETE FROM message WHERE receiver_id = :user_id"),
                        {"user_id": current_user.id},
                    )
                except Exception as e:
                    current_app.logger.error(
                        f"Erreur lors de la suppression des messages: {str(e)}"
                    )
                    # Fallback avec SQLAlchemy
                    Message.query.filter_by(sender_id=current_user.id).delete()
                    Message.query.filter_by(receiver_id=current_user.id).delete()

                # 3. Supprimer les notifications liées à l'utilisateur
                from models.notification import Notification

                Notification.query.filter_by(user_id=current_user.id).delete()

                # 4. Supprimer la photo de profil si ce n'est pas l'image par défaut
                if (
                    current_user.photo_profil
                    and current_user.photo_profil != "default.jpg"
                ):
                    try:
                        photo_path = os.path.join(
                            current_app.static_folder,  # Chemin vers le dossier static
                            "uploads",
                            "profile_pics",
                            current_user.photo_profil,
                        )
                        if os.path.exists(photo_path):
                            os.remove(photo_path)
                    except Exception as e:
                        current_app.logger.error(
                            f"Erreur lors de la suppression de la photo de profil: {str(e)}"
                        )
                        # Ne pas arrêter l'exécution en cas d'échec de suppression de la photo

                # 5. Supprimer les bug_reports créés par l'utilisateur
                from models.bug_report import BugReport

                BugReport.query.filter_by(user_id=current_user.id).delete()

                # 6. Supprimer les posts créés par l'utilisateur
                from models.post import Post

                Post.query.filter_by(auteur_id=current_user.id).delete()

                # 7. Supprimer les commentaires créés par l'utilisateur
                from models.commentaire import Commentaire

                Commentaire.query.filter_by(auteur_id=current_user.id).delete()

                # 8. Supprimer les autres enregistrements liés
                from models.study_document import StudyDocument
                from models.study_progress import StudyProgress
                from models.study_session import StudySession
                from models.quiz_models import Quiz, QuizAttempt, QuizAnswer
                from models.flashcard import Flashcard, FlashcardReview
                from models.suggestion import Suggestion, SuggestionVote
                from models.password_reset_token import PasswordResetToken
                from models.teacher_profile_update_request import (
                    TeacherProfileUpdateRequest,
                )
                from models.competence import Competence
                from models.experience import Experience
                from models.formation import Formation
                from models.langue import Langue
                from models.projet import Projet
                from models.videoconference import (
                    RoomParticipant,
                    RoomActivityLog,
                    Inscription,
                    RoomInvitation,
                    Room,
                )
                from models.resource import Resource
                from models.global_notification import GlobalNotification
                from models.pomodoro_session import PomodoroSession
                from models.devoir import Devoir
                from models.devoir_vu import DevoirVu

                # Documents d'étude (approche directe pour éviter les problèmes de SQLAlchemy)
                try:
                    db.session.execute(
                        db.text("DELETE FROM study_documents WHERE user_id = :user_id"),
                        {"user_id": current_user.id},
                    )
                except Exception as e:
                    current_app.logger.error(
                        f"Erreur lors de la suppression des study_documents: {str(e)}"
                    )
                    # Essayer avec SQLAlchemy si la requête SQL échoue
                    StudyDocument.query.filter_by(user_id=current_user.id).delete()

                # Progression d'étude et sessions
                StudyProgress.query.filter_by(user_id=current_user.id).delete()
                StudySession.query.filter_by(user_id=current_user.id).delete()

                # Compétences, expériences, formations, langues, projets
                Competence.query.filter_by(user_id=current_user.id).delete()
                Experience.query.filter_by(user_id=current_user.id).delete()
                Formation.query.filter_by(user_id=current_user.id).delete()
                Langue.query.filter_by(user_id=current_user.id).delete()
                Projet.query.filter_by(user_id=current_user.id).delete()

                # Vidéoconférence (ordre important : supprimer d'abord les dépendances, puis les salles)
                # 1. D'abord supprimer les invitations qui référencent les salles
                RoomInvitation.query.filter_by(user_id=current_user.id).delete()

                # 2. Supprimer les invitations pour les salles hébergées par l'utilisateur
                rooms_hotees = Room.query.filter_by(host_id=current_user.id).all()
                for room in rooms_hotees:
                    RoomInvitation.query.filter_by(room_id=room.id).delete()

                # 3. Supprimer les participants et logs d'activité
                RoomParticipant.query.filter_by(user_id=current_user.id).delete()
                RoomActivityLog.query.filter_by(user_id=current_user.id).delete()

                # 4. Supprimer les inscriptions
                Inscription.query.filter_by(user_id=current_user.id).delete()

                # 5. Enfin supprimer les salles hébergées
                Room.query.filter_by(host_id=current_user.id).delete()

                # Ressources et notifications globales créées par l'utilisateur
                Resource.query.filter_by(enseignant_id=current_user.id).delete()
                GlobalNotification.query.filter_by(createur_id=current_user.id).delete()

                # Sessions Pomodoro (pour les étudiants)
                if hasattr(current_user, "etudiant") and current_user.etudiant:
                    PomodoroSession.query.filter_by(
                        etudiant_id=current_user.etudiant.id
                    ).delete()

                # Devoirs vus par l'utilisateur (étudiants)
                if hasattr(current_user, "etudiant") and current_user.etudiant:
                    DevoirVu.query.filter_by(
                        etudiant_id=current_user.etudiant.id
                    ).delete()

                # Quiz et tentatives
                Quiz.query.filter_by(user_id=current_user.id).delete()
                QuizAttempt.query.filter_by(user_id=current_user.id).delete()
                QuizAnswer.query.filter_by(user_id=current_user.id).delete()

                # Flashcards
                Flashcard.query.filter_by(user_id=current_user.id).delete()
                FlashcardReview.query.filter_by(user_id=current_user.id).delete()

                # Suggestions et votes
                Suggestion.query.filter_by(user_id=current_user.id).delete()
                SuggestionVote.query.filter_by(user_id=current_user.id).delete()

                # Tokens de réinitialisation et demandes de profil
                PasswordResetToken.query.filter_by(user_id=current_user.id).delete()
                TeacherProfileUpdateRequest.query.filter_by(
                    user_id=current_user.id
                ).delete()

                # 9. Si l'utilisateur est un étudiant, supprimer d'abord l'entrée étudiant et les données associées
                from models.etudiant import Etudiant
                from models.presence import Presence
                from models.note import Note

                etudiant = Etudiant.query.filter_by(user_id=current_user.id).first()
                if etudiant:
                    # Supprimer les présences de l'étudiant
                    Presence.query.filter_by(etudiant_id=etudiant.id).delete()

                    # Supprimer les notes de l'étudiant
                    Note.query.filter_by(etudiant_id=etudiant.id).delete()

                    # Puis supprimer l'entrée étudiant
                    db.session.delete(etudiant)

                # 10. Si l'utilisateur est un enseignant, gérer d'abord les matières associées et l'emploi du temps
                from models.enseignant import Enseignant
                from models.matiere import Matiere
                from models.emploi_temps import EmploiTemps
                from models.note import Note

                enseignant = Enseignant.query.filter_by(user_id=current_user.id).first()
                if enseignant:
                    # Supprimer l'emploi du temps de l'enseignant
                    emplois_temps = EmploiTemps.query.filter_by(
                        enseignant_id=enseignant.id
                    ).all()
                    for emploi in emplois_temps:
                        db.session.delete(emploi)

                    # Supprimer les devoirs créés par l'enseignant (approche directe)
                    # Utiliser une requête SQL brute pour éviter les problèmes de SQLAlchemy
                    try:
                        # D'abord supprimer les devoir_vu qui référencent les devoirs de cet enseignant
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

                        # Puis supprimer les devoirs
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
                        # Essayer avec SQLAlchemy si la requête SQL échoue
                        from models.devoir import Devoir

                        devoirs = Devoir.query.filter_by(
                            enseignant_id=enseignant.id
                        ).all()
                        for devoir in devoirs:
                            # D'abord supprimer les devoir_vu pour ce devoir
                            DevoirVu.query.filter_by(devoir_id=devoir.id).delete()
                            # Puis supprimer le devoir
                            db.session.delete(devoir)

                    # Supprimer les matières enseignées ET les notes associées
                    matieres = Matiere.query.filter_by(
                        enseignant_id=enseignant.id
                    ).all()
                    for matiere in matieres:
                        # D'abord supprimer les notes des étudiants pour cette matière
                        Note.query.filter_by(matiere_id=matiere.id).delete()
                        # Puis supprimer la matière
                        db.session.delete(matiere)

                    # Puis supprimer l'enseignant
                    db.session.delete(enseignant)

                # 11. Enfin, supprimer l'utilisateur
                db.session.delete(current_user)

        # Tout s'est bien passé, on peut faire le commit final
        db.session.commit()

        flash("Votre compte a été supprimé avec succès.", "success")
        return redirect(url_for("auth.login"))

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erreur lors de la suppression du compte: {str(e)}")
        flash(
            "Une erreur est survenue lors de la suppression de votre compte. Veuillez réessayer.",
            "danger",
        )
        return redirect(url_for("profile.mon_profil"))


# Fonction utilitaire pour obtenir l'URL de la photo de profil
def get_profile_picture(user):
    """
    Renvoie l'URL de la photo de profil de l'utilisateur.

    Si l'utilisateur a une photo de profil, renvoie l'URL de cette photo.
    Si la photo est déjà une URL complète (comme une URL Cloudinary), la renvoie telle quelle.
    Sinon, renvoie l'URL de l'image par défaut (le favicon).

    :param user: L'utilisateur dont on veut obtenir l'URL de la photo de profil.
    :type user: User
    :return: L'URL de la photo de profil.
    :rtype: str
    """
    if user.photo_profil:
        # Si c'est déjà une URL complète (commence par http:// ou https://)
        if user.photo_profil.startswith(("http://", "https://")):
            return user.photo_profil
        # Sinon, on suppose que c'est un chemin relatif
        return url_for(
            "static",
            filename=f"uploads/profile_pics/{user.photo_profil}",
            _external=True,
        )
    return url_for("static", filename="assets/favicon.ico")


# Ajouter la fonction au contexte du template
@profile_bp.context_processor
def utility_processor():
    """
    Ajoute la fonction get_profile_picture au contexte du template.

    La fonction get_profile_picture permet d'obtenir l'URL de la photo de profil d'un utilisateur.

    :return: Un dictionnaire contenant la fonction get_profile_picture.
    :rtype: dict
    """
    return dict(get_profile_picture=get_profile_picture)


# Routes pour le profil étendu
@profile_bp.route("/profil-avance")
@login_required
def profil_avance():
    """
    Affiche la page du profil avancé avec compétences, formations, expériences, etc.

    :return: Template du profil avancé
    :rtype: str
    """
    from app.models.competence import Competence
    from app.models.formation import Formation
    from app.models.langue import Langue
    from app.models.projet import Projet
    from app.models.experience import Experience

    # Récupérer toutes les données de l'utilisateur
    competences = (
        Competence.query.filter_by(user_id=current_user.id)
        .order_by(Competence.created_at.desc())
        .all()
    )
    formations = (
        Formation.query.filter_by(user_id=current_user.id)
        .order_by(Formation.date_debut.desc())
        .all()
    )
    langues = (
        Langue.query.filter_by(user_id=current_user.id)
        .order_by(Langue.created_at.desc())
        .all()
    )
    projets = (
        Projet.query.filter_by(user_id=current_user.id)
        .order_by(Projet.date_debut.desc())
        .all()
    )
    experiences = (
        Experience.query.filter_by(user_id=current_user.id)
        .order_by(Experience.date_debut.desc())
        .all()
    )

    # Calculer la complétion du profil via CVGenerator
    from app.services.cv_generator import CVGenerator

    cv_gen = CVGenerator(current_user.id)
    profile_data = cv_gen.get_user_data()
    completion = profile_data.get("completion", {"score": 0, "details": {}})
    suggestions = profile_data.get("suggestions", [])

    return render_template(
        "profile/profil_avance.html",
        competences=competences,
        formations=formations,
        langues=langues,
        projets=projets,
        experiences=experiences,
        completion=completion,
        suggestions=suggestions,
    )


# Routes pour les compétences
@profile_bp.route("/competences/ajouter", methods=["GET", "POST"])
@login_required
def ajouter_competence():
    """
    Ajoute une nouvelle compétence au profil de l'utilisateur.

    :return: Redirection vers le profil avancé ou template du formulaire
    :rtype: Response ou str
    """
    from app.models.competence import Competence
    from app.forms import CompetenceForm

    form = CompetenceForm()
    if form.validate_on_submit():
        competence = Competence(
            user_id=current_user.id,
            nom=form.nom.data,
            niveau=form.niveau.data,
            categorie=form.categorie.data,
        )
        db.session.add(competence)
        db.session.commit()
        flash("Compétence ajoutée avec succès!", "success")
        return redirect(url_for("profile.profil_avance"))

    return render_template("profile/ajouter_competence.html", form=form)


@profile_bp.route("/competences/<int:competence_id>/supprimer", methods=["POST"])
@login_required
def supprimer_competence(competence_id):
    """
    Supprime une compétence du profil de l'utilisateur.

    :param competence_id: ID de la compétence à supprimer
    :type competence_id: int
    :return: Redirection vers le profil avancé
    :rtype: Response
    """
    from app.models.competence import Competence

    competence = Competence.query.get_or_404(competence_id)
    if competence.user_id != current_user.id:
        flash("Accès non autorisé", "error")
        return redirect(url_for("profile.profil_avance"))

    db.session.delete(competence)
    db.session.commit()
    flash("Compétence supprimée avec succès!", "success")
    return redirect(url_for("profile.profil_avance"))


# Routes pour les formations
@profile_bp.route("/formations/ajouter", methods=["GET", "POST"])
@login_required
def ajouter_formation():
    """
    Ajoute une nouvelle formation au profil de l'utilisateur.

    :return: Redirection vers le profil avancé ou template du formulaire
    :rtype: Response ou str
    """
    from app.models.formation import Formation
    from app.forms import FormationForm

    form = FormationForm()
    if form.validate_on_submit():
        formation = Formation(
            user_id=current_user.id,
            diplome=form.diplome.data,
            etablissement=form.etablissement.data,
            domaine=form.domaine.data,
            description=form.description.data,
            date_debut=form.date_debut.data,
            date_fin=form.date_fin.data if not form.en_cours.data == "True" else None,
            en_cours=form.en_cours.data == "True",
        )
        db.session.add(formation)
        db.session.commit()
        flash("Formation ajoutée avec succès!", "success")
        return redirect(url_for("profile.profil_avance"))

    return render_template("profile/ajouter_formation.html", form=form)


@profile_bp.route("/formations/<int:formation_id>/supprimer", methods=["POST"])
@login_required
def supprimer_formation(formation_id):
    """
    Supprime une formation du profil de l'utilisateur.

    :param formation_id: ID de la formation à supprimer
    :type formation_id: int
    :return: Redirection vers le profil avancé
    :rtype: Response
    """
    from app.models.formation import Formation

    formation = Formation.query.get_or_404(formation_id)
    if formation.user_id != current_user.id:
        flash("Accès non autorisé", "error")
        return redirect(url_for("profile.profil_avance"))

    db.session.delete(formation)
    db.session.commit()
    flash("Formation supprimée avec succès!", "success")
    return redirect(url_for("profile.profil_avance"))


# Routes pour les langues
@profile_bp.route("/langues/ajouter", methods=["GET", "POST"])
@login_required
def ajouter_langue():
    """
    Ajoute une nouvelle langue au profil de l'utilisateur.

    :return: Redirection vers le profil avancé ou template du formulaire
    :rtype: Response ou str
    """
    from app.models.langue import Langue
    from app.forms import LangueForm

    form = LangueForm()
    if form.validate_on_submit():
        langue = Langue(
            user_id=current_user.id,
            nom=form.nom.data,
            niveau_ecrit=form.niveau_ecrit.data,
            niveau_oral=form.niveau_oral.data,
        )
        db.session.add(langue)
        db.session.commit()
        flash("Langue ajoutée avec succès!", "success")
        return redirect(url_for("profile.profil_avance"))

    return render_template("profile/ajouter_langue.html", form=form)


@profile_bp.route("/langues/<int:langue_id>/supprimer", methods=["POST"])
@login_required
def supprimer_langue(langue_id):
    """
    Supprime une langue du profil de l'utilisateur.

    :param langue_id: ID de la langue à supprimer
    :type langue_id: int
    :return: Redirection vers le profil avancé
    :rtype: Response
    """
    from app.models.langue import Langue

    langue = Langue.query.get_or_404(langue_id)
    if langue.user_id != current_user.id:
        flash("Accès non autorisé", "error")
        return redirect(url_for("profile.profil_avance"))

    db.session.delete(langue)
    db.session.commit()
    flash("Langue supprimée avec succès!", "success")
    return redirect(url_for("profile.profil_avance"))


# Routes pour les projets
@profile_bp.route("/projets/ajouter", methods=["GET", "POST"])
@login_required
def ajouter_projet():
    """
    Ajoute un nouveau projet au profil de l'utilisateur.

    :return: Redirection vers le profil avancé ou template du formulaire
    :rtype: Response ou str
    """
    from app.models.projet import Projet
    from app.forms import ProjetForm

    form = ProjetForm()
    if form.validate_on_submit():
        projet = Projet(
            user_id=current_user.id,
            titre=form.titre.data,
            description=form.description.data,
            technologies=form.technologies.data,
            date_debut=form.date_debut.data,
            date_fin=form.date_fin.data if not form.en_cours.data == "True" else None,
            lien=form.lien.data,
            en_cours=form.en_cours.data == "True",
        )
        db.session.add(projet)
        db.session.commit()
        flash("Projet ajouté avec succès!", "success")
        return redirect(url_for("profile.profil_avance"))

    return render_template("profile/ajouter_projet.html", form=form)


@profile_bp.route("/projets/<int:projet_id>/supprimer", methods=["POST"])
@login_required
def supprimer_projet(projet_id):
    """
    Supprime un projet du profil de l'utilisateur.

    :param projet_id: ID du projet à supprimer
    :type projet_id: int
    :return: Redirection vers le profil avancé
    :rtype: Response
    """
    from app.models.projet import Projet

    projet = Projet.query.get_or_404(projet_id)
    if projet.user_id != current_user.id:
        flash("Accès non autorisé", "error")
        return redirect(url_for("profile.profil_avance"))

    db.session.delete(projet)
    db.session.commit()
    flash("Projet supprimé avec succès!", "success")
    return redirect(url_for("profile.profil_avance"))


# Routes pour les expériences
@profile_bp.route("/experiences/ajouter", methods=["GET", "POST"])
@login_required
def ajouter_experience():
    """
    Ajoute une nouvelle expérience professionnelle au profil de l'utilisateur.

    :return: Redirection vers le profil avancé ou template du formulaire
    :rtype: Response ou str
    """
    from app.models.experience import Experience
    from app.forms import ExperienceForm

    form = ExperienceForm()
    if form.validate_on_submit():
        experience = Experience(
            user_id=current_user.id,
            poste=form.poste.data,
            entreprise=form.entreprise.data,
            lieu=form.lieu.data,
            description=form.description.data,
            date_debut=form.date_debut.data,
            date_fin=form.date_fin.data if not form.en_poste.data == "True" else None,
            en_poste=form.en_poste.data == "True",
        )
        db.session.add(experience)
        db.session.commit()
        flash("Expérience ajoutée avec succès!", "success")
        return redirect(url_for("profile.profil_avance"))

    return render_template("profile/ajouter_experience.html", form=form)


@profile_bp.route("/experiences/<int:experience_id>/supprimer", methods=["POST"])
@login_required
def supprimer_experience(experience_id):
    """
    Supprime une expérience professionnelle du profil de l'utilisateur.

    :param experience_id: ID de l'expérience à supprimer
    :type experience_id: int
    :return: Redirection vers le profil avancé
    :rtype: Response
    """
    from app.models.experience import Experience

    experience = Experience.query.get_or_404(experience_id)
    if experience.user_id != current_user.id:
        flash("Accès non autorisé", "error")
        return redirect(url_for("profile.profil_avance"))

    db.session.delete(experience)
    db.session.commit()
    flash("Expérience supprimée avec succès!", "success")
    return redirect(url_for("profile.profil_avance"))
