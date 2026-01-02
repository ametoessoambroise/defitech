from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
)
from flask_login import login_required, current_user
from datetime import datetime
import json
from datetime import date, timedelta

from app.extensions import db
from app.models.user import User
from app.models.enseignant import Enseignant
from app.models.etudiant import Etudiant
from app.models.matiere import Matiere
from app.models.emploi_temps import EmploiTemps
from app.models.filiere import Filiere
from app.models.devoir import Devoir
from app.models.devoir_vu import DevoirVu
from app.models.notification import Notification
from app.models.presence import Presence
from app.models.note import Note

teachers_bp = Blueprint("teachers", __name__, url_prefix="/enseignant")


@teachers_bp.route("/dashboard")
@login_required
def dashboard():
    """
    Route pour afficher le tableau de bord de l'enseignant.
    """
    if current_user.role != "enseignant":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("main.index"))

    enseignant = Enseignant.query.filter_by(user_id=current_user.id).first()
    if not enseignant:
        flash("Profil enseignant non trouvé.", "error")
        return redirect(url_for("main.index"))

    # Matières enseignées
    matieres = Matiere.query.filter_by(enseignant_id=enseignant.id).all()

    # Étudiants (tous ceux des filières/années enseignées)
    filieres = []
    annees = []
    if enseignant.filieres_enseignees:
        try:
            data = json.loads(enseignant.filieres_enseignees)
            filieres = data.get("filieres", [])
            annees = data.get("annees", [])
        except Exception:
            pass

    etudiants_count = 0
    if filieres and annees:
        etudiants_count = Etudiant.query.filter(
            Etudiant.filiere.in_(filieres), Etudiant.annee.in_(annees)
        ).count()

    # Cours aujourd'hui (emploi du temps)

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
    today_en = datetime.now().strftime("%A")
    today = day_map.get(today_en, today_en)

    # On récupère tous les emplois du temps du jour pour cet enseignant
    cours_aujourdhui = (
        EmploiTemps.query.join(Matiere, EmploiTemps.matiere_id == Matiere.id)
        .join(Enseignant, Matiere.enseignant_id == Enseignant.id)
        .join(User, Enseignant.user_id == User.id)
        .join(Filiere, EmploiTemps.filiere_id == Filiere.id)
        .filter(EmploiTemps.jour == today, User.nom == enseignant.user.nom)
        .order_by(EmploiTemps.heure_debut)
        .all()
    )
    cours_aujourdhui_count = len(cours_aujourdhui)

    # Devoirs à corriger (devoirs de l'enseignant avec fichier uploadé par les étudiants)
    devoirs_a_corriger = (
        Devoir.query.filter_by(enseignant_id=enseignant.id)
        .filter(Devoir.fichier is not None)
        .count()
    )

    # Notifications récentes
    notifications = (
        Notification.query.filter_by(user_id=current_user.id)
        .order_by(Notification.date_created.desc())
        .limit(5)
        .all()
    )

    # Prendre la première matière si elle existe
    matiere_courante = matieres[0] if matieres else None

    return render_template(
        "enseignant/dashboard.html",
        matieres=matieres,
        matiere=matiere_courante,  # Ajout de la matière courante
        enseignant=enseignant,
        etudiants_count=etudiants_count,
        cours_aujourdhui_count=cours_aujourdhui_count,
        devoirs_a_corriger=devoirs_a_corriger,
        cours_aujourdhui=cours_aujourdhui,
        notifications=notifications,
    )


@teachers_bp.route("/cours-aujourdhui")
@login_required
def cours_aujourdhui():
    """
    Fonction qui affiche la liste des cours de l'enseignant de l'utilisateur actuel
    qui ont lieu aujourd'hui.
    """

    if current_user.role != "enseignant":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("main.index"))
    enseignant = Enseignant.query.filter_by(user_id=current_user.id).first()
    if not enseignant:
        flash("Profil enseignant non trouvé.", "error")
        return redirect(url_for("main.index"))

    day_map = {
        "Monday": "Lundi",
        "Tuesday": "Mardi",
        "Wednesday": "Mercredi",
        "Thursday": "Jeudi",
        "Friday": "Vendredi",
        "Saturday": "Samedi",
        "Sunday": "Dimanche",
    }
    today_en = datetime.now().strftime("%A")
    today = day_map.get(today_en, today_en)

    # Même logique que sur le dashboard : tous les cours du jour pour cet enseignant
    cours_aujourdhui = (
        EmploiTemps.query.join(Matiere, EmploiTemps.matiere_id == Matiere.id)
        .join(Enseignant, Matiere.enseignant_id == Enseignant.id)
        .join(User, Enseignant.user_id == User.id)
        .join(Filiere, EmploiTemps.filiere_id == Filiere.id)
        .filter(EmploiTemps.jour == today, User.nom == enseignant.user.nom)
        .order_by(EmploiTemps.heure_debut)
        .all()
    )
    return render_template(
        "enseignant/cours_aujourdhui.html", cours_aujourdhui=cours_aujourdhui
    )


@teachers_bp.route("/notes", methods=["GET", "POST"])
@login_required
def notes():
    """
    Permet à l'enseignant de consulter les notes de ses étudiants.
    """

    if current_user.role != "enseignant":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("main.index"))

    enseignant = Enseignant.query.filter_by(user_id=current_user.id).first()
    try:
        data = json.loads(enseignant.filieres_enseignees)
        filieres = data.get("filieres", [])
        annees = data.get("annees", [])
    except Exception:
        filieres = []
        annees = []

    etudiants = Etudiant.query.filter(
        Etudiant.filiere.in_(filieres), Etudiant.annee.in_(annees)
    ).all()

    matieres = Matiere.query.filter_by(enseignant_id=enseignant.id).all()

    # Récupérer les notes existantes pour pré-remplir le formulaire
    notes_existantes = {}
    dates_evaluations = {}
    for matiere in matieres:
        notes_matiere = Note.query.filter_by(matiere_id=matiere.id).all()
        for note in notes_matiere:
            key = f"{note.etudiant_id}_{matiere.id}_{note.type_evaluation}"
            notes_existantes[key] = note.note

            # Récupérer la date d'évaluation pour cette matière et ce type
            date_key = f"{matiere.id}_{note.type_evaluation}"
            if date_key not in dates_evaluations:
                dates_evaluations[date_key] = (
                    note.date_evaluation.strftime("%Y-%m-%d")
                    if note.date_evaluation
                    else ""
                )

    if request.method == "POST":
        etudiant_id = request.form["etudiant_id"]
        matiere_id = request.form["matiere_id"]
        type_eval = request.form["type_eval"]  # 'devoir', 'examen' ou 'TP
        note_val = float(request.form["note"])

        etu = Etudiant.query.get(etudiant_id)
        if etu.filiere not in filieres or etu.annee not in annees:
            flash("Vous n'avez pas le droit de modifier cette note.", "error")
            return redirect(url_for("teachers.notes"))

        note = Note.query.filter_by(
            etudiant_id=etudiant_id, matiere_id=matiere_id, type_evaluation=type_eval
        ).first()
        if note:
            note.note = note_val
        else:
            note = Note(
                etudiant_id=etudiant_id,
                matiere_id=matiere_id,
                type_evaluation=type_eval,
                note=note_val,
            )
            db.session.add(note)
        db.session.commit()
        flash("Note enregistrée.", "success")
        return redirect(url_for("teachers.notes"))

    return render_template(
        "enseignant/notes.html",
        etudiants=etudiants,
        matieres=matieres,
        notes_existantes=notes_existantes,
        dates_evaluations=dates_evaluations,
    )


@teachers_bp.route("/devoirs", methods=["GET", "POST"])
@login_required
def devoirs():
    """
    Permet à l'enseignant de consulter et de gérer les devoirs de ses étudiants.
    """
    if current_user.role != "enseignant":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("main.index"))

    enseignant = Enseignant.query.filter_by(user_id=current_user.id).first()
    try:
        data = json.loads(enseignant.filieres_enseignees)
        filieres = data.get("filieres", [])
        annees = data.get("annees", [])
    except Exception:
        filieres = []
        annees = []

    if request.method == "POST":
        titre = request.form["titre"]
        description = request.form["description"]
        type_devoir = request.form["type"]
        filiere = request.form["filiere"]
        annee = request.form["annee"]
        date_limite = request.form.get("date_limite")

        # Cloudinary File Handling
        file_url = request.form.get("file_url")
        # original_filename = request.form.get("original_filename") # Optionnel si on veut stocker le nom d'origine

        # Création du devoir
        devoir = Devoir(
            titre=titre,
            description=description,
            type=type_devoir,
            filiere=filiere,
            annee=annee,
            enseignant_id=enseignant.id,
            date_limite=date_limite if date_limite else None,
            fichier=file_url,  # Stocke l'URL Cloudinary directement
        )
        db.session.add(devoir)
        db.session.commit()
        # Notifier tous les étudiants concernés
        etudiants = Etudiant.query.filter_by(filiere=filiere, annee=annee).all()
        for etu in etudiants:
            Notification.creer_notification(
                user_id=etu.user_id,
                titre=f"Nouveau {type_devoir}",
                message=f"Sujet : {titre} - {filiere} {annee}",
                type="info",
            )
        db.session.commit()
        flash(
            f"{type_devoir.capitalize()} envoyé à tous les étudiants de {filiere} {annee}.",
            "success",
        )
        return redirect(url_for("teachers.devoirs"))

    return render_template("enseignant/devoirs.html", filieres=filieres, annees=annees)

@teachers_bp.route("/emploi-temps")
@login_required
def emploi_temps():
    """Page d'accès à l'emploi du temps de l'enseignant.

    La page est remplie côté client via l'API JSON correspondante.
    """
    if current_user.role != "enseignant":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("main.index"))

    enseignant = Enseignant.query.filter_by(user_id=current_user.id).first()
    if not enseignant:
        flash("Aucun profil enseignant trouvé.", "error")
        return redirect(url_for("teachers.dashboard"))

    return render_template("enseignant/emploi_temps.html")


@teachers_bp.route("/api/emploi-temps", methods=["GET"])
@login_required
def api_emploi_temps():
    """Récupère les emplois du temps de l'enseignant courant en JSON."""
    if current_user.role != "enseignant":
        flash("Accès non autorisé.", "error")
        return jsonify({"error": "Accès non autorisé"}), 403

    enseignant = Enseignant.query.filter_by(user_id=current_user.id).first()
    if not enseignant:
        flash("Profil enseignant introuvable.", "error")
        return jsonify({"error": "Profil enseignant introuvable"}), 404

    filieres = []
    annees = []
    try:
        data = json.loads(enseignant.filieres_enseignees)
        filieres = data.get("filieres", [])
        annees = data.get("annees", [])
    except Exception:
        pass

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

    if not filieres or not annees:
        return jsonify(
            {
                "jours": jours,
                "horaires": [h["label"] for h in horaire_config],
                "horaire_config": horaire_config,
                "creneaux": [],
            }
        )

    filiere_ids = [
        Filiere.query.filter_by(nom=f).first().id
        for f in filieres
        if Filiere.query.filter_by(nom=f).first()
    ]

    emplois = (
        EmploiTemps.query.join(Matiere, EmploiTemps.matiere_id == Matiere.id)
        .filter(
            EmploiTemps.filiere_id.in_(filiere_ids),
            Matiere.enseignant_id == enseignant.id,
        )
        .all()
    )

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

        creneaux_json.append(
            {
                "jour": e.jour,
                "horaire": label,
                "matiere": matiere.nom if matiere else None,
                "filiere": e.filiere.nom if e.filiere else "Inconnue",
                "annee": matiere.annee if matiere else "N/A",
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


@teachers_bp.route("/presence", methods=["GET", "POST"])
@login_required
def presence():
    """Page de gestion des présences pour les enseignants."""
    if current_user.role != "enseignant":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("main.index"))

    enseignant = Enseignant.query.filter_by(user_id=current_user.id).first()
    if not enseignant:
        flash("Profil enseignant non trouvé.", "error")
        return redirect(url_for("main.index"))

    filieres = []
    annees = []
    if enseignant.filieres_enseignees:
        try:
            data = json.loads(enseignant.filieres_enseignees)
            filieres = data.get("filieres", [])
            annees = data.get("annees", [])
        except Exception:
            pass

    matieres = Matiere.query.filter_by(enseignant_id=enseignant.id).all()

    selected_filiere = request.values.get("filiere")
    selected_annee = request.values.get("annee")
    selected_matiere = request.values.get("matiere", type=int)
    selected_date = request.values.get("date")

    etudiants = []

    if selected_filiere and selected_annee and selected_matiere and selected_date:
        matiere_obj = Matiere.query.get(selected_matiere)
        if matiere_obj and matiere_obj.filiere_id:
            filiere_obj = Filiere.query.get(matiere_obj.filiere_id)
            if filiere_obj and filiere_obj.nom in filieres:
                etudiants = Etudiant.query.filter_by(
                    filiere=filiere_obj.nom, annee=selected_annee
                ).all()

                if request.method == "POST":
                    from datetime import datetime as _dt

                    date_presence = _dt.strptime(selected_date, "%Y-%m-%d").date()
                    for etu in etudiants:
                        present = f"present_{etu.id}" in request.form
                        presence_rec = Presence.query.filter_by(
                            etudiant_id=etu.id,
                            matiere_id=selected_matiere,
                            date_presence=date_presence,
                        ).first()
                        if presence_rec:
                            presence_rec.present = present
                        else:
                            presence_rec = Presence(
                                etudiant_id=etu.id,
                                matiere_id=selected_matiere,
                                date_presence=date_presence,
                                present=present,
                            )
                            db.session.add(presence_rec)
                    db.session.commit()
                    flash("Présences enregistrées avec succès.", "success")
                    return redirect(request.url)

    return render_template(
        "enseignant/presence.html",
        filieres=filieres,
        annees=annees,
        matieres=matieres,
        selected_filiere=selected_filiere,
        selected_annee=selected_annee,
        selected_matiere=selected_matiere,
        selected_date=selected_date,
        etudiants=etudiants,
    )


@teachers_bp.route("/devoirs-a-corriger")
@login_required
def devoirs_a_corriger():
    """
    Permet à l'enseignant de consulter les devoirs à corriger.
    """
    if current_user.role != "enseignant":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("main.index"))
    enseignant = Enseignant.query.filter_by(user_id=current_user.id).first()
    if not enseignant:
        flash("Profil enseignant non trouvé.", "error")
        return redirect(url_for("main.index"))
    # On récupère tous les devoirs de l'enseignant avec un fichier uploadé
    devoirs = (
        Devoir.query.filter_by(enseignant_id=enseignant.id)
        .filter(Devoir.fichier is not None)
        .all()
    )
    # Pour chaque devoir, on cherche l'étudiant qui a uploadé (si possible)
    devoirs_info = []
    for d in devoirs:
        # On suppose que le nom du fichier est unique par étudiant
        etudiant = None
        if d.fichier:
            # On tente de retrouver l'étudiant par le nom du fichier si possible
            etudiant = Etudiant.query.filter(
                Etudiant.user_id == d.enseignant_id
            ).first()
        devoirs_info.append(
            {"devoir": d, "nom_fichier": d.fichier, "etudiant": etudiant}
        )
    return render_template(
        "enseignant/devoirs_a_corriger.html", devoirs_info=devoirs_info
    )


@teachers_bp.route("/devoir/vus/<int:devoir_id>")
@login_required
def devoir_vus(devoir_id):
    """
    Permet à l'enseignant de consulter les étudiants qui ont consulté un devoir.
    """
    if current_user.role != "enseignant":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("teachers.devoirs"))
    devoir = Devoir.query.get_or_404(devoir_id)
    if (
        devoir.enseignant_id
        != Enseignant.query.filter_by(user_id=current_user.id).first().id
    ):
        flash("Vous ne pouvez voir que vos propres devoirs.", "error")
        return redirect(url_for("teachers.devoirs"))
    vus = DevoirVu.query.filter_by(devoir_id=devoir_id).all()
    return render_template("enseignant/devoir_vus.html", devoir=devoir, vus=vus)


@teachers_bp.route("/mes-etudiants")
@login_required
def manage_etudiants():
    """
    Permet à l'enseignant de consulter les étudiants inscrits dans les filières et années qu'il enseigne.
    """
    if current_user.role != "enseignant":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("main.index"))

    enseignant = Enseignant.query.filter_by(user_id=current_user.id).first()
    if not enseignant:
        flash("Profil enseignant non trouvé.", "error")
        return redirect(url_for("main.index"))

    # Récupérer les filières et années enseignées
    filieres = []
    annees = []
    if enseignant.filieres_enseignees:
        try:
            data = json.loads(enseignant.filieres_enseignees)
            filieres = data.get("filieres", [])
            annees = data.get("annees", [])
        except Exception:
            pass

    if not filieres or not annees:
        flash("Aucune filière ou année assignée.", "warning")
        return render_template("enseignant/mes_etudiants.html", etudiants_data=[])

    # Récupérer les étudiants des filières/années enseignées
    etudiants = Etudiant.query.filter(
        Etudiant.filiere.in_(filieres), Etudiant.annee.in_(annees)
    ).all()

    # Récupérer les matières de l'enseignant
    matieres = Matiere.query.filter_by(enseignant_id=enseignant.id).all()
    matiere_id_defaut = matieres[0].id if matieres else 1

    # Préparer les données pour le template
    etudiants_data = []
    for etudiant in etudiants:
        user = User.query.get(etudiant.user_id)
        if user:
            etudiants_data.append((user, etudiant))

    # Statut de présence du jour avec la matière par défaut
    from datetime import date as _date

    today = _date.today()
    presence_status = {}
    for user, etudiant in etudiants_data:
        presence = Presence.query.filter_by(
            etudiant_id=etudiant.id, matiere_id=matiere_id_defaut, date_cours=today
        ).first()
        presence_status[etudiant.id] = bool(presence.present) if presence else False

    return render_template(
        "enseignant/mes_etudiants.html",
        etudiants_data=etudiants_data,
        filieres_enseignees=filieres,
        annees_enseignees=annees,
        presence_status=presence_status,
        matiere_id_defaut=matiere_id_defaut,
    )


@teachers_bp.route("/mes-etudiants/presence", methods=["POST"])
@login_required
def set_etudiant_presence():
    """
    API pour définir la présence d'un étudiant.
    """
    if current_user.role != "enseignant":
        return jsonify({"success": False, "error": "Accès non autorisé"}), 403

    data = request.get_json(silent=True) or {}
    etudiant_id = data.get("etudiant_id")
    present = data.get("present")
    matiere_id = data.get("matiere_id")

    # Here we should implement the presence saving logic
    # Simplified for migration:
    try:
        # Check if presence exists
        presence_record = Presence.query.filter_by(
            etudiant_id=etudiant_id, matiere_id=matiere_id, date_cours=date.today()
        ).first()
        if presence_record:
            presence_record.present = present
        else:

            # Need to get matiere_nom
            matiere = Matiere.query.get(matiere_id)
            new_presence = Presence(
                etudiant_id=etudiant_id,
                matiere_id=matiere_id,
                matiere_nom=matiere.nom if matiere else "Inconnu",
                date_presence=date.today(),
                present=present,
                date_cours=date.today(),
            )
            db.session.add(new_presence)
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@teachers_bp.route("/api/verifier-creneau")
@login_required
def verifier_creneau():
    """
    API pour vérifier si l'enseignant est dans un créneau horaire valide
    """
    if current_user.role != "enseignant":
        flash("Accès non autorisé", "error")
        return jsonify({"valide": False, "message": "Accès non autorisé"}), 403

    matiere_id = request.args.get("matiere_id", type=int)
    if not matiere_id:
        flash("ID de matière manquant", "error")
        return jsonify({"valide": False, "message": "ID de matière manquant"}), 400

    # Récupérer l'enseignant connecté
    enseignant = Enseignant.query.filter_by(user_id=current_user.id).first()
    if not enseignant:
        flash("Profil enseignant non trouvé", "error")
        return (
            jsonify({"valide": False, "message": "Profil enseignant non trouvé"}),
            404,
        )

    # Obtenir le jour actuel en français
    jours_fr = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    jour_actuel = jours_fr[datetime.now().weekday()]  # 0 = Lundi, 1 = Mardi, etc.
    heure_actuelle = datetime.now().time()

    # Trouver le créneau de cours actuel pour cet enseignant et cette matière
    creneau = EmploiTemps.query.filter(
        EmploiTemps.enseignant_id == enseignant.id,
        EmploiTemps.matiere_id == matiere_id,
        EmploiTemps.jour == jour_actuel,
        EmploiTemps.heure_debut <= heure_actuelle,
        EmploiTemps.heure_fin >= heure_actuelle,
    ).first()

    if not creneau:
        flash("Aucun cours prévu à cette heure", "error")
        return jsonify({"valide": False, "message": "Aucun cours prévu à cette heure"})

    # Vérifier si on est dans la plage horaire autorisée (15 minutes avant/après le cours)
    marge = 15  # minutes
    debut_autorise = (
        datetime.combine(date.today(), creneau.heure_debut) - timedelta(minutes=marge)
    ).time()
    fin_autorisee = (
        datetime.combine(date.today(), creneau.heure_fin) + timedelta(minutes=marge)
    ).time()

    if not (debut_autorise <= heure_actuelle <= fin_autorisee):
        flash("Hors créneau autorisé", "error")
        return jsonify(
            {
                "valide": False,
                "message": f"Hors créneau autorisé (entre {debut_autorise.strftime('%H:%M')} et {fin_autorisee.strftime('%H:%M')})",
                "creneau": {
                    "heure_debut": creneau.heure_debut.strftime("%H:%M"),
                    "heure_fin": creneau.heure_fin.strftime("%H:%M"),
                    "salle": creneau.salle,
                },
            }
        )

    flash("Créneau valide", "success")

    return jsonify(
        {
            "valide": True,
            "message": f"Créneau valide - Salle: {creneau.salle}",
            "creneau": {
                "heure_debut": creneau.heure_debut.strftime("%H:%M"),
                "heure_fin": creneau.heure_fin.strftime("%H:%M"),
                "salle": creneau.salle,
            },
        }
    )
