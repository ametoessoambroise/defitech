"""
AI-Powered Study Planner for DEFITECH
Smart scheduling and personalized study recommendations
Version améliorée avec parsing JSON robuste
"""

from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from sqlalchemy import func
from functools import wraps
import requests
import json
import re
import os
from app.extensions import db
from app.models.etudiant import Etudiant
from app.models.note import Note
from app.models.devoir import Devoir
from app.models.devoir_vu import DevoirVu
from app.models.matiere import Matiere
from app.models.presence import Presence
from app.models.pomodoro_session import PomodoroSession
from flask import current_app

# Configuration API Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key="
    + GEMINI_API_KEY
)


study_planner_bp = Blueprint("study_planner", __name__, url_prefix="/study-planner")


def student_required(f):
    """Décorateur pour restreindre l'accès aux étudiants"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash("Vous devez être connecté pour accéder à cette page.", "error")
            return redirect(url_for("auth.login"))
        if current_user.role not in ["etudiant", "admin"]:
            flash("Accès réservé aux étudiants.", "error")
            return redirect(url_for("main.index"))
        return f(*args, **kwargs)

    return decorated_function


def clean_json_response(text):
    """
    Nettoie la réponse de Gemini pour extraire le JSON valide
    Gère les cas: ```json, backticks, texte avant/après le JSON, JSON tronqué
    """
    if not text:
        return None

    # Supprimer les backticks markdown
    text = re.sub(r"```json\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"```\s*", "", text)

    # Nettoyer les caractères problématiques
    text = text.replace("\n", " ")
    text = text.replace("\t", " ")
    text = re.sub(r"\s+", " ", text)  # Réduire les espaces multiples

    # Trouver le premier { et le dernier } pour extraire le JSON
    start = text.find("{")
    end = text.rfind("}")

    if start != -1 and end != -1 and end > start:
        json_text = text[start : end + 1]
        try:
            parsed = json.loads(json_text)
            return parsed
        except json.JSONDecodeError as e:
            current_app.logger.error(f"Erreur parsing JSON: {e}")  # Debug
            # print(f"Texte JSON problématique: {json_text}")  # Debug

            # Tenter de réparer les JSON tronqués ou mal formés
            json_text_fixed = json_text.rstrip()  # Enlever espaces finaux

            # Cas spécial: JSON qui se termine par des guillemets ouverts
            if json_text_fixed.endswith('"'):
                json_text_fixed = json_text_fixed[:-1] + '"'

            # Compter les accolades et crochets pour équilibrer
            open_braces = json_text_fixed.count("{")
            close_braces = json_text_fixed.count("}")
            open_brackets = json_text_fixed.count("[")
            close_brackets = json_text_fixed.count("]")

            # Ajouter les accolades manquantes
            while close_braces < open_braces:
                json_text_fixed += "}"
                close_braces += 1

            # Ajouter les crochets manquants
            while close_brackets < open_brackets:
                json_text_fixed += "]"
                close_brackets += 1

            # Corriger les virgules en trop
            json_text_fixed = json_text_fixed.replace(",}", "}")
            json_text_fixed = json_text_fixed.replace(",]", "]")

            # Cas spécial: si le JSON se termine par une virgule dans un tableau
            if json_text_fixed.rstrip().endswith(","):
                json_text_fixed = json_text_fixed.rstrip()[:-1]

            # Cas spécial: si le JSON se termine par un élément incomplet
            if json_text_fixed.rstrip().endswith('",'):
                # Fermer la chaîne et l'objet/tableau
                json_text_fixed = json_text_fixed.rstrip() + '"'
                # Rééquilibrer après cette modification
                open_braces = json_text_fixed.count("{")
                close_braces = json_text_fixed.count("}")
                open_brackets = json_text_fixed.count("[")
                close_brackets = json_text_fixed.count("]")
                while close_braces < open_braces:
                    json_text_fixed += "}"
                    close_braces += 1
                while close_brackets < open_brackets:
                    json_text_fixed += "]"
                    close_brackets += 1

            # Tenter de parser le JSON corrigé
            try:
                parsed = json.loads(json_text_fixed)
                current_app.logger.info("JSON corrigé et parsé avec succès")  # Debug
                return parsed
            except json.JSONDecodeError as e2:
                current_app.logger.error(f"Erreur parsing JSON corrigé: {e2}")  # Debug

                # Dernière tentative: reconstruire le JSON manuellement
                try:
                    # Trouver la dernière position valide dans le JSON
                    last_valid_pos = -1
                    stack = []

                    for i, char in enumerate(json_text):
                        if char == "{":
                            stack.append("{")
                        elif char == "}":
                            if stack and stack[-1] == "{":
                                stack.pop()
                                last_valid_pos = i
                        elif char == "[":
                            stack.append("[")
                        elif char == "]":
                            if stack and stack[-1] == "[":
                                stack.pop()
                                last_valid_pos = i

                    if last_valid_pos > 0:
                        # Reconstruire jusqu'à la dernière position valide
                        reconstructed = json_text[: last_valid_pos + 1]

                        # Ajouter les fermetures manquantes
                        open_braces = reconstructed.count("{")
                        close_braces = reconstructed.count("}")
                        open_brackets = reconstructed.count("[")
                        close_brackets = reconstructed.count("]")

                        while close_braces < open_braces:
                            reconstructed += "}"
                            close_braces += 1
                        while close_brackets < open_brackets:
                            reconstructed += "]"
                            close_brackets += 1

                        # Corriger les virgules finales
                        reconstructed = reconstructed.replace(",}", "}")
                        reconstructed = reconstructed.replace(",]", "]")

                        parsed = json.loads(reconstructed)
                        current_app.logger.info(
                            "JSON reconstruit et parsé avec succès"
                        )  # Debug
                        return parsed

                except Exception as e3:
                    current_app.logger.error(
                        f"Erreur reconstruction JSON: {e3}"
                    )  # Debug

            # Si tout échoue, essayer de trouver un tableau JSON
            start = text.find("[")
            end = text.rfind("]")
            if start != -1 and end != -1 and end > start:
                json_text = text[start : end + 1]
                try:
                    return json.loads(json_text)
                except json.JSONDecodeError:
                    pass

    print("Impossible de parser le JSON")  # Debug
    return None


def call_gemini_api(prompt, temperature=0.7):
    """
    Appelle l'API Gemini avec un prompt optimisé
    Retourne un dict Python avec la réponse
    """
    try:
        # Vérification de la clé API
        if not GEMINI_API_KEY:
            current_app.logger.error("Clé API Gemini non configurée")
            return {"success": False, "error": "Configuration API manquante"}

        headers = {"Content-Type": "application/json"}

        data = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "topK": 40,
                "topP": 0.95,
                "maxOutputTokens": 4096,
            },
        }

        current_app.logger.info("Envoi de la requête à l'API Gemini...")

        try:
            response = requests.post(
                GEMINI_API_URL, headers=headers, json=data, timeout=30
            )
            current_app.logger.info(f"Réponse reçue : {response.status_code}")

        except requests.exceptions.RequestException as e:
            current_app.logger.error(f"Erreur de connexion à l'API Gemini: {str(e)}")
            return {"success": False, "error": f"Erreur de connexion à l'API: {str(e)}"}

        if response.status_code == 200:
            try:
                result = response.json()
                current_app.logger.info("Réponse JSON parsée avec succès")

                if "candidates" in result and result["candidates"]:
                    candidate = result["candidates"][0]
                    if "content" in candidate and "parts" in candidate["content"]:
                        parts = candidate["content"]["parts"]
                        if parts and "text" in parts[0]:
                            text_response = parts[0]["text"].strip()

                            # Nettoyage de la réponse
                            if text_response.startswith("```json"):
                                text_response = text_response[7:]
                            if text_response.endswith("```"):
                                text_response = text_response[:-3].strip()

                            try:
                                parsed_json = json.loads(text_response)
                                return {"success": True, "data": parsed_json}
                            except json.JSONDecodeError as e:
                                current_app.logger.error(
                                    f"Erreur de parsing JSON: {str(e)}"
                                )
                                return {
                                    "success": False,
                                    "error": "Format de réponse invalide",
                                    "raw_text": text_response,
                                }

                # Si on arrive ici, la structure de la réponse est inattendue
                current_app.logger.error(f"Structure de réponse inattendue: {result}")
                return {
                    "success": False,
                    "error": "Format de réponse inattendu",
                    "raw_response": result,
                }

            except json.JSONDecodeError as e:
                current_app.logger.error(f"Erreur de décodage JSON: {str(e)}")
                return {
                    "success": False,
                    "error": "Réponse invalide de l'API",
                    "raw_response": response.text,
                }

        # Gestion des erreurs HTTP
        error_msg = f"Erreur {response.status_code}"
        if response.status_code == 502:
            error_msg = "Erreur de connexion au service d'IA (502 Bad Gateway)"
        elif response.status_code == 401:
            error_msg = "Clé API invalide ou expirée"
        elif response.status_code == 429:
            error_msg = "Quota de requêtes dépassé"

        current_app.logger.error(f"{error_msg}: {response.text}")
        return {
            "success": False,
            "error": error_msg,
            "status_code": response.status_code,
        }

    except Exception as e:
        current_app.logger.error(f"Erreur inattendue: {str(e)}", exc_info=True)
        return {"success": False, "error": f"Erreur inattendue: {str(e)}"}


@study_planner_bp.route("/")
@login_required
@student_required
def index():
    """
    Affiche la page principale du planificateur d'études.

    Cette fonction est appelée lorsque l'utilisateur accède à l'URL principale du
    planificateur d'études. Elle retourne le template "study_planner/index.html"
    afin d'afficher l'interface utilisateur principale du planificateur.

    Retourne:
        Un objet `flask.Response` contenant le template "study_planner/index.html"
        et ses données associées.
    """

    return render_template("study_planner/index.html")


@study_planner_bp.route("/api/dashboard")
@login_required
@student_required
def api_dashboard():
    """
    Renvoie le tableau de bord du planificateur avec des statistiques personnalisées.

    Cette fonction est appelée lorsque l'utilisateur accède à l'URL "/api/dashboard"
    du planificateur d'études. Elle récupère les données de l'étudiant connecté et
    renvoie un objet JSON contenant des statistiques sur ses notes, ses présences,
    et ses devoirs. Ces statistiques sont utilisées pour afficher des informations
    utiles sur le planificateur d'études.

    Retourne:
        Un objet JSON contenant des statistiques sur les notes, les présences et les
        devoirs de l'étudiant connecté. Le format de l'objet JSON est le suivant :
        {
            "success": bool,
            "data": {
                "notes": {
                    "moyenne_globale": float,
                    "moyennes_par_matiere": [
                        {
                            "matiere": str,
                            "moyenne": float,
                            "nb_notes": int
                        }
                    ],
                    "taux_absences": float
                },
                "devoirs": {
                    "en_retard": int
                }
            }
        }

    Si une erreur se produit pendant l'exécution de la fonction, un objet JSON
    d'erreur sera renvoyé au format suivant :
        {
            "success": bool,
            "error": str
        }
    """
    try:
        etudiant = Etudiant.query.filter_by(user_id=current_user.id).first()
        if not etudiant:
            return (
                jsonify({"success": False, "error": "Profil étudiant introuvable"}),
                404,
            )

        # Statistiques de performance
        try:
            notes = Note.query.filter_by(etudiant_id=etudiant.id).all()
            notes_valides = [n for n in notes if n.note is not None]
            moyenne_generale = (
                sum(n.note for n in notes_valides) / len(notes_valides)
                if notes_valides
                else 0
            )
        except Exception as e:
            print(f"Erreur calcul notes: {e}")
            notes = []
            moyenne_generale = 0

        # Devoirs à venir
        try:
            devoirs_a_venir = (
                Devoir.query.filter(
                    Devoir.filiere == etudiant.filiere,
                    Devoir.annee == etudiant.annee,
                    Devoir.date_limite > datetime.now(),
                )
                .order_by(Devoir.date_limite)
                .limit(5)
                .all()
            )
        except Exception as e:
            print(f"Erreur devoirs à venir: {e}")
            devoirs_a_venir = []

        # Devoirs non consultés
        try:
            devoirs_vus_ids = [
                dv.devoir_id
                for dv in DevoirVu.query.filter_by(etudiant_id=etudiant.id).all()
            ]
            if devoirs_vus_ids:
                devoirs_non_vus = Devoir.query.filter(
                    Devoir.filiere == etudiant.filiere,
                    Devoir.annee == etudiant.annee,
                    Devoir.date_limite > datetime.now(),
                    ~Devoir.id.in_(devoirs_vus_ids),
                ).count()
            else:
                devoirs_non_vus = Devoir.query.filter(
                    Devoir.filiere == etudiant.filiere,
                    Devoir.annee == etudiant.annee,
                    Devoir.date_limite > datetime.now(),
                ).count()
        except Exception as e:
            print(f"Erreur devoirs non vus: {e}")
            devoirs_non_vus = 0

        # Taux de présence
        try:
            presences = Presence.query.filter_by(etudiant_id=etudiant.id).all()
            taux_presence = (
                sum(1 for p in presences if p.present) / len(presences) * 100
                if presences
                else 0
            )
        except Exception as e:
            print(f"Erreur taux présence: {e}")
            presences = []
            taux_presence = 0

        # Analyse des matières faibles
        try:
            matieres_faibles = analyze_weak_subjects(etudiant.id)
        except Exception as e:
            print(f"Erreur matières faibles: {e}")
            matieres_faibles = []

        # Temps d'étude recommandé
        try:
            temps_etude_recommande = calculate_study_time(
                devoirs_a_venir, matieres_faibles, moyenne_generale
            )
        except Exception as e:
            print(f"Erreur temps étude: {e}")
            temps_etude_recommande = {"par_jour": 120, "par_semaine": 840}

        data = {
            "student_info": {
                "nom": current_user.nom,
                "prenom": current_user.prenom,
                "filiere": etudiant.filiere,
                "annee": etudiant.annee,
            },
            "performance": {
                "moyenne_generale": round(moyenne_generale, 2),
                "taux_presence": round(taux_presence, 2),
                "nombre_notes": len(notes),
            },
            "devoirs": {
                "a_venir": len(devoirs_a_venir),
                "non_vus": devoirs_non_vus,
                "urgents": len([d for d in devoirs_a_venir if is_urgent(d)]),
            },
            "matieres_faibles": matieres_faibles,
            "temps_etude_recommande": temps_etude_recommande,
            "prochains_devoirs": [
                {
                    "id": d.id,
                    "titre": d.titre,
                    "type": d.type,
                    "date_rendu": d.date_limite.isoformat() if d.date_limite else None,
                    "jours_restants": (
                        (d.date_limite - datetime.now()).days if d.date_limite else 0
                    ),
                    "urgent": is_urgent(d),
                }
                for d in devoirs_a_venir
            ],
        }

        return jsonify({"success": True, "data": data})
    except Exception as e:
        print(f"Erreur générale dashboard: {e}")
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@study_planner_bp.route("/api/generate-smart-plan", methods=["POST"])
@login_required
@student_required
def api_generate_smart_plan():
    """
    Génère un plan d'étude intelligent personnalisé avec l'IA Gemini.

    Cette fonction est une route d'API qui prend en entrée le nombre de jours
    (par défaut 7) sur lesquels le plan doit être généré. Elle génère un plan
    d'étude intelligent personnalisé pour l'étudiant connecté.

    Retourne une réponse JSON avec les données du plan d'étude intelligent. La clé
    "success" est True si le plan a été généré avec succès, False sinon. Si le
    plan n'a pas été généré, la clé "error" contient un message d'erreur détaillé.

    Si le plan d'étude intelligent n'a pas pu être généré, une réponse d'erreur
    est renvoyée avec le code HTTP 500. Dans ce cas, la clé "fallback_available"
    est True si un plan d'étude intelligent fallback est disponible.

    Paramètres:
        None

    Retourne:
        JSON: Données du plan d'étude intelligent
    """
    try:
        data = request.get_json()
        days = data.get("days", 7)

        etudiant = Etudiant.query.filter_by(user_id=current_user.id).first()
        if not etudiant:
            return (
                jsonify({"success": False, "error": "Profil étudiant introuvable"}),
                404,
            )

        # Générer le plan intelligent avec Gemini
        smart_plan_result = generate_smart_study_plan(etudiant, days)

        if smart_plan_result and smart_plan_result.get("success"):
            return jsonify({"success": True, "data": smart_plan_result["data"]})
        else:
            # Fallback avec message d'erreur clair
            error_message = (
                smart_plan_result.get("error", "Erreur inconnue")
                if smart_plan_result
                else "Service IA indisponible"
            )

            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"L'IA n'a pas pu générer le plan: {error_message}",
                        "fallback_available": True,
                    }
                ),
                500,
            )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@study_planner_bp.route("/api/recommendations")
@login_required
@student_required
def api_recommendations():
    """
    Renvoie les recommandations personnalisées basées sur l'IA pour l'étudiant connecté.

    Cette fonction est une route d'API qui prend en entrée les données de l'étudiant.
    Elle génère des recommandations personnalisées pour l'étudiant en utilisant l'IA Gemini.

    Retourne une réponse JSON avec les données des recommandations. La clé "success"
    est True si les recommandations ont été générées avec succès, False sinon. Si les
    recommandations n'ont pas été générées, la clé "error" contient un message
    d'erreur détaillé.

    Si les recommandations n'ont pas pu être générées, une réponse d'erreur est renvoyée
    avec le code HTTP 500. Dans ce cas, la clé "fallback_available" est True si un
    plan d'étude intelligent fallback est disponible.

    Paramètres:
        None

    Retourne:
        JSON: Données des recommandations
    """
    try:
        etudiant = Etudiant.query.filter_by(user_id=current_user.id).first()
        if not etudiant:
            return (
                jsonify({"success": False, "error": "Profil étudiant introuvable"}),
                404,
            )

        recommendations_result = generate_recommendations(etudiant)

        if recommendations_result and recommendations_result.get("success"):
            return jsonify({"success": True, "data": recommendations_result["data"]})
        else:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Impossible de générer les recommandations",
                        "data": [],
                    }
                ),
                500,
            )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ==================== Fonctions IA améliorées ====================


def generate_smart_study_plan(etudiant, days=7):
    """
    Génère un plan d'étude intelligent avec Gemini - Version optimisée.

    Cette fonction prend en entrée un étudiant et le nombre de jours sur lesquels
    le plan doit être généré. Elle utilise l'API Gemini pour générer un plan d'étude
    intelligent personnalisé pour cet étudiant.

    Paramètres:
        etudiant (Etudiant): L'étudiant pour lequel générer le plan d'étude intelligent
        days (int, optionnel): Le nombre de jours sur lesquels le plan doit être généré

    Retourne:
        dict: Données du plan d'étude intelligent. Si le plan d'étude intelligent n'a pas pu
        être généré, la clé "success" est False, et la clé "error" contient un message
        d'erreur détaillé.
    """

    # Préparer les données de l'étudiant
    notes = Note.query.filter_by(etudiant_id=etudiant.id).all()
    matieres_data = []

    if notes:
        notes_valides = [n for n in notes if n.note is not None]
        matieres_notes = {}
        for note in notes_valides:
            matiere = Matiere.query.get(note.matiere_id)
            if matiere:
                if matiere.nom not in matieres_notes:
                    matieres_notes[matiere.nom] = []
                matieres_notes[matiere.nom].append(note.note)

        for matiere_nom, notes_list in matieres_notes.items():
            matiere_moyenne = sum(notes_list) / len(notes_list)
            matieres_data.append(
                {
                    "matiere": matiere_nom,
                    "moyenne": round(matiere_moyenne, 2),
                    "nb_notes": len(notes_list),
                    "priorite": (
                        "haute"
                        if matiere_moyenne < 10
                        else "moyenne" if matiere_moyenne < 12 else "basse"
                    ),
                }
            )

    # Devoirs urgents
    devoirs_urgents = []
    devoirs = Devoir.query.filter(
        Devoir.filiere == etudiant.filiere,
        Devoir.annee == etudiant.annee,
        Devoir.date_limite > datetime.now(),
        Devoir.date_limite < datetime.now() + timedelta(days=days),
    ).all()

    for devoir in devoirs:
        devoirs_urgents.append(
            {
                "titre": devoir.titre,
                "type": devoir.type,
                "matiere": devoir.matiere.nom if devoir.matiere else "Générale",
                "date_limite": devoir.date_limite.strftime("%Y-%m-%d"),
                "jours_restants": (devoir.date_limite - datetime.now()).days,
            }
        )

    # Prompt optimisé pour Gemini
    prompt = f"""Tu es un conseiller pédagogique expert. Génère un plan d'étude détaillé et personnalisé.

DONNÉES DE L'ÉTUDIANT:
- Nom: {etudiant.user.prenom} {etudiant.user.nom}
- Filière: {etudiant.filiere} - Année {etudiant.annee}
- Matières et moyennes: {json.dumps(matieres_data, ensure_ascii=False)}
- Devoirs urgents: {json.dumps(devoirs_urgents, ensure_ascii=False)}

INSTRUCTIONS:
Crée un plan d'étude pour {days} jours avec:
1. 2-3 sessions d'étude par jour (matin, après-midi, soir)
2. Priorise les matières avec les moyennes les plus basses
3. Intègre les devoirs urgents dans le planning
4. Ajoute des pauses Pomodoro (25min travail + 5min pause)
5. Varie les matières pour maintenir la motivation

IMPORTANT: Réponds UNIQUEMENT avec un objet JSON valide, sans texte avant ou après. Utilise ce format exact:

{{
  "plan": [
    {{
      "jour": 1,
      "date": "2025-01-15",
      "jour_semaine": "Lundi",
      "sessions": [
        {{
          "heure_debut": "09:00",
          "heure_fin": "10:30",
          "matiere": "Mathématiques",
          "type": "revision",
          "titre": "Révision des équations",
          "description": "Revoir les chapitres 1-3 avec exercices",
          "priorite": "haute",
          "duree_minutes": 90
        }},
        {{
          "heure_debut": "10:30",
          "heure_fin": "10:45",
          "type": "pause",
          "titre": "Pause courte",
          "description": "Pause détente",
          "duree_minutes": 15
        }}
      ],
      "total_minutes": 105
    }}
  ],
  "conseils": [
    "Conseil pratique 1",
    "Conseil pratique 2",
    "Conseil pratique 3"
  ],
  "statistiques": {{
    "total_heures": 21.5,
    "sessions_par_jour": 3,
    "matieres_couvertes": 5
  }}
}}"""

    # Appeler Gemini
    result = call_gemini_api(prompt, temperature=0.8)

    if result.get("success"):
        plan_data = result["data"]

        # Valider que les champs essentiels sont présents
        if "plan" in plan_data and isinstance(plan_data["plan"], list):
            return {"success": True, "data": plan_data}

    return {
        "success": False,
        "error": result.get("error", "Format de réponse invalide"),
    }


def generate_recommendations(etudiant):
    """
    Génère des recommandations personnalisées pour l'étudiant passé en paramètre.

    Cette fonction utilise des données de l'étudiant pour générer des recommandations
    personnalisées utilisant l'IA Gemini. Les recommandations sont formées de:
    - Une analyse des notes pour calculer la moyenne des étudiants
    - Une analyse des présences pour calculer le taux d'absence
    - Les recommandations sont générées à l'aide d'un prompt optimisé pour Gemini

    Args:
        etudiant (Etudiant): L'étudiant pour lequel générer les recommandations.

    Returns:
        dict: Un dictionnaire contenant les données des recommandations. La clé "success"
            est True si les recommandations ont été générées avec succès, False sinon. Si les
            recommandations n'ont pas été générées, la clé "error" contient un message
            d'erreur détaillé.
    """

    # Analyser les notes
    notes = Note.query.filter_by(etudiant_id=etudiant.id).all()
    moyenne = 0
    notes_data = []

    if notes:
        notes_valides = [n for n in notes if n.note is not None]
        if notes_valides:
            moyenne = sum(n.note for n in notes_valides) / len(notes_valides)

        matieres_notes = {}
        for note in notes_valides:
            matiere = Matiere.query.get(note.matiere_id)
            if matiere:
                if matiere.nom not in matieres_notes:
                    matieres_notes[matiere.nom] = []
                matieres_notes[matiere.nom].append(note.note)

        for matiere_nom, notes_list in matieres_notes.items():
            matiere_moyenne = sum(notes_list) / len(notes_list)
            notes_data.append(
                {
                    "matiere": matiere_nom,
                    "moyenne": round(matiere_moyenne, 2),
                    "nb_notes": len(notes_list),
                }
            )

    # Analyser les présences
    presences = Presence.query.filter_by(etudiant_id=etudiant.id).all()
    taux_absence = 0
    if presences:
        absences = sum(1 for p in presences if not p.present)
        taux_absence = (absences / len(presences) * 100) if presences else 0

    # Analyser les devoirs
    devoirs_en_retard = (
        Devoir.query.join(DevoirVu)
        .filter(
            DevoirVu.etudiant_id == etudiant.id, Devoir.date_limite < datetime.now()
        )
        .count()
    )

    # Prompt optimisé
    prompt = f"""Tu es un conseiller pédagogique expert. Analyse ce profil étudiant et donne des recommandations concrètes.

PROFIL ÉTUDIANT:
- Moyenne générale: {moyenne:.2f}/20
- Taux d'absence: {taux_absence:.1f}%
- Devoirs en retard: {devoirs_en_retard}
- Détails par matière: {json.dumps(notes_data, ensure_ascii=False)}

INSTRUCTIONS:
Donne 4 recommandations personnalisées et actionnables pour améliorer la performance académique.
Chaque recommandation doit avoir:
- Un type (critique/warning/info/success)
- Un titre court et percutant
- Un message détaillé (2-3 phrases)
- 3-4 actions concrètes à réaliser
- Une icône FontAwesome appropriée

IMPORTANT: Réponds UNIQUEMENT avec un objet JSON valide. Format exact:

{{
  "recommendations": [
    {{
      "type": "warning",
      "icon": "fas fa-exclamation-triangle",
      "title": "Améliorez votre assiduité",
      "message": "Votre taux d'absence impacte vos résultats. La présence en cours est essentielle pour comprendre et réussir.",
      "actions": [
        "Assistez à tous vos cours sans exception",
        "Prévenez en cas d'absence justifiée",
        "Rattrapez les cours manqués immédiatement",
        "Organisez votre emploi du temps pour éviter les conflits"
      ]
    }}
  ]
}}"""

    result = call_gemini_api(prompt, temperature=0.7)

    if result.get("success"):
        reco_data = result["data"]
        if "recommendations" in reco_data and isinstance(
            reco_data["recommendations"], list
        ):
            return {"success": True, "data": reco_data["recommendations"]}

    return {"success": False, "error": result.get("error", "Format invalide")}


# ==================== Fonctions auxiliaires ====================


def analyze_weak_subjects(etudiant_id):
    """
    Analyse les matières où l'étudiant a des difficultés.

    Cette fonction récupère les notes de chaque matière pour un étudiant donné,
    et détermine les matières où l'étudiant affiche des difficultés. Les matières
    sont considérées comme des difficultés si leur moyenne est inférieure à 10.

    Paramètres:
        etudiant_id (int): L'identifiant de l'étudiant dont les difficultés seront analysées

    Retourne:
        list: Liste des matières où l'étudiant a des difficultés. Chaque entrée de la liste
        est un objet contenant les noms des matières, leurs moyennes et leurs nombres de notes.
        Les objets sont triés par moyenne décroissante.
    """
    notes_by_matiere = (
        db.session.query(
            Matiere.nom,
            Matiere.id,
            func.avg(Note.note).label("moyenne"),
            func.count(Note.id).label("nb_notes"),
        )
        .join(Note, Note.matiere_id == Matiere.id)
        .filter(Note.etudiant_id == etudiant_id, Note.note.isnot(None))
        .group_by(Matiere.id)
        .all()
    )

    weak_subjects = []
    for matiere_nom, matiere_id, moyenne, nb_notes in notes_by_matiere:
        if moyenne and moyenne < 12:
            weak_subjects.append(
                {
                    "matiere": matiere_nom,
                    "matiere_id": matiere_id,
                    "moyenne": round(moyenne, 2),
                    "nb_notes": nb_notes,
                    "niveau_difficulte": get_difficulty_level(moyenne),
                    "priorite": calculate_priority(moyenne, nb_notes),
                }
            )

    weak_subjects.sort(key=lambda x: x["priorite"], reverse=True)
    return weak_subjects


def get_difficulty_level(moyenne):
    """
    Détermine le niveau de difficulté basé sur la moyenne.

    La fonction prend en paramètre la moyenne d'un étudiant et renvoie
    le niveau de difficulté correspondant à cette moyenne. Les niveaux
    de difficulté sont les suivants :

    - "Critique" : Si la moyenne est inférieure à 8.
    - "Très difficile" : Si la moyenne est comprise entre 8 et 10.
    - "Difficile" : Si la moyenne est comprise entre 10 et 12.
    - "Moyen" : Si la moyenne est supérieure ou égale à 12.

    Paramètres:
        moyenne (float): La moyenne d'un étudiant.

    Retourne:
        str: Le niveau de difficulté correspondant à la moyenne donnée.
    """
    if moyenne < 8:
        return "Critique"
    elif moyenne < 10:
        return "Très difficile"
    elif moyenne < 12:
        return "Difficile"
    else:
        return "Moyen"


def calculate_priority(moyenne, nb_notes):
    """
    Calcule la priorité d'une matière en fonction de sa moyenne.

    La fonction prend en paramètres la moyenne d'une matière et renvoie
    un score de priorité allant de 0 à 100. Le score est calculé en fonction
    de la moyenne de la matière. Plus la moyenne est basse, plus le score
    est élevé.

    Paramètres:
        moyenne (float): La moyenne d'une matière.

    Retourne:
        int: Le score de priorité de la matière, allant de 0 à 100.
    """
    score_moyenne = max(100 - (moyenne * 10), 0)
    score_nb_notes = min(nb_notes * 5, 30)
    return min(score_moyenne + score_nb_notes, 100)


def calculate_study_time(devoirs, matieres_faibles, moyenne_generale):
    """
    Calcule le temps d'étude recommandé par jour.

    Cette fonction calcule le temps d'étude recommandé par jour en fonction de la
    moyenne générale de l'étudiant, du nombre de matières faibles et du nombre de
    devoirs urgents. Le temps d'étude recommandé est calculé en fonction de la
    moyenne générale de l'étudiant. Plus la moyenne est basse, plus le temps d'étude
    recommandé est élevé. Le temps d'étude recommandé par jour est fixé à 120 minutes
    par défaut. Il est ensuite ajusté en fonction des critères mentionnés précédemment.

    Paramètres:
        devoirs (list): La liste des devoirs de l'étudiant.
        matieres_faibles (list): La liste des matières où l'étudiant affiche des difficultés.
        moyenne_generale (float): La moyenne générale de l'étudiant.

    Retourne:
        int: Le temps d'étude recommandé par jour en minutes, allant de 120 à 300.
    """
    base_time = 120

    if moyenne_generale < 10:
        base_time += 60
    elif moyenne_generale < 12:
        base_time += 30

    devoirs_urgents = sum(1 for d in devoirs if is_urgent(d))
    base_time += devoirs_urgents * 15
    base_time += len(matieres_faibles) * 20

    return min(base_time, 300)


def is_urgent(devoir):
    """
    Détermine si un devoir est considéré comme urgent en fonction de sa date limite.

    Cette fonction prend en paramètre un devoir et renvoie True si la date limite
    du devoir est inférieure ou égale à trois jours à partir de la date actuelle.
    Sinon, la fonction renvoie False.

    Paramètres:
        devoir (Devoir): Le devoir dont la date limite doit être vérifiée.

    Retourne:
        bool: True si la date limite du devoir est inférieure ou égale à trois jours,
        False sinon.
    """
    jours_restants = (devoir.date_limite - datetime.now()).days
    return jours_restants <= 3


def get_jour_fr(weekday):
    """
    Retourne le nom du jour en français.

    Cette fonction prend en paramètre un jour de la semaine (comme un entier) et
    renvoie le nom correspondant en français.

    Paramètres:
        weekday (int): Le jour de la semaine (0 pour lundi, 1 pour mardi, etc.).

    Retourne:
        str: Le nom du jour en français.
    """
    jours = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    return jours[weekday]


def calculate_most_productive_day(etudiant_id):
    """
    Calcule le jour de la semaine le plus productif.

    Cette fonction calcule le jour de la semaine le plus productif en fonction des
    statistiques de pomodoros terminés pour l'étudiant. Le jour le plus productif
    est le jour sur lequel le nombre de pomodoros terminés est le plus élevé.

    Paramètres:
        etudiant_id (int): L'identifiant de l'étudiant dont le jour le plus productif
        doit être calculé.

    Retourne:
        str: Le nom du jour le plus productif en français.
    """
    from datetime import timedelta

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_week = today - timedelta(days=today.weekday())

    jours_fr = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]

    stats_par_jour = {}
    for i in range(7):
        day = start_of_week + timedelta(days=i)
        day_end = day + timedelta(days=1)

        sessions = PomodoroSession.query.filter(
            PomodoroSession.etudiant_id == etudiant_id,
            PomodoroSession.date_debut >= day,
            PomodoroSession.date_debut < day_end,
            PomodoroSession.statut == "terminee",
            PomodoroSession.type_session == "travail",
        ).all()

        total_minutes = sum(s.duree_reelle or 0 for s in sessions)
        stats_par_jour[jours_fr[i]] = total_minutes

    if stats_par_jour and max(stats_par_jour.values()) > 0:
        return max(stats_par_jour, key=stats_par_jour.get)
    return "Aucun"


# ==================== Routes Pomodoro ====================


@study_planner_bp.route("/api/pomodoro/stats")
@login_required
@student_required
def api_pomodoro_stats():
    """
    Renvoie des statistiques sur les sessions Pomodoro pour un étudiant spécifique.

    Cette fonction est appelée lorsque l'utilisateur accède à l'URL "/api/pomodoro/stats"
    pour obtenir des statistiques sur les sessions Pomodoro d'un étudiant. Elle récupère les
    statistiques pour aujourd'hui, la semaine et le mois pour cet étudiant, et renvoie un
    objet JSON contenant ces statistiques.

    Retourne:
        Un objet JSON contenant les statistiques sur les sessions Pomodoro pour l'étudiant
        connecté. Le format de l'objet JSON est le suivant :
        {
            "success": bool,
            "data": {
                "today": {
                    "total_minutes": int,
                    "nbr_pomodoros": int
                },
                "week": {
                    "total_minutes": int,
                    "nbr_pomodoros": int
                },
                "month": {
                    "total_minutes": int,
                    "nbr_pomodoros": int
                },
                "most_productive_day": str
            }
        }

    Si une erreur se produit pendant l'exécution de la fonction, un objet JSON
    d'erreur sera renvoyé au format suivant :
        {
            "success": bool,
            "error": str
        }
    """
    try:
        etudiant = Etudiant.query.filter_by(user_id=current_user.id).first()
        if not etudiant:
            return (
                jsonify({"success": False, "error": "Profil étudiant introuvable"}),
                404,
            )

        stats_today = PomodoroSession.get_stats_etudiant(etudiant.id, "today")
        stats_week = PomodoroSession.get_stats_etudiant(etudiant.id, "week")
        stats_month = PomodoroSession.get_stats_etudiant(etudiant.id, "month")

        most_productive_day = calculate_most_productive_day(etudiant.id)

        days_in_month = datetime.now().day
        average_per_day = (
            stats_month["total_minutes"] / days_in_month if days_in_month > 0 else 0
        )

        stats = {
            "today": {
                "sessions_completed": stats_today["sessions_completed"],
                "total_minutes": stats_today["total_minutes"],
                "breaks_taken": stats_today["breaks_taken"],
            },
            "week": {
                "sessions_completed": stats_week["sessions_completed"],
                "total_minutes": stats_week["total_minutes"],
                "most_productive_day": most_productive_day,
            },
            "month": {
                "sessions_completed": stats_month["sessions_completed"],
                "total_minutes": stats_month["total_minutes"],
                "average_per_day": round(average_per_day, 1),
            },
        }

        return jsonify({"success": True, "data": stats})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@study_planner_bp.route("/api/pomodoro/start", methods=["POST"])
@login_required
@student_required
def api_pomodoro_start():
    """
    Démarre une session Pomodoro.

    Cette fonction est appelée lorsque l'utilisateur accède à l'URL "/api/pomodoro/start"
    pour démarrer une nouvelle session Pomodoro. Elle récupère les données de l'étudiant
    connecté et vérifie s'il existe déjà une session en cours. Si ce n'est pas le cas,
    elle crée une nouvelle session Pomodoro avec les paramètres fournis dans la requête
    POST. Si une session est déjà en cours, elle renvoie une réponse d'erreur.

    Retourne:
        Un objet JSON contenant les détails de la session Pomodoro démarrée. Le format de
        l'objet JSON est le suivant :
        {
            "success": bool,
            "data": {
                "id": int,
                "etudiant_id": int,
                "matiere_id": int,
                "duree_prevue": int,
                "type_session": str,
                "titre": str,
                "description": str,
                "duree_reelle": int,
                "date_debut": str (en format ISO 8601),
                "date_fin": str (en format ISO 8601) ou None,
                "pauses": [
                    {
                        "id": int,
                        "session_id": int,
                        "duree": int,
                        "date_debut": str (en format ISO 8601),
                        "date_fin": str (en format ISO 8601) ou None
                    }
                ]
            }
        }

    Si une session est déjà en cours, une réponse d'erreur est renvoyée au format suivant :
        {
            "success": bool,
            "error": str
        }
    """
    try:
        etudiant = Etudiant.query.filter_by(user_id=current_user.id).first()
        if not etudiant:
            return (
                jsonify({"success": False, "error": "Profil étudiant introuvable"}),
                404,
            )

        data = request.get_json()

        session = PomodoroSession(
            etudiant_id=etudiant.id,
            matiere_id=data.get("matiere_id"),
            duree_prevue=data.get("duree_prevue", 25),
            type_session=data.get("type_session", "travail"),
            titre=data.get("titre"),
            description=data.get("description"),
            tache_associee=data.get("tache_associee"),
        )

        db.session.add(session)
        db.session.commit()

        return jsonify({"success": True, "data": session.to_dict()})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@study_planner_bp.route("/api/pomodoro/<int:session_id>/complete", methods=["POST"])
@login_required
@student_required
def api_pomodoro_complete(session_id):
    """
    Marque une session comme terminée.

    Cette fonction est appelée lorsque l'utilisateur souhaite marquer une session
    Pomodoro comme terminée. Elle prend en paramètre l'identifiant de la session,
    vérifie que l'utilisateur est autorisé à terminer la session et met à jour les
    informations de la session enregistrée en base de données.

    Paramètres:
        session_id (int): L'identifiant de la session Pomodoro à terminer.

    Retourne:
        Un objet JSON contenant les détails de la session Pomodoro terminée. Le format
        de l'objet JSON est le suivant :
        {
            "success": bool,
            "data": {
                "id": int,
                "etudiant_id": int,
                "matiere_id": int,
                "duree_prevue": int,
                "type_session": str,
                "titre": str,
                "description": str,
                "duree_reelle": int,
                "date_debut": str (en format ISO 8601),
                "date_fin": str (en format ISO 8601),
                "pause_prise": bool,
                "duree_pause": int,
                "niveau_concentration": int,
                "pauses": [
                    {
                        "id": int,
                        "session_id": int,
                        "duree": int,
                        "date_debut": str (en format ISO 8601),
                        "date_fin": str (en format ISO 8601) ou None
                    }
                ]
            }
        }

    Si l'utilisateur n'est pas autorisé à terminer la session, une réponse d'erreur
    est renvoyée au format suivant :
        {
            "success": bool,
            "error": str
        }
    """
    try:
        etudiant = Etudiant.query.filter_by(user_id=current_user.id).first()
        if not etudiant:
            return (
                jsonify({"success": False, "error": "Profil étudiant introuvable"}),
                404,
            )

        session = PomodoroSession.query.get_or_404(session_id)

        if session.etudiant_id != etudiant.id:
            return jsonify({"success": False, "error": "Accès non autorisé"}), 403

        data = request.get_json()

        session.marquer_terminee()
        session.pause_prise = data.get("pause_prise", False)
        session.duree_pause = data.get("duree_pause")
        session.niveau_concentration = data.get("niveau_concentration")

        db.session.commit()

        return jsonify({"success": True, "data": session.to_dict()})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@study_planner_bp.route("/api/pomodoro/<int:session_id>/interrupt", methods=["POST"])
@login_required
@student_required
def api_pomodoro_interrupt(session_id):
    """
    Marque une session comme interrompue.

    Cette fonction est appelée lorsque l'utilisateur souhaite marquer une session Pomodoro
    comme interrompue. Elle prend en paramètre l'identifiant de la session à marquer.
    Si l'utilisateur n'est pas autorisé à interrompre la session, une réponse d'erreur
    est renvoyée au format suivant :
        {
            "success": bool,
            "error": str
        }
    """
    try:
        etudiant = Etudiant.query.filter_by(user_id=current_user.id).first()
        if not etudiant:
            return (
                jsonify({"success": False, "error": "Profil étudiant introuvable"}),
                404,
            )

        session = PomodoroSession.query.get_or_404(session_id)

        if session.etudiant_id != etudiant.id:
            return jsonify({"success": False, "error": "Accès non autorisé"}), 403

        session.marquer_interrompue()
        db.session.commit()

        return jsonify({"success": True, "data": session.to_dict()})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@study_planner_bp.route(
    "/api/pomodoro/<int:session_id>/add-interruption", methods=["POST"]
)
@login_required
@student_required
def api_pomodoro_add_interruption(session_id):
    """
    Ajoute une interruption à une session Pomodoro.

    Cette fonction est appelée lorsque l'utilisateur souhaite ajouter une interruption
    à une session Pomodoro. Elle prend en paramètre l'identifiant de la session
    à laquelle ajouter l'interruption. Si l'utilisateur n'est pas autorisé à ajouter
    l'interruption, une réponse d'erreur est renvoyée au format suivant :
        {
            "success": bool,
            "error": str
        }
    """
    try:
        etudiant = Etudiant.query.filter_by(user_id=current_user.id).first()
        if not etudiant:
            return (
                jsonify({"success": False, "error": "Profil étudiant introuvable"}),
                404,
            )

        session = PomodoroSession.query.get_or_404(session_id)

        if session.etudiant_id != etudiant.id:
            return jsonify({"success": False, "error": "Accès non autorisé"}), 403

        session.ajouter_interruption()
        db.session.commit()

        return jsonify({"success": True, "data": session.to_dict()})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@study_planner_bp.route("/api/generate-plan", methods=["POST"])
@login_required
@student_required
def api_generate_plan():
    """
    Génère un plan d'étude avec l'IA Gemini

    Cette fonction est appelée lorsque l'utilisateur souhaite générer un plan d'étude
    personnalisé en utilisant l'IA Gemini. Elle prend en paramètre une requête HTTP POST
    contenant les données nécessaires pour générer le plan d'étude.

    Format de la requête:
    {
        "start_date": "YYYY-MM-DD",
        "end_date": "YYYY-MM-DD",
        "study_hours_per_day": int,
        "focus_areas": [str]
    }

    Retourne un plan d'étude au format:
    {
        "success": bool,
        "data": {
            "plan": [{
                "day": int,
                "hours": int,
                "sessions": [{
                    "matiere": str,
                    "duree": int,
                    "type": str
                }]
            }]
        }
    }
    """
    try:
        data = request.get_json() or {}

        # 1. Validation et sécurisation des paramètres d'entrée
        try:
            start_date = datetime.fromisoformat(
                data.get("start_date", datetime.now().date().isoformat())
            )
            end_date = datetime.fromisoformat(
                data.get(
                    "end_date", (datetime.now() + timedelta(days=7)).date().isoformat()
                )
            )
        except (ValueError, TypeError):
            return (
                jsonify(
                    {"success": False, "error": "Format de date invalide (ISO attendu)"}
                ),
                400,
            )

        # Limitation raisonnable du temps d'étude (max 12h/jour)
        study_hours_per_day = min(int(data.get("study_hours_per_day", 2)), 12)
        focus_areas = data.get("focus_areas", [])

        # 2. Récupération des données académiques
        etudiant = Etudiant.query.filter_by(user_id=current_user.id).first()
        if not etudiant:
            return (
                jsonify({"success": False, "error": "Profil étudiant introuvable"}),
                404,
            )

        # Récupération des notes pour calcul de moyenne par matière
        notes = Note.query.filter_by(etudiant_id=etudiant.id).all()
        matieres_stats = {}
        for n in notes:
            if n.matiere_id not in matieres_stats:
                matieres_stats[n.matiere_id] = {
                    "sum": 0,
                    "count": 0,
                    "nom": n.matiere.nom,
                }
            matieres_stats[n.matiere_id]["sum"] += n.note
            matieres_stats[n.matiere_id]["count"] += 1

        matieres_data = [
            {"matiere": v["nom"], "moyenne": round(v["sum"] / v["count"], 2)}
            for v in matieres_stats.values()
        ]

        # Récupération des devoirs à venir sur la période
        devoirs = (
            Devoir.query.filter(
                Devoir.filiere == etudiant.filiere,
                Devoir.annee == etudiant.annee,
                Devoir.date_limite >= start_date,
                Devoir.date_limite <= end_date,
            )
            .order_by(Devoir.date_limite.asc())
            .all()
        )

        # 3. Construction du Prompt optimisé
        prompt = f"""Tu es un expert en coaching académique. Génère un plan d'étude JSON pour cet étudiant :

PROFIL :
- Cursus : {etudiant.filiere} ({etudiant.annee})
- Volume : {study_hours_per_day}h/jour
- Période : du {start_date.strftime('%d/%m/%Y')} au {end_date.strftime('%d/%m/%Y')}

PERFORMANCES :
- Moyennes actuelles : {json.dumps(matieres_data, ensure_ascii=False)}
- Priorités déclarées : {', '.join(focus_areas) if focus_areas else 'Aucune'}

ÉCHÉANCES CRITIQUES :
{chr(10).join([f"- {d.titre} le {d.date_limite.strftime('%d/%m/%Y')}" for d in devoirs])}

RÈGLES STRICTES :
1. ÉQUILIBRE : Alloue plus de temps aux matières où la moyenne est < 10/20.
2. ANTICIPATION : Prévois des sessions "Devoir" 48h avant chaque échéance.
3. STRUCTURE : Sessions de 45 à 90 minutes maximum.
4. FORMAT : Réponds EXCLUSIVEMENT avec un objet JSON. Pas de texte avant/après.

FORMAT JSON ATTENDU :
{{
  "plan": [
    {{
      "jour": 1,
      "date": "YYYY-MM-DD",
      "sessions": [
        {{ "matiere": "Nom", "duree": 60, "type": "Révision/Exercices/Devoir", "objectif": "Sujet précis" }}
      ]
    }}
  ]
}}"""

        # 4. Appel à l'IA avec température basse pour plus de rigueur structurelle
        result = call_gemini_api(prompt, temperature=0.3)

        if not result.get("success"):
            return (
                jsonify({"success": False, "error": "L'IA n'a pas pu générer le plan"}),
                502,
            )

        # 5. Nettoyage et Parsing de la réponse
        raw_text = result.get("data", {}).get("text", "{}")
        # Supprime les balises Markdown ```json si Gemini les ajoute malgré les instructions
        clean_json = re.sub(r"```json|```", "", raw_text).strip()

        try:
            plan_data = json.loads(clean_json)

            # Validation sommaire de la structure
            if "plan" not in plan_data:
                raise ValueError("Clé 'plan' absente de la réponse IA")

            # Formatage final pour le front-end
            formatted_plan = []
            for day_entry in plan_data["plan"]:
                sessions = day_entry.get("sessions", [])
                formatted_day = {
                    "day": day_entry.get("jour"),
                    "date": day_entry.get("date"),
                    "total_minutes": sum(s.get("duree", 0) for s in sessions),
                    "sessions": sessions,
                }
                formatted_plan.append(formatted_day)

            return jsonify({"success": True, "data": {"plan": formatted_plan}})

        except (json.JSONDecodeError, ValueError) as e:
            current_app.logger.error(
                f"Erreur parsing JSON IA: {str(e)} | Brut: {raw_text}"
            )
            return (
                jsonify({"success": False, "error": "Le format généré est invalide"}),
                500,
            )

    except Exception as e:
        current_app.logger.error(f"Erreur critique api_generate_plan: {str(e)}")
        return jsonify({"success": False, "error": "Erreur serveur interne"}), 500


@study_planner_bp.route("/view-plan")
@login_required
@student_required
def view_plan():
    """
    Affiche le plan d'étude.

    Cette fonction est appelée lorsque l'utilisateur accède à l'URL "/view-plan"
    du planificateur d'études. Elle récupère les données du plan d'étude à afficher
    à partir de la chaîne de caractères "data" dans les paramètres de la requête.
    Les données sont décodées à partir de l'URL, puis affichées sous forme d'arbre de
    répertoires avec les activités de chaque jour.

    Retourne:
        Un objet JSON de réponse avec la clé "success" à True si le plan d'étude a
        été affiché avec succès, False sinon. Si le plan d'étude n'a pas été affiché,
        la clé "error" contient un message d'erreur détaillé.
    """
    import json
    from urllib.parse import unquote

    plan_data = request.args.get("data")

    if not plan_data:
        flash("Aucun plan d'étude à afficher.", "error")
        return redirect(url_for("study_planner.index"))

    try:
        plan_json = unquote(plan_data)
        plan = json.loads(plan_json)

        return render_template("study_planner/view_plan.html", plan=plan)
    except Exception as e:
        flash(f"Erreur lors du chargement du plan: {str(e)}", "error")
        return redirect(url_for("study_planner.index"))


def generate_smart_plan(
    start_date,
    end_date,
    study_hours_per_day,
    devoirs,
    emploi_temps,
    weak_subjects,
    focus_areas,
):
    """
    Génère un plan d'étude intelligent (algorithme local).

    Cette fonction prend en entrée les paramètres suivants :

    - start_date (datetime): la date de début du plan d'étude
    - end_date (datetime): la date de fin du plan d'étude
    - study_hours_per_day (float): le nombre d'heures d'étude par jour
    - devoirs (list): la liste des devoirs à effectuer
    - emploi_temps (list): la liste des emplois du temps pour chaque jour de la semaine
    - weak_subjects (list): les matières sur lesquelles l'étudiant a des difficultés
    - focus_areas (list): les domaines sur lesquels l'étudiant veut se concentrer

    Elle renvoie un plan d'étude sous la forme d'une liste de jours, chaque jour
    contenant une date, une liste de sessions d'étude, et le nombre total de minutes
    d'étude pour ce jour. Chaque session d'étude contient une liste de tâches, une
    durée en minutes, et une description.

    """
    plan = []
    current_date = start_date
    study_minutes_per_day = study_hours_per_day * 60

    while current_date <= end_date:
        day_plan = {
            "date": current_date.isoformat(),
            "jour": get_jour_fr(current_date.weekday()),
            "sessions": [],
            "total_minutes": 0,
        }

        remaining_minutes = study_minutes_per_day

        # Devoirs urgents
        for devoir in devoirs:
            if is_urgent(devoir) and remaining_minutes > 0:
                duration = min(60, remaining_minutes)
                session = {
                    "type": "devoir",
                    "titre": f"Travail sur: {devoir.titre}",
                    "matiere": "Devoir",
                    "duree": duration,
                    "priorite": "haute",
                    "description": f"{devoir.type} à rendre le {devoir.date_limite.strftime('%d/%m/%Y') if devoir.date_limite else 'N/A'}",
                }
                day_plan["sessions"].append(session)
                remaining_minutes -= duration

        # Matières faibles
        for weak in weak_subjects[:3]:
            if remaining_minutes > 0:
                duration = min(45, remaining_minutes)
                session = {
                    "type": "revision",
                    "titre": f"Révision: {weak['matiere']}",
                    "matiere": weak["matiere"],
                    "duree": duration,
                    "priorite": "moyenne",
                    "description": f"Moyenne actuelle: {weak['moyenne']}/20 - {weak['niveau_difficulte']}",
                }
                day_plan["sessions"].append(session)
                remaining_minutes -= duration

        # Focus areas
        for focus in focus_areas:
            if remaining_minutes > 0:
                duration = min(45, remaining_minutes)
                session = {
                    "type": "focus",
                    "titre": f"Approfondissement: {focus}",
                    "matiere": focus,
                    "duree": duration,
                    "priorite": "normale",
                    "description": "Session d'approfondissement",
                }
                day_plan["sessions"].append(session)
                remaining_minutes -= duration

        # Révision générale
        if remaining_minutes > 0:
            session = {
                "type": "revision_generale",
                "titre": "Révision générale",
                "matiere": "Toutes matières",
                "duree": remaining_minutes,
                "priorite": "basse",
                "description": "Révision des points importants",
            }
            day_plan["sessions"].append(session)

        day_plan["total_minutes"] = sum(s["duree"] for s in day_plan["sessions"])
        day_plan["sessions"] = add_pomodoro_breaks(day_plan["sessions"])

        plan.append(day_plan)
        current_date += timedelta(days=1)

    return {
        "plan": plan,
        "total_days": len(plan),
        "total_hours": sum(d["total_minutes"] for d in plan) / 60,
        "recommendations": generate_plan_recommendations_basic(plan, weak_subjects),
    }


def add_pomodoro_breaks(sessions):
    """
    Ajoute des pauses Pomodoro.

    Cette fonction prend une liste de sessions d'étude, et ajoute des pauses
    Pomodoro entre chaque session. Chaque pause est une session de type "pause"
    avec une durée de 5 minutes ou de 15 minutes, en fonction de la durée de la
    session précédente.

    Paramètres:
        sessions (list): une liste de sessions d'étude. Chaque session est un
            dictionnaire contenant les clés "type", "titre", "duree", et
            "description".

    Retourne:
        list: une liste de sessions d'étude avec des pauses Pomodoro ajoutées.
    """
    enhanced_sessions = []
    for i, session in enumerate(sessions):
        enhanced_sessions.append(session)

        if i < len(sessions) - 1:
            pause_duration = 15 if session["duree"] >= 30 else 5
            enhanced_sessions.append(
                {
                    "type": "pause",
                    "titre": "Pause",
                    "duree": pause_duration,
                    "description": "Pause recommandée pour optimiser la concentration",
                }
            )

    return enhanced_sessions


def generate_plan_recommendations_basic(plan, weak_subjects):
    """
    Génère des recommandations basiques (fallback).

    Cette fonction prend un plan d'étude et une liste de matières faibles et
    génère une liste de recommandations basiques qui peuvent être utilisées en
    cas d'échec de la génération d'un plan d'étude intelligent.

    Paramètres:
        plan (list): un plan d'étude généré par la fonction `generate_smart_study_plan`
        weak_subjects (list): une liste de noms de matières faibles.

    Retourne:
        list: une liste de recommandations basiques. Chaque recommandation est un
        dictionnaire contenant les clés "type", "message". Le type de recommandation
        peut être "warning" ou "success". Le message est un texte décrivant la
        recommandation.
    """
    recommendations = []

    total_minutes = sum(d["total_minutes"] for d in plan)
    avg_per_day = total_minutes / len(plan) if plan else 0

    if avg_per_day < 120:
        recommendations.append(
            {
                "type": "warning",
                "message": "Votre temps d'étude est inférieur à 2h par jour. Considérez augmenter votre charge de travail.",
            }
        )

    if avg_per_day > 300:
        recommendations.append(
            {
                "type": "warning",
                "message": "Attention à ne pas surcharger votre emploi du temps. Pensez à prendre des pauses régulières.",
            }
        )

    if weak_subjects:
        recommendations.append(
            {
                "type": "info",
                "message": f"Concentrez-vous particulièrement sur: {', '.join([w['matiere'] for w in weak_subjects[:3]])}",
            }
        )

    recommendations.append(
        {
            "type": "success",
            "message": "Utilisez la technique Pomodoro (25 min de travail + 5 min de pause) pour maximiser votre concentration.",
        }
    )

    return recommendations


def find_free_slots(current_date, emploi_temps):
    """
    Trouve les créneaux horaires libres en commençant à 7h du matin et en
    se terminant à 23h.

    Args:
        current_date (date): La date pour laquelle on recherche les créneaux
            horaires libres.
        emploi_temps (list): La liste des créneaux horaires déjà occupés pour
            la date donnée.

    Returns:
        list: La liste des créneaux horaires libres pour la date donnée.
    """
    day_start = datetime.strptime("07:00", "%H:%M").time()
    day_end = datetime.strptime("23:00", "%H:%M").time()

    jours_fr = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    jour_semaine = jours_fr[current_date.weekday()]

    creneaux_du_jour = [
        creneau
        for creneau in emploi_temps
        if creneau.get("jour", "").lower() == jour_semaine.lower()
    ]

    creneaux_du_jour.sort(key=lambda x: x["debut"])

    creneaux_libres = []

    premier_creneau = creneaux_du_jour[0] if creneaux_du_jour else None
    if premier_creneau:
        debut_premier = datetime.strptime(premier_creneau["debut"], "%H:%M").time()
        if debut_premier > day_start:
            creneaux_libres.append(
                {"debut": day_start.strftime("%H:%M"), "fin": premier_creneau["debut"]}
            )

    for i in range(len(creneaux_du_jour) - 1):
        fin_actuel = creneaux_du_jour[i]["fin"]
        debut_suivant = creneaux_du_jour[i + 1]["debut"]

        fin_actuel_time = datetime.strptime(fin_actuel, "%H:%M").time()
        debut_suivant_time = datetime.strptime(debut_suivant, "%H:%M").time()

        if (
            datetime.combine(current_date, debut_suivant_time)
            - datetime.combine(current_date, fin_actuel_time)
        ).total_seconds() >= 1800:
            creneaux_libres.append({"debut": fin_actuel, "fin": debut_suivant})

    if creneaux_du_jour:
        dernier_creneau = creneaux_du_jour[-1]
        fin_dernier = datetime.strptime(dernier_creneau["fin"], "%H:%M").time()
        if fin_dernier < day_end:
            creneaux_libres.append(
                {"debut": dernier_creneau["fin"], "fin": day_end.strftime("%H:%M")}
            )

    if not creneaux_du_jour:
        creneaux_libres = [
            {"debut": day_start.strftime("%H:%M"), "fin": day_end.strftime("%H:%M")}
        ]

    creneaux_libres = [
        creneau
        for creneau in creneaux_libres
        if (
            datetime.strptime(creneau["fin"], "%H:%M")
            - datetime.strptime(creneau["debut"], "%H:%M")
        ).total_seconds()
        >= 1800
    ]

    return creneaux_libres
