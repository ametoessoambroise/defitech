"""
Routes pour la gestion des salles de visioconférence
"""

from flask import (
    Blueprint,
    request,
    jsonify,
    render_template,
    url_for,
    abort,
    flash,
    redirect,
    current_app,
)
from flask_login import login_required, current_user
from app.models.videoconference import (
    Room,
    RoomParticipant,
    RoomActivityLog,
    RoomInvitation,
)
from app.models.matiere import Matiere
from app.models.etudiant import Etudiant
from app.models.enseignant import Enseignant
from app.models.filiere import Filiere
from app.models.emploi_temps import EmploiTemps
from app.extensions import db
from sqlalchemy import func
import logging
import secrets
from datetime import datetime
from app.utils.room_utils import send_room_invitations

bp = Blueprint("videoconference", __name__, url_prefix="/videoconference")


@bp.route("/create", methods=["POST"])
@login_required
def create_room():
    """
    Crée une nouvelle salle de visioconférence.

    Cette route est utilisée pour créer une nouvelle salle de visioconférence.
    Elle attend une requête POST avec un corps JSON contenant les informations
    suivantes :

    Args:
        name (str): Le nom de la salle.
        course_id (int): L'ID du cours auquel la salle est liée.
        is_public (bool): Indique si la salle est publique ou non.

    Retourne:
        Une réponse JSON contenant les informations suivantes :
        - success (bool): Indique si la requête a été effectuée avec succès.

    Exemple de requête JSON :
    {
        "name": "Nom de la salle",
        "course_id": 1,
        "is_public": false
    }

    Exemple de réponse JSON :
    {
        "success": true
    }
    """
    data = request.get_json()

    # Validation des données
    if not all(k in data for k in ["name", "course_id"]):
        return jsonify({"error": "Nom et ID de cours requis"}), 400

    # Vérifier que le cours existe et que l'utilisateur est l'enseignant
    course = Matiere.query.get_or_404(data["course_id"])
    if course.enseignant_id != current_user.id and not current_user.is_admin:
        return jsonify({"error": "Non autorisé à créer une salle pour ce cours"}), 403

    try:
        # Création de la salle
        room = Room(
            name=data["name"],
            course_id=data["course_id"],
            host_id=current_user.id,
            is_active=True,
        )
        db.session.add(room)

        # Enregistrer l'hôte comme participant
        host_participant = RoomParticipant(
            room=room, user_id=current_user.id, role="host"
        )
        db.session.add(host_participant)

        db.session.commit()

        return (
            jsonify(
                {
                    "success": True,
                    "room_id": room.id,
                    "room_token": room.room_token,
                    "join_url": url_for(
                        "videoconference.join_room",
                        token=room.room_token,
                        _external=True,
                    ),
                }
            ),
            201,
        )

    except Exception as e:
        db.session.rollback()
        logging.error(f"Erreur création salle: {str(e)}")
        return jsonify({"error": "Erreur lors de la création de la salle"}), 500


@bp.route("/room/<token>", methods=["GET"])
@login_required
def join_room(token):
    """
    Rejoindre une salle de visioconférence.

    Cette route est utilisée pour rejoindre une salle de visioconférence en
    utilisant le token de la salle. Elle renvoie une réponse HTML contenant
    la page de la salle.

    Args:
        token (str): Le token unique de la salle de visioconférence à rejoindre.

    Retourne:
        Une réponse HTML contenant la page de la salle de visioconférence.

    Raises:
        NotFound: Si la salle de visioconférence avec le token donné n'existe pas.
    """
    room = Room.query.filter_by(room_token=token).first_or_404()

    # Vérifier si l'utilisateur a accès au cours
    has_access = False
    if current_user.role == "etudiant":
        # Vérifier si l'étudiant est inscrit au cours
        etudiant = Etudiant.query.filter_by(user_id=current_user.id).first()
        has_access = etudiant and etudiant.filiere_id == room.course.filiere_id
    elif current_user.role == "enseignant":
        # Les enseignants ont accès s'ils enseignent le cours ou sont admins
        has_access = (
            room.course.enseignant_id == current_user.id
        ) or current_user.is_admin

    if not has_access and not current_user.is_admin:
        abort(403, "Accès non autorisé à cette salle")

    # Enregistrer la participation
    participant = RoomParticipant.query.filter_by(
        room_id=room.id, user_id=current_user.id
    ).first()

    if not participant:
        role = "teacher" if current_user.role == "enseignant" else "student"
        participant = RoomParticipant(
            room_id=room.id, user_id=current_user.id, role=role
        )
        db.session.add(participant)
        db.session.commit()

    return render_template(
        "videoconference/room.html",
        room=room,
        user=current_user,
        participant=participant,
    )


@bp.route("/room/<token>/close", methods=["POST"])
@login_required
def close_room(token):
    """
    Ferme une salle de visioconférence.

    Cette route est utilisée pour fermer une salle de visioconférence.
    Elle attend une requête POST.

    Args:
        token (str): Le token unique de la salle à fermer.

    Retourne:
        Une réponse JSON contenant les informations suivantes :
        - success (bool): Indique si la requête a été effectuée avec succès.
        - error (str): Message d'erreur si la requête a échoué.

    Exemple de requête JSON :
    {
        "token": "token_de_la_salle"
    }

    Exemple de réponse JSON :
    {
        "success": true
    }
    """
    room = Room.query.filter_by(room_token=token).first_or_404()

    # Vérifier que l'utilisateur est l'hôte ou un admin
    if room.host_id != current_user.id and not current_user.is_admin:
        return jsonify({"error": "Seul l'hôte peut fermer la salle"}), 403

    try:
        # Marquer la salle comme inactive
        room.is_active = False

        # Enregistrer l'activité
        activity = RoomActivityLog(
            room_id=room.id,
            user_id=current_user.id,
            action="room_closed",
            details=f"Salle fermée par {current_user.email}",
        )
        db.session.add(activity)

        db.session.commit()

        return jsonify({"success": True, "message": "Salle fermée avec succès"})

    except Exception as e:
        db.session.rollback()
        logging.error(f"Erreur fermeture salle: {str(e)}")
        return jsonify({"error": "Erreur lors de la fermeture de la salle"}), 500


@bp.route("/room/<token>/participants", methods=["GET"])
@login_required
def list_participants(token):
    """
    Liste les participants d'une salle.

    Cette route retourne les informations sur les participants d'une salle
    donnée. Elle attend une requête GET avec le token de la salle en paramètre.

    Args:
        token (str): Token unique de la salle.

    Returns:
        Une réponse JSON contenant les informations suivantes :
        - participants (list): Liste des participants de la salle, chaque élément
          de la liste est un dictionnaire avec les informations suivantes :
          - id (int): Identifiant unique du participant
          - nom (str): Nom du participant
          - prenom (str): Prénom du participant
          - email (str): Adresse e-mail du participant
          - photo_profil (str): Chemin vers la photo de profil du participant

    Exemple de réponse JSON :
    {
        "participants": [
            {
                "id": 1,
                "nom": "Doe",
                "prenom": "John",
                "email": "john.doe@example.com",
                "photo_profil": "/static/photos/profil/john_doe.png"
            },
            {
                "id": 2,
                "nom": "Smith",
                "prenom": "Jane",
                "email": "jane.smith@example.com",
                "photo_profil": "/static/photos/profil/jane_smith.png"
            }
        ]
    }
    """
    room = Room.query.filter_by(room_token=token).first_or_404()

    # Vérifier que l'utilisateur a accès à cette salle
    if not (room.host_id == current_user.id or current_user.is_admin):
        abort(403, "Accès non autorisé")

    participants = RoomParticipant.query.filter_by(room_id=room.id).all()

    return jsonify(
        [
            {
                "id": p.user.id,
                "name": f"{p.user.prenom} {p.user.nom}",
                "role": p.role,
                "joined_at": p.joined_at.isoformat(),
                "left_at": p.left_at.isoformat() if p.left_at else None,
            }
            for p in participants
        ]
    )


@bp.route("/room", methods=["GET"])
@login_required
def room():
    """
    Route principale pour entrer dans une salle de visioconférence.
    Gère la création automatique pour les enseignants et l'accès pour les étudiants.
    """
    room_token = request.args.get("token")

    # Si l'utilisateur est un enseignant
    if current_user.role == "enseignant":
        course_id = request.args.get("course_id")

        if not course_id:
            flash("ID de cours manquant", "error")
            return redirect(url_for("enseignants.dashboard"))

        # Vérifier si l'utilisateur est bien un enseignant
        enseignant = Enseignant.query.filter_by(user_id=current_user.id).first()
        if not enseignant:
            flash("Profil enseignant non trouvé", "error")
            return redirect(url_for("enseignants.dashboard"))

        # Vérifier si le cours appartient bien à l'enseignant
        course = Matiere.query.filter_by(
            id=course_id, enseignant_id=enseignant.id
        ).first()
        if not course:
            flash("Cours non trouvé ou accès non autorisé", "error")
            return redirect(url_for("enseignants.dashboard"))

        # Vérifier si une salle existe déjà pour ce cours aujourd'hui
        today = datetime.now().date()
        room_obj = Room.query.filter(
            Room.course_id == course_id,
            func.date(Room.created_at) == today,
            Room.is_active,
        ).first()

        # Créer une nouvelle salle si elle n'existe pas
        if not room_obj:
            room_obj = Room(
                name=f"Salle {course.nom} - {today.strftime('%d/%m/%Y')}",
                created_by=current_user.id,
                course_id=course_id,
                host_id=current_user.id,
                room_token=secrets.token_urlsafe(16),
            )

            db.session.add(room_obj)
            db.session.commit()

        # Envoyer les invitations aux étudiants inscrits
        try:
            result = send_room_invitations(room_obj.id, current_app)
            if result.get("success"):
                flash(f"Salle créée avec succès. {result['message']}", "success")
            else:
                flash(
                    f"La salle a été créée mais des erreurs sont survenues lors de l'envoi des invitations: {result.get('message', 'Erreur inconnue')}",
                    "warning",
                )
        except Exception as e:
            current_app.logger.error(
                f"Erreur lors de l'envoi des invitations: {str(e)}"
            )
            flash("Erreur lors de l'envoi des invitations.", "warning")

        # Enregistrer la participation de l'enseignant comme hôte
        participation = RoomParticipant.query.filter_by(
            room_id=room_obj.id, user_id=current_user.id
        ).first()

        if not participation:
            participation = RoomParticipant(
                room_id=room_obj.id,
                user_id=current_user.id,
                joined_at=datetime.utcnow(),
                role="enseignant",
            )
            db.session.add(participation)
            db.session.commit()

        return render_template(
            "videoconference/room.html",
            room=room_obj,
            user=current_user,
            course=course,
            is_teacher=True,
        )

    # Si l'utilisateur est un étudiant avec un token
    elif room_token and current_user.role == "etudiant":
        room_obj = Room.query.filter_by(room_token=room_token).first()

        if not room_obj:
            flash("Salle de cours introuvable ou expirée", "error")
            return redirect(url_for("students.etudiant_dashboard"))

        # Récupérer les informations du cours
        course = Matiere.query.get(room_obj.course_id)
        if not course:
            flash("Cours introuvable", "error")
            return redirect(url_for("students.etudiant_dashboard"))

        # Récupérer l'étudiant
        etudiant = Etudiant.query.filter_by(user_id=current_user.id).first()
        if not etudiant:
            flash("Profil étudiant introuvable", "error")
            return redirect(url_for("students.etudiant_dashboard"))

        # Vérifier si la matière est dans l'emploi du temps de la filière de l'étudiant
        filiere = Filiere.query.filter_by(nom=etudiant.filiere).first()
        if not filiere:
            flash("Filière introuvable", "error")
            return redirect(url_for("students.etudiant_dashboard"))

        # Vérifier si le cours est dans l'emploi du temps de cette filière
        emploi = EmploiTemps.query.filter_by(
            filiere_id=filiere.id, matiere_id=room_obj.course_id
        ).first()

        if not emploi:
            flash("Vous n'êtes pas inscrit à ce cours", "error")
            return redirect(url_for("students.etudiant_dashboard"))

        # Enregistrer la participation de l'étudiant
        participation = RoomParticipant.query.filter_by(
            room_id=room_obj.id, user_id=current_user.id
        ).first()

        if not participation:
            participation = RoomParticipant(
                room_id=room_obj.id,
                user_id=current_user.id,
                joined_at=datetime.utcnow(),
                role="etudiant",
            )
            db.session.add(participation)

        # Marquer l'invitation comme acceptée
        invitation = RoomInvitation.query.filter_by(
            room_id=room_obj.id, user_id=current_user.id
        ).first()

        if invitation and invitation.status != "accepted":
            invitation.status = "accepted"
            invitation.accepted_at = datetime.utcnow()

        db.session.commit()

        return render_template(
            "videoconference/room.html",
            room=room_obj,
            user=current_user,
            course=course,
            is_teacher=False,
        )

    # Accès non autorisé
    flash("Accès non autorisé à la salle de visioconférence", "error")
    return redirect(url_for("main.index"))
