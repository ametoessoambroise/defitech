from flask import Blueprint, render_template, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timedelta

from app.extensions import db
from app.models.etudiant import Etudiant
from app.models.note import Note
from app.models.presence import Presence
from app.models.notification import Notification
from app.models.devoir import Devoir
from app.models.devoir_vu import DevoirVu
from app.models.emploi_temps import EmploiTemps
from app.models.filiere import Filiere
from app.models.matiere import Matiere

students_bp = Blueprint("students", __name__, url_prefix="/etudiant")


@students_bp.route("/dashboard")
@login_required
def dashboard():
    """
    Fonction qui rend la page de dashboard de l'étudiant.
    """

    if current_user.role != "etudiant":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("main.index"))

    etudiant = Etudiant.query.filter_by(user_id=current_user.id).first()
    if not etudiant:
        flash("Profil étudiant non trouvé. Contactez l'administration.", "error")
        return redirect(url_for("auth.logout"))

    # Récupérer les notes de l'étudiant
    notes = Note.query.filter_by(etudiant_id=etudiant.id).all()

    # Calcul de la présence (défensif : afficher 0.0% si pas de cours enregistrés)
    total_cours = Presence.query.filter_by(etudiant_id=etudiant.id).count()
    total_present = Presence.query.filter_by(
        etudiant_id=etudiant.id, present=True
    ).count()
    presence = round((total_present / total_cours) * 100, 1) if total_cours > 0 else 0.0

    # Notifications récentes
    notifications = (
        Notification.query.filter_by(user_id=current_user.id)
        .order_by(Notification.date_created.desc())
        .limit(5)
        .all()
    )

    # Nombre de devoirs à faire
    devoirs_count = Devoir.query.filter_by(
        filiere=etudiant.filiere, annee=etudiant.annee
    ).count()

    # Emploi du temps du jour

    # Mapper le jour anglais vers le libellé français utilisé dans EmploiTemps
    day_map = {
        "Monday": "Lundi",
        "Tuesday": "Mardi",
        "Wednesday": "Mercredi",
        "Thursday": "Jeudi",
        "Friday": "Vendredi",
        "Saturday": "Samedi",
        "Sunday": "Dimanche",
    }
    today_en = datetime.now().strftime("%A")  # Nom du jour en anglais
    today = day_map.get(today_en, today_en)
    filiere_obj = Filiere.query.filter_by(nom=etudiant.filiere).first()
    if filiere_obj:
        emploi_temps = EmploiTemps.query.filter_by(
            filiere_id=filiere_obj.id, jour=today
        ).all()
    else:
        emploi_temps = []

    # Calculer la moyenne de manière défensive (None si pas de notes)
    if notes and len(notes) > 0:
        # Utiliser 0 pour les notes manquantes si jamais note.note est None
        total_notes = sum([(n.note or 0) for n in notes])
        average = round(total_notes / len(notes), 2)
    else:
        average = None

    return render_template(
        "etudiant/dashboard.html",
        etudiant=etudiant,
        notes=notes,
        average=average,
        presence=presence,
        notifications=notifications,
        devoirs_count=devoirs_count,
        emploi_temps=emploi_temps,
    )


@students_bp.route("/voir_notes")
@login_required
def voir_notes():
    """
    Permet à l'étudiant de consulter ses notes.
    """

    if current_user.role != "etudiant":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("main.index"))

    # Récupérer le profil et les notes
    etudiant = Etudiant.query.filter_by(user_id=current_user.id).first()
    if not etudiant:
        flash("Profil étudiant introuvable.", "error")
        return redirect(url_for("main.index"))

    notes = (
        Note.query.filter_by(etudiant_id=etudiant.id)
        .order_by(Note.date_evaluation.desc())
        .all()
    )

    # Résoudre les noms de matière pour l'affichage (matiere peut être None)
    notes_display = []
    for n in notes:
        matiere = None
        if n.matiere_id:
            try:
                matiere = Matiere.query.get(n.matiere_id)
            except Exception:
                matiere = None
        notes_display.append(
            {
                "matiere": matiere.nom if matiere else "-",
                "type": n.type_evaluation or "-",
                "note": n.note if n.note is not None else "-",
                "date": n.date_evaluation,
            }
        )

    return render_template("etudiant/voir_notes.html", notes=notes_display)


@students_bp.route("/emploi-temps")
@login_required
def emploi_temps():
    """
    Fonction qui rend la page de l'emploi du temps de l'étudiant.
    """
    if current_user.role != "etudiant":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("main.index"))
    # Passer timedelta au template pour les expressions Jinja comme
    # `(now + timedelta(days=4)).strftime('%d/%m/%Y')`
    return render_template("etudiant/emploi_temps.html", timedelta=timedelta)


@students_bp.route("/devoirs")
@login_required
def devoirs():
    """
    Fonction qui rend la page de devoirs de l'étudiant.
    """
    if current_user.role != "etudiant":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("main.index"))

    etudiant = Etudiant.query.filter_by(user_id=current_user.id).first()
    devoirs = (
        Devoir.query.filter_by(filiere=etudiant.filiere, annee=etudiant.annee)
        .order_by(Devoir.date_creation.desc())
        .all()
    )
    notifications = (
        Notification.query.filter_by(user_id=current_user.id, is_read=False)
        .order_by(Notification.date_created.desc())
        .all()
    )

    return render_template(
        "etudiant/devoirs.html", devoirs=devoirs, notifications=notifications
    )


@students_bp.route("/notification/lue/<int:notif_id>")
@login_required
def marquer_notification_lue(notif_id):
    """
    Fonction qui marque une notification comme lue.
    """
    notif = Notification.query.get_or_404(notif_id)
    if notif.user_id != current_user.id:
        flash("Accès non autorisé.", "error")
        return redirect(url_for("students.devoirs"))
    notif.is_read = True
    db.session.commit()
    return redirect(url_for("students.devoirs"))


@students_bp.route("/devoir/<int:devoir_id>")
@login_required
def voir_devoir(devoir_id):
    """
    Fonction qui affiche la page permettant d'afficher un devoir.
    """

    devoir = Devoir.query.get_or_404(devoir_id)
    etudiant = Etudiant.query.filter_by(user_id=current_user.id).first()
    # Vérifier que l'étudiant a le droit de voir ce devoir
    if devoir.filiere != etudiant.filiere or devoir.annee != etudiant.annee:
        flash("Accès non autorisé à ce devoir.", "error")
        return redirect(url_for("students.devoirs"))
    # Accusé de réception (marquer comme vu)
    vu = DevoirVu.query.filter_by(devoir_id=devoir.id, etudiant_id=etudiant.id).first()
    if not vu:
        vu = DevoirVu(devoir_id=devoir.id, etudiant_id=etudiant.id)
        db.session.add(vu)
        db.session.commit()
    return render_template("etudiant/voir_devoir.html", devoir=devoir)


@students_bp.route("/api/emploi-temps", methods=["GET"])
@login_required
def api_etudiant_emploi_temps():
    """
    Fonction qui retourne l'emploi du temps de l'étudiant connecté au format JSON.
    """
    if current_user.role != "etudiant":
        return jsonify({"error": "Accès non autorisé"}), 403

    etudiant = Etudiant.query.filter_by(user_id=current_user.id).first()
    if not etudiant:
        return jsonify({"error": "Profil étudiant introuvable"}), 404

    filiere_obj = Filiere.query.filter_by(nom=etudiant.filiere).first()
    if not filiere_obj:
        return jsonify({"jours": [], "horaires": [], "creneaux": []})

    jours = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi"]

    # Définition des créneaux fixes (Cours et Pauses)
    horaire_config = [
        {"label": "07:00 - 10:00", "type": "cours"},
        {"label": "10:00 - 10:30", "type": "pause", "nom": "Récréation"},
        {"label": "10:30 - 12:30", "type": "cours"},
        {"label": "12:30 - 13:30", "type": "pause", "nom": "Déjeuner"},
        {"label": "13:30 - 15:30", "type": "cours"},
        {"label": "15:30 - 16:00", "type": "pause", "nom": "Pause"},
        {"label": "16:00 - 18:00", "type": "cours"},
    ]

    emplois = EmploiTemps.query.filter_by(filiere_id=filiere_obj.id).all()

    def format_label(emploi):
        hd = emploi.heure_debut
        hf = emploi.heure_fin
        if isinstance(hd, str):
            hd_h, hd_m = map(int, hd.split(":")[:2])
        else:
            hd_h, hd_m = hd.hour, hd.minute
        if isinstance(hf, str):
            hf_h, hf_m = map(int, hf.split(":")[:2])
        else:
            hf_h, hf_m = hf.hour, hf.minute
        return f"{hd_h:02d}:{hd_m:02d} - {hf_h:02d}:{hf_m:02d}"

    creneaux_json = []
    for e in emplois:
        if not e.heure_debut or not e.heure_fin:
            continue
        label = format_label(e)
        matiere = Matiere.query.get(e.matiere_id) if e.matiere_id else None
        enseignant_nom = None
        if matiere and matiere.enseignant and matiere.enseignant.user:
            enseignant_nom = (
                f"{matiere.enseignant.user.nom} {matiere.enseignant.user.prenom}"
            )

        creneaux_json.append(
            {
                "jour": e.jour,
                "horaire": label,
                "matiere": matiere.nom if matiere else None,
                "enseignant": enseignant_nom,
                "salle": e.salle,
                "type": "cours",
            }
        )

    return jsonify(
        {
            "jours": jours,
            "horaires": [h["label"] for h in horaire_config],
            "horaire_config": horaire_config,
            "creneaux": creneaux_json,
        }
    )
