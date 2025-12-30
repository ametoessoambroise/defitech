"""
Module principal pour l'assistant IA defAI
Gère les routes Flask, la communication avec Gemini et l'orchestration des requêtes internes
"""

from flask import (
    Blueprint,
    request,
    jsonify,
    render_template,
    current_app,
    redirect,
    url_for,
    send_from_directory,
)
from flask_login import login_required, current_user
import json
import logging
import os
import uuid
import re
from datetime import datetime
from werkzeug.utils import secure_filename
import mimetypes

from app.extensions import db
from app.models.ai_assistant import AIConversation, AIMessage, Dataset
from app.services.ai_orchestrator import AIOrchestrator
from app.services.gemini_integration import GeminiIntegration
from app.security_decorators import log_api_access, rate_limit
from app.services.ai_image_generator import (
    generate_image_async,
    check_image_status,
)

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration des fichiers
ALLOWED_EXTENSIONS = {
    "txt",
    "pdf",
    "png",
    "jpg",
    "jpeg",
    "gif",
    "doc",
    "docx",
    "xls",
    "xlsx",
    "ppt",
    "pptx",
}
MAX_FILE_SIZE = 16 * 1024 * 1024  # 16MB

# Création du blueprint
ai_assistant_bp = Blueprint("ai_assistant", __name__, url_prefix="/api/ai")

# Configuration Gemini API depuis les variables d'environnement
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Configuration du service externe de génération d'images
FREE_IMAGE_API_URL = os.getenv("FREE_IMAGE_API_URL")
FREE_IMAGE_API_TOKEN = os.getenv("FREE_IMAGE_API_TOKEN")
FREE_IMAGE_API_TIMEOUT = int(
    os.getenv("FREE_IMAGE_API_TIMEOUT", 30)
)  # 30 secondes par défaut

# Initialisation de l'intégration Gemini
gemini = GeminiIntegration(GEMINI_API_KEY)

# Initialisation de l'orchestrateur
orchestrator = AIOrchestrator()


"""
Ajouts à faire dans ai_assistant.py pour gérer les SMART_QUERY
"""


def parse_smart_queries(response):
    """Extrait les demandes de requêtes intelligentes de la réponse de l'IA"""
    import re

    pattern = r"\[SMART_QUERY:\s*([^\]]+)\]"
    matches = re.findall(pattern, response)

    requests = []
    for query in matches:
        requests.append({"query": query.strip()})

    return requests


def process_smart_queries(smart_queries, user_id, user_role, conversation_id):
    """Traite les requêtes intelligentes et récupère les données"""
    all_data = {}

    for sq in smart_queries:
        try:
            query = sq["query"]
            logger.info(f"Traitement SMART_QUERY: {query}")

            # Utiliser l'orchestrateur pour récupérer les données
            result = orchestrator.execute_smart_request(query, user_id, user_role)

            if result["success"]:
                all_data[query] = result["data"]
                logger.info(f"Données récupérées pour: {query}")
            else:
                logger.error(f"Échec SMART_QUERY: {result.get('error')}")
                all_data[query] = {"error": result.get("error")}

        except Exception as e:
            logger.error(f"Erreur traitement SMART_QUERY: {e}")
            all_data[query] = {"error": str(e)}

    return all_data


# ---------------- SQL QUERY HELPERS ----------------
SQL_PATTERN = r"\[SQL_QUERY:\s*([^\]]+)\]"


def parse_sql_queries(response: str):
    """Retourne la liste des requêtes SQL trouvées dans la réponse de l'IA."""
    import re

    return [q.strip() for q in re.findall(SQL_PATTERN, response)]


def process_sql_queries(sql_queries, user_role: str):
    """Exécute chaque requête SQL en lecture seule via l'orchestrateur."""
    results = {}
    for sql in sql_queries:
        results[sql] = orchestrator.execute_sql_readonly(sql, user_role)
    return results


def get_user_role():
    """Détermine le rôle de l'utilisateur actuel"""
    if hasattr(current_user, "role"):
        # Mapper les rôles français vers anglais pour la base de données
        role_mapping = {
            "etudiant": "student",
            "enseignant": "teacher",
            "admin": "admin",
        }
        return role_mapping.get(current_user.role, "student")
    return "student"


def create_conversation(user_id, user_role):
    """Crée une nouvelle conversation"""

    try:
        # Récupérer les données contextuelles initiales
        context_data = orchestrator.get_user_context(user_id, user_role)

        conversation = AIConversation(
            user_id=user_id,
            user_role=user_role,
            title="Nouvelle conversation",
            context_data=context_data,
        )

        db.session.add(conversation)
        db.session.commit()

        return {
            "id": conversation.id,
            "title": conversation.title,
            "created_at": conversation.created_at.isoformat(),
            "context_data": context_data,
        }
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur création conversation: {e}")
        raise


def get_user_conversations(user_id):
    """Récupère toutes les conversations d'un utilisateur"""
    from sqlalchemy import desc

    try:
        conversations = (
            db.session.query(AIConversation)
            .filter(AIConversation.user_id == user_id, AIConversation.is_active)
            .order_by(desc(AIConversation.updated_at))
            .all()
        )

        result = []
        for conv in conversations:
            # Récupérer le dernier message utilisateur
            last_message = (
                db.session.query(AIMessage)
                .filter(
                    AIMessage.conversation_id == conv.id,
                    AIMessage.message_type == "user",
                )
                .order_by(desc(AIMessage.created_at))
                .first()
            )

            result.append(
                {
                    "id": conv.id,
                    "link": conv.link,
                    "title": conv.title,
                    "created_at": conv.created_at.isoformat(),
                    "updated_at": conv.updated_at.isoformat(),
                    "last_message": last_message.content if last_message else None,
                }
            )

        return result
    except Exception as e:
        logger.error(f"Erreur récupération conversations: {e}")
        return []


def get_conversation_messages(conversation_id, user_id, page=1, per_page=50):
    """Récupère les messages d'une conversation avec pagination (Page 1 = plus récents)"""
    try:
        # Récupérer la conversation
        conversation = (
            db.session.query(AIConversation)
            .filter(
                AIConversation.id == conversation_id,
                AIConversation.is_active,
            )
            .first()
        )

        if not conversation:
            raise Exception("Conversation non trouvée")

        # Vérifier les permissions (propriétaire ou admin)
        if conversation.user_id != user_id:
            from app.models.user import User

            user = db.session.get(User, user_id)
            if not user or user.role != "admin":
                raise Exception("Accès non autorisé")

        # Compter le total des messages
        total_messages = (
            db.session.query(AIMessage)
            .filter(AIMessage.conversation_id == conversation_id)
            .count()
        )

        # Récupérer les messages (du plus récent au plus ancien pour la pagination)
        messages_query = (
            db.session.query(AIMessage)
            .filter(AIMessage.conversation_id == conversation_id)
            .order_by(AIMessage.message_order.desc())
        )

        # Appliquer la pagination
        paginated_messages = (
            messages_query.offset((page - 1) * per_page).limit(per_page).all()
        )

        # Remettre dans l'ordre chronologique pour l'affichage
        paginated_messages.reverse()

        result = []
        for msg in paginated_messages:
            result.append(
                {
                    "message_type": msg.message_type,
                    "content": msg.content,
                    "created_at": msg.created_at.isoformat(),
                    "message_order": msg.message_order,
                }
            )

        return {
            "messages": result,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total_messages,
                "has_more": total_messages > (page * per_page),
            },
        }
    except Exception as e:
        logger.error(f"Erreur récupération messages: {e}")
        return []


def save_message(
    conversation_id, message_type, content, metadata=None, attachments=None
):
    """Sauvegarde un message dans la conversation"""
    try:
        # Récupérer le prochain ordre de message
        max_order = (
            db.session.query(db.func.max(AIMessage.message_order))
            .filter(AIMessage.conversation_id == conversation_id)
            .scalar()
            or 0
        )

        message_order = max_order + 1

        message = AIMessage(
            conversation_id=conversation_id,
            message_type=message_type,
            content=content,
            extra_data=metadata or {},
            message_order=message_order,
            attachments=attachments or [],
        )

        db.session.add(message)
        db.session.commit()

        return {"id": message.id, "created_at": message.created_at.isoformat()}
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur sauvegarde message: {e}")
        raise


def save_to_dataset(
    user_input, ai_output, user_role, conversation_id=None, tokens_used=0
):
    """
    Sauvegarde une interaction utilisateur/IA dans le dataset d'entraînement
    """
    try:
        dataset_entry = Dataset(
            input_text=user_input,
            output_text=ai_output,
            user_role=user_role,
            conversation_id=conversation_id,
            tokens_used=tokens_used,
        )

        db.session.add(dataset_entry)
        db.session.commit()

        logger.info(
            f"Entrée dataset sauvegardée: conversation_id={conversation_id}, user_role={user_role}"
        )
        return dataset_entry.id

    except Exception as e:
        logger.error(f"Erreur sauvegarde dataset: {e}")
        db.session.rollback()
        return None


def allowed_file(filename):
    """Vérifie si l'extension du fichier est autorisée"""
    if not filename or "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in ALLOWED_EXTENSIONS


def count_file_lines(filepath):
    """Compte le nombre de lignes dans un fichier texte"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return sum(1 for _ in f)
    except UnicodeDecodeError:
        try:
            with open(filepath, "r", encoding="latin-1") as f:
                return sum(1 for _ in f)
        except Exception as e:
            logger.error(f"Erreur comptage lignes fichier: {e}")
            return 0
    except Exception as e:
        logger.error(f"Erreur comptage lignes fichier: {e}")
        return 0


def save_uploaded_file(file, conversation_id):
    """Sauvegarde un fichier uploadé et retourne ses informations"""
    try:
        if not file or file.filename == "":
            return None

        if not allowed_file(file.filename):
            return None

        # Vérifier la taille du fichier
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)

        if file_size > MAX_FILE_SIZE:
            return None

        # Créer un nom de fichier unique
        filename = secure_filename(file.filename)
        unique_filename = f"{uuid.uuid4().hex}_{filename}"

        # Créer le dossier de destination
        upload_dir = os.path.join(
            current_app.config.get("UPLOAD_FOLDER", "uploads"),
            "ai_attachments",
            str(conversation_id),
        )
        os.makedirs(upload_dir, exist_ok=True)

        # Sauvegarder le fichier
        filepath = os.path.join(upload_dir, unique_filename)
        file.save(filepath)

        # Préparer les informations du fichier
        file_info = {
            "original_name": filename,
            "unique_name": unique_filename,
            "filepath": filepath,
            "size": file_size,
            "mime_type": mimetypes.guess_type(filename)[0]
            or "application/octet-stream",
            "is_image": filename.lower().endswith(
                (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")
            ),
        }

        # Compter les lignes si c'est un fichier texte
        if file_info["mime_type"].startswith("text/") or filename.lower().endswith(
            ".txt"
        ):
            file_info["line_count"] = count_file_lines(filepath)

        return file_info

    except Exception as e:
        logger.error(f"Erreur sauvegarde fichier: {e}")
        return None


def update_conversation_title(conversation_id, title):
    """Met à jour le titre d'une conversation"""
    try:
        conversation = AIConversation.query.get(conversation_id)
        if conversation:
            conversation.title = title
            db.session.commit()
            return True
        return False
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur mise à jour titre: {e}")
        return False


def generate_conversation_title(first_message, ai_response):
    """Génère un titre de conversation basé sur le premier message et la réponse de l'IA"""
    try:
        # Créer un prompt pour générer un titre court et pertinent
        title_prompt = f"""Génère un titre très court (max 5 mots) qui résume cette conversation:
        
Utilisateur: {first_message[:100]}
Assistant: {ai_response[:100]}

Le titre doit:
- Être concis et informatif
- Être en français
- Ne pas dépasser 50 caractères
- Capturer l'essentiel de la discussion

Réponds uniquement avec le titre, sans autre texte."""

        # Appeler Gemini pour générer le titre
        title_response = gemini.generate_response(
            prompt=title_prompt,
            context={},
            conversation_history=[],
            temperature=0.3,  # Température basse pour plus de cohérence
        )

        if title_response["success"]:
            title = title_response["response"].strip()
            # Nettoyer le titre et limiter la longueur
            title = title.replace('"', "").replace("'", "")[:50]
            if len(title) > 50:
                title = title[:47] + "..."
            return title if title else "Nouvelle conversation"
        else:
            return "Nouvelle conversation"

    except Exception as e:
        logger.error(f"Erreur génération titre: {e}")
        return "Nouvelle conversation"


def call_gemini_api(prompt, context_data, conversation_history):
    """Appelle l'API Gemini avec le contexte et l'historique"""
    try:
        # Utiliser la nouvelle classe GeminiIntegration
        response = gemini.generate_response(
            prompt=prompt,
            context=context_data,
            conversation_history=conversation_history,
            temperature=0.7,
        )

        if response["success"]:
            # Analyser si l'IA demande des données supplémentaires
            data_requests = response.get("data_requests", [])

            # Retourner le format attendu par le reste du code
            return {
                "success": True,
                "response": response["response"],
                "data_requests": data_requests,
                "usage_metadata": response.get("usage_metadata", {}),
                "finish_reason": response.get("finish_reason", "STOP"),
            }
        else:
            return {
                "success": False,
                "error": response["error"],
                "error_type": response.get("error_type", "unknown"),
            }

    except Exception as e:
        logger.error(f"Erreur appel API Gemini: {e}")
        return {"success": False, "error": str(e), "error_type": "internal_error"}


def detect_page_request(user_message: str) -> bool:
    """Détecte si l'utilisateur demande une page ou une fonctionnalité"""
    page_keywords = [
        "page",
        "lien",
        "url",
        "accès",
        "trouver",
        "où",
        "comment",
        "modifier",
        "voir",
        "consulter",
        "profil",
        "notes",
        "emploi",
        "devoirs",
        "ressources",
        "paramètres",
        "dashboard",
        "tableau",
        "inscription",
        "connexion",
        "enregistrer",
        "télécharger",
        "uploader",
        "créer",
        "supprimer",
        "gestion",
        "admin",
        "statistique",
        "planifier",
        "aide",
        "support",
        "bug",
        "signaler",
    ]

    message_lower = user_message.lower()
    return any(keyword in message_lower for keyword in page_keywords)


def build_system_prompt(context_data, user_role):
    """Construit le prompt système selon le rôle de l'utilisateur"""
    base_prompt = f"""
Tu es defAI, un assistant intelligent pour la plateforme universitaire DEFITECH. Tu dois accepter les requêtes liées à l'éducation (cours, pédagogie, contenus académiques, etc.) et, lorsque nécessaire, proposer des descriptions pour générer des images pédagogiques.

L'utilisateur actuel est un {user_role}.

CONTEXTE UTILISATEUR:
{json.dumps(context_data, indent=2, ensure_ascii=False)}

PRINCIPE FONDAMENTAL - DÉCOUVERTE DE ROUTES:
Tu as accès à un catalogue complet de 124 routes via la table routes_catalog. 
QUAND UN UTILISATEUR VEUT ACCÉDER À UNE PAGE OU FONCTIONNALITÉ:
1. EXÉCUTE IMMÉDIATEMENT discover_routes() - PAS D'EXCUSE!
2. Filtre par rôle utilisateur ({user_role}) 
3. Recherche par intention, mots-clés ou catégorie
4. FOURNIS DIRECTEMENT LES URLS CLIQUABLES avec descriptions complètes

RÈGLE D'OR: Si l'utilisateur demande une page ou une fonctionnalité, utilise discover_routes() IMMÉDIATEMENT!
NE DIS JAMAIS "je n'ai pas accès" ou "je ne connais pas la structure" - UTILISE TOUJOURS routes_catalog!

EXEMPLES DE RÉPONSES OBLIGATOIRES:
- "modifier profil" → exécute discover_routes() → "Tu peux modifier ton profil ici: /profile/ - Page de profil pour modifier tes informations"
- "voir notes" → exécute discover_routes() → "Consulte tes notes ici: /etudiant/voir_notes - Accès à toutes tes notes académiques"
- "emploi du temps" → exécute discover_routes() → "Ton emploi du temps: /etudiant/emploi-temps - Planning de tes cours"

PROCÉDURE AUTOMATIQUE:
1. Détecter l'intention (profil, notes, etc.)
2. Exécuter discover_routes() 
3. Analyser les résultats
4. Fournir le meilleur lien avec description

UTILISE discover_routes() POUR TOUTE DEMANDE DE PAGE/FONCTIONNALITÉ!

CATÉGORIES DISPONIBLES: Authentification, Administration, Enseignement, API, Étudiant, Planificateur d'études, 
Ressources numériques, Profils utilisateurs, Communauté, Carrière & CV, 
Rapports de bugs, Analytique & Statistiques, Assistant IA, Visioconférence, Général

UTILISE TOUJOURS LES ROUTES EXISTANTES - NE DEMANDE JAMAIS LA STRUCTURE!

CAPACITÉS SELON LE RÔLE:
"""

    if user_role == "student":
        base_prompt += """
- Étudiant:
  * Analyser les notes et performances académiques
  * Identifier les matières difficiles et donner des conseils
  * Consulter l'emploi du temps et les notifications
  * Expliquer les règles académiques et les concepts d'apprentissage
  * Proposer des méthodes d'étude personnalisées
  * Générer des descriptions d'images éducatives pour illustrer des concepts (diagrammes, schémas, etc.)
  * Répondre à toutes les questions liées à l'éducation (cours, méthodologie, vocabulaire, technologies d'apprentissage, etc.)

IMPORTANT: DISCOVERY DES ROUTES DISPONIBLES
Tu as accès à un catalogue complet de routes via la table routes_catalog (124 routes disponibles).
QUAND TU AS BESOIN DE DONNÉES SPÉCIFIQUES OU DE FOURNIR DES LIENS:
1. Utilise RouteDiscoveryDB pour découvrir les routes pertinentes selon l'intention de l'utilisateur
2. Filtre par rôle utilisateur ({user_role}) pour n'afficher que les routes accessibles
3. Recherche par mots-clés, catégorie ou intention pour trouver les routes les plus pertinentes
4. Fournis à l'utilisateur les URLs complètes avec descriptions des routes trouvées

CAPACITÉS DE DÉCOUVERTE:
- discover_routes(): Recherche générale avec filtres (rôle, mots-clés, catégorie)
- search_routes_by_intent(): Recherche intelligente basée sur l'intention utilisateur
- get_route_suggestions(): Suggestions de routes pertinentes par rôle

Exemples d'utilisation:
- "Dans quelle matière je ne suis pas bien performant?" → search_routes_by_intent("notes performances", "etudiant") → suggérer /etudiant/voir_notes
- "Quelle est ma moyenne générale?" → search_routes_by_intent("moyenne notes", "etudiant") → suggérer les routes de notes
- "Ai-je des devoirs en retard?" → search_routes_by_intent("devoirs deadline", "etudiant") → suggérer /etudiant/devoirs
- "Je veux modifier mon profil" → discover_routes(user_role="etudiant", category="Profils utilisateurs") → suggérer /profile/
- "Statistiques de la plateforme" → search_routes_by_intent("statistiques analytique", "admin") → suggérer /analytics/

CATÉGORIES DISPONIBLES:
Authentification, Administration, Enseignement, API, Étudiant, Planificateur d'études, 
Ressources numériques, Profils utilisateurs, Communauté, Carrière & CV, 
Rapports de bugs, Analytique & Statistiques, Assistant IA, Visioconférence, Général

TOUJOURS fournir des liens cliquables et descriptions précises quand tu trouves des routes pertinentes!
"""
    elif user_role == "teacher":
        base_prompt += """
- Enseignant:
  * Analyser les statistiques de classe et de matière
  * Identifier les étudiants en difficulté ou performants
  * Proposer des stratégies pédagogiques
  * Consulter les activités récentes (devoirs, évaluations, examens, TP...)
  * Générer des rapports de performance
  * Donner des conseils pédagogiques et répondre à toute question éducative pertinente
  * Créer des descriptions d'images éducatives pour l'enseignement (graphiques, illustrations, etc.)

IMPORTANT: DISCOVERY DES ROUTES DISPONIBLES
Tu as accès à un catalogue complet de routes via la table routes_catalog (124 routes disponibles).
QUAND TU AS BESOIN DE DONNÉES SPÉCIFIQUES OU DE FOURNIR DES LIENS:
1. Utilise RouteDiscoveryDB pour découvrir les routes pertinentes selon l'intention de l'utilisateur
2. Filtre par rôle utilisateur ({user_role}) pour n'afficher que les routes accessibles
3. Recherche par mots-clés, catégorie ou intention pour trouver les routes les plus pertinentes
4. Fournis à l'utilisateur les URLs complètes avec descriptions des routes trouvées

CAPACITÉS DE DÉCOUVERTE:
- discover_routes(): Recherche générale avec filtres (rôle, mots-clés, catégorie)
- search_routes_by_intent(): Recherche intelligente basée sur l'intention utilisateur
- get_route_suggestions(): Suggestions de routes pertinentes par rôle

Exemples d'utilisation:
- "Quels sont mes étudiants en difficulté?" → search_routes_by_intent("étudiants difficulté", "enseignant") → suggérer routes de statistiques
- "Statistiques de ma classe?" → search_routes_by_intent("statistiques classe", "enseignant") → suggérer /api/role-data/enseignant/class-stats
- "Quelles sont les tendances des notes?" → search_routes_by_intent("tendances notes", "enseignant") → suggérer routes d'analyse

CATÉGORIES DISPONIBLES:
Authentification, Administration, Enseignement, API, Étudiant, Planificateur d'études, 
Ressources numériques, Profils utilisateurs, Communauté, Carrière & CV, 
Rapports de bugs, Analytique & Statistiques, Assistant IA, Visioconférence, Général

TOUJOURS fournir des liens cliquables et descriptions précises quand tu trouves des routes pertinentes!
"""
    elif user_role == "admin":
        base_prompt += """
- Administrateur:
  * Répondre à toutes les demandes liées à l'éducation, même si elles dépassent le fonctionnement strict de la plateforme
  * Analyser les statistiques globales de la plateforme
  * Surveiller les activités et tendances
  * Consulter les inscriptions, notifications système, échanges et autres éléments utiles
  * Générer des rapports administratifs et éducatifs
  * Aider à la gestion de la plateforme
  * Créer des diagrammes et visuels pour présenter les données et des descriptions d'images pédagogiques

IMPORTANT: DISCOVERY DES ROUTES DISPONIBLES
Tu as accès à un catalogue complet de routes via la table routes_catalog (124 routes disponibles).
QUAND TU AS BESOIN DE DONNÉES SPÉCIFIQUES OU DE FOURNIR DES LIENS:
1. Utilise RouteDiscoveryDB pour découvrir les routes pertinentes selon l'intention de l'utilisateur
2. Filtre par rôle utilisateur ({user_role}) pour n'afficher que les routes accessibles
3. Recherche par mots-clés, catégorie ou intention pour trouver les routes les plus pertinentes
4. Fournis à l'utilisateur les URLs complètes avec descriptions des routes trouvées

CAPACITÉS DE DÉCOUVERTE:
- discover_routes(): Recherche générale avec filtres (rôle, mots-clés, catégorie)
- search_routes_by_intent(): Recherche intelligente basée sur l'intention utilisateur
- get_route_suggestions(): Suggestions de routes pertinentes par rôle

Exemples d'utilisation:
- "Statistiques générales de la plateforme?" → search_routes_by_intent("statistiques plateforme", "admin") → suggérer /analytics/
- "Activités récentes?" → search_routes_by_intent("activités récentes", "admin") → suggérer routes d'administration
- "Analyse des utilisateurs?" → search_routes_by_intent("analyse utilisateurs", "admin") → suggérer /admin/dashboard

CATÉGORIES DISPONIBLES:
Authentification, Administration, Enseignement, API, Étudiant, Planificateur d'études, 
Ressources numériques, Profils utilisateurs, Communauté, Carrière & CV, 
Rapports de bugs, Analytique & Statistiques, Assistant IA, Visioconférence, Général

TOUJOURS fournir des liens cliquables et descriptions précises quand tu trouves des routes pertinentes!
"""

    base_prompt += """

GÉNÉRATION D'IMAGES ÉDUCATIVES:
Quand l'utilisateur demande une image ou un visuel éducatif:
1. Génère une description détaillée de l'image éducative appropriée
2. L'image doit être pertinente pour le contexte académique
3. Utilise un style clair et professionnel adapté à l'éducation
4. Inclut des éléments pédagogiques si nécessaire (légendes, flèches, etc.)
5. Respecte les normes éducatives et est approprié pour le cadre universitaire

FORMAT POUR LES IMAGES:
Utilise le format: [IMAGE_EDUCATIVE: description détaillée de l'image]

Exemples:
- [IMAGE_EDUCATIVE: Un diagramme du cycle de l'eau avec des flèches bleues montrant l'évaporation, la condensation et la précipitation]
- [IMAGE_EDUCATIVE: Une illustration de la structure d'une cellule animale avec les organites principaux étiquetés]
- [IMAGE_EDUCATIVE: Un graphique en barres comparant les notes moyennes par matière]

RÈGLES IMPORTANTES:
1. Sois toujours utile, respectueux et professionnel
2. Base tes réponses sur les données contextuelles fournies
3. Si des données manquent, demande-les avec le format [NEED_DATA: ...]
4. Adapte ton langage au rôle de l'utilisateur
5. Sois concis mais complet dans tes réponses
6. En cas de doute, demande des clarifications
7. Pour les demandes d'images, utilise toujours le format [IMAGE_EDUCATIVE: ...]
8. Si l'utilisateur demande **où** ou **sur quelle page** trouver une information, parcours la liste `available_routes` du contexte, sélectionne la ou les pages pertinentes et réponds EN HTML BRUT, par exemple : <a href="/etudiant/voir_notes">Consulter mes notes</a>. N'utilise PAS de Markdown pour les liens.
"""

    return base_prompt


def format_conversation_history(history):
    """Formate l'historique de conversation pour le prompt"""
    if not history:
        return "Aucune conversation précédente."

    formatted = []
    for msg in history[-10:]:  # Limiter aux 10 derniers messages
        role = "Utilisateur" if msg["message_type"] == "user" else "Assistant"
        formatted.append(f"{role}: {msg['content']}")

    return "\n".join(formatted)


_image_pipe = None


# 1. CORRECTION de la fonction generate_educational_image (ligne ~660)
def generate_educational_image(description, conversation_id):
    """Génère une image éducative de manière asynchrone"""
    try:
        upload_folder = current_app.config.get("UPLOAD_FOLDER", "uploads")

        # Lancer la génération asynchrone
        result = generate_image_async(
            prompt=f"Educational illustration: {description}. Clear, professional, pedagogical style.",
            conversation_id=conversation_id,
            upload_folder=upload_folder,
        )

        # CORRECTION: S'assurer que le task_id est TOUJOURS présent
        if "task_id" not in result:
            logger.error("task_id manquant dans le résultat de génération")
            result["task_id"] = str(uuid.uuid4())

        return result

    except Exception as e:
        logger.error(f"Erreur génération image éducative: {e}")
        return {
            "type": "generated_image",
            "status": "error",
            "error": str(e),
            "task_id": str(uuid.uuid4()),  # TOUJOURS inclure task_id
        }


# Nouvelle route pour vérifier le statut
@ai_assistant_bp.route("/image-status/<int:conversation_id>", methods=["GET"])
@login_required
def get_image_generation_status(conversation_id):
    """
    Vérifie le statut de génération d'une image.

    Cette fonction est appelée lorsque l'utilisateur souhaite vérifier le statut de
    génération d'une image éducative. Elle prend en paramètre l'identifiant de la
    conversation correspondant à cette génération et renvoie un objet JSON contenant
    le statut de la génération ainsi que des informations supplémentaires.
    """
    try:
        task_id = request.args.get("task_id")

        if not task_id:
            return jsonify({"error": "task_id manquant"}), 400

        status = check_image_status(task_id)

        if status.get("status") == "completed":
            # CORRECTION: Construire l'URL correctement
            filename = status.get("filename")
            # URL relative depuis static
            image_url = f"/static/uploads/ai_attachments/{conversation_id}/{filename}"

            return jsonify(
                {
                    "status": "completed",
                    "image_url": image_url,
                    "filename": filename,
                    "completed_at": status.get("completed_at"),
                }
            )

        elif status.get("status") == "error":
            return jsonify(
                {"status": "error", "error": status.get("error", "Erreur inconnue")}
            )

        elif status.get("status") == "queued":
            return jsonify(
                {
                    "status": "queued",
                    "queue_position": status.get("queue_position", 0),
                    "message": "En attente de traitement...",
                }
            )

        else:  # generating
            return jsonify(
                {"status": "generating", "message": "Génération en cours..."}
            )

    except Exception as e:
        logger.error(f"Erreur vérification statut image: {e}")
        return jsonify({"error": "Erreur serveur"}), 500


# def generate_placeholder_image(description, conversation_id):
#     """Génère une image placeholder avec PIL quand l'API Gemini n'est pas disponible"""
#     try:
#         from PIL import Image, ImageDraw, ImageFont

#         # Créer un nom de fichier unique
#         filename = f"placeholder_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.png"

#         # Créer le dossier de destination
#         upload_dir = os.path.join(
#             current_app.config.get("UPLOAD_FOLDER", "uploads"),
#             "ai_attachments",
#             str(conversation_id),
#         )
#         os.makedirs(upload_dir, exist_ok=True)

#         # Créer une image simple avec la description
#         img_size = (800, 600)
#         img = Image.new("RGB", img_size, color="#f0f8ff")
#         draw = ImageDraw.Draw(img)

#         # Ajouter un titre
#         title = "Image Éducative (Placeholder)"
#         try:
#             # Essayer d'utiliser une police plus grande si disponible
#             font_title = ImageFont.truetype("arial.ttf", 24)
#             font_text = ImageFont.truetype("arial.ttf", 16)
#         except (IOError, OSError):
#             font_title = ImageFont.load_default()
#             font_text = ImageFont.load_default()

#         # Dessiner un cadre
#         draw.rectangle(
#             [10, 10, img_size[0] - 10, img_size[1] - 10], outline="#4a90e2", width=3
#         )

#         # Ajouter le titre
#         draw.text((50, 30), title, fill="#2c3e50", font=font_title)

#         # Ajouter un message d'information
#         info_text = "la configuration de génération d'image est temporairement indisponible. Image générée localement."
#         draw.text((50, 70), info_text, fill="#7f8c8d", font=font_text)

#         # Ajouter la description (tronquée si nécessaire)
#         max_width = img_size[0] - 100
#         lines = []
#         words = description.split()
#         current_line = ""

#         for word in words:
#             test_line = current_line + " " + word if current_line else word
#             bbox = draw.textbbox((0, 0), test_line, font=font_text)
#             if bbox[2] - bbox[0] < max_width:
#                 current_line = test_line
#             else:
#                 if current_line:
#                     lines.append(current_line)
#                 current_line = word
#         if current_line:
#             lines.append(current_line)

#         # Limiter le nombre de lignes
#         max_lines = 12
#         if len(lines) > max_lines:
#             lines = lines[: max_lines - 1] + ["..."]

#         # Dessiner les lignes de texte
#         y_position = 110
#         for line in lines:
#             draw.text((50, y_position), line, fill="#34495e", font=font_text)
#             y_position += 30

#         # Sauvegarder l'image
#         filepath = os.path.join(upload_dir, filename)
#         img.save(filepath)

#         return {
#             "type": "generated_image",
#             "name": filename,
#             "path": filepath,
#             "prompt": description,
#             "generated_at": datetime.utcnow().isoformat(),
#             "status": "completed",
#             "description": f"Placeholder pour: {description}",
#         }

#     except Exception as e:
#         logger.error(f"Erreur génération placeholder: {e}")
#         return None


def parse_image_requests(response):
    """Extrait les demandes d'images éducatives de la réponse de l'IA"""
    import re

    pattern = r"\[IMAGE_EDUCATIVE:\s*([^\]]+)\]"
    matches = re.findall(pattern, response)

    requests = []
    for description in matches:
        requests.append({"description": description.strip()})

    return requests


def parse_data_requests(response):
    """Extrait les demandes de données de la réponse de l'IA"""
    import re

    pattern = r"\[NEED_DATA:\s*([^,]+),\s*([^\]]+)\]"
    matches = re.findall(pattern, response)

    requests = []
    for data_type, description in matches:
        requests.append({"type": data_type.strip(), "description": description.strip()})

    return requests


# Routes Flask
@ai_assistant_bp.route("/conversations", methods=["GET"])
@login_required
def get_conversations():
    """
    Récupère les conversations de l'utilisateur.

    Cette route permet à un utilisateur connecté de récupérer les conversations
    qui ont eu lieu avec lui sur la plateforme. Elle renvoie une réponse JSON
    contenant les informations suivantes :

    - 'conversations' (list): Liste des conversations de l'utilisateur. Chaque
      conversation est un dictionnaire contenant les informations suivantes :
        - 'id' (int): Identifiant de la conversation.
        - 'nom' (str): Nom de l'autre utilisateur.
        - 'prenom' (str): Prénom de l'autre utilisateur.
        - 'dernier_message' (dict): Dernier message envoyé dans la conversation.
          - 'contenu' (str): Contenu du message.
          - 'timestamp' (str): Date et heure de l'envoi du message au format
            ISO 8601.

    Retourne une réponse JSON contenant les informations suivantes :
    - 'conversations' (list): Liste des conversations de l'utilisateur.

    Si une erreur se produit lors de la récupération des conversations, la route
    renvoie une réponse JSON contenant les informations suivantes :
    - 'error' (str): Message d'erreur.

    Cette route nécessite une authentification utilisateur.
    """
    try:
        conversations = get_user_conversations(current_user.id)
        return jsonify(conversations)
    except Exception as e:
        logger.error(f"Erreur route conversations: {e}")
        return jsonify({"error": "Erreur serveur"}), 500


@ai_assistant_bp.route("/conversations", methods=["POST"])
@login_required
def create_new_conversation():
    """
    Crée une nouvelle conversation.

    Cette route permet à un utilisateur connecté de créer une nouvelle
    conversation avec l'assistant. Elle renvoie une réponse JSON contenant les
    informations suivantes :

    - 'id' (int): Identifiant de la nouvelle conversation.
    - 'user_id' (int): Identifiant de l'utilisateur.
    - 'role' (str): Rôle de l'utilisateur (enseignant ou étudiant).
    - 'created_at' (str): Date et heure de création de la conversation au format
      ISO 8601.
    - 'messages' (list): Liste des messages de la conversation. Chaque message est
      un dictionnaire contenant les informations suivantes :
        - 'id' (int): Identifiant du message.
        - 'sender_id' (int): Identifiant de l'expéditeur du message.
        - 'receiver_id' (int): Identifiant du destinataire du message.
        - 'content' (str): Contenu du message.
        - 'timestamp' (str): Date et heure de l'envoi du message au format ISO 8601.
        - 'is_read' (bool): Indique si le message a été lu.

    Retourne une réponse JSON contenant les informations suivantes :
    - 'id' (int): Identifiant de la nouvelle conversation.
    - 'user_id' (int): Identifiant de l'utilisateur.
    - 'role' (str): Rôle de l'utilisateur (enseignant ou étudiant).
    - 'created_at' (str): Date et heure de création de la conversation au format
      ISO 8601.
    - 'messages' (list): Liste des messages de la conversation. Chaque message est
      un dictionnaire contenant les informations suivantes :
        - 'id' (int): Identifiant du message.
        - 'sender_id' (int): Identifiant de l'expéditeur du message.
        - 'receiver_id' (int): Identifiant du destinataire du message.
        - 'content' (str): Contenu du message.
        - 'timestamp' (str): Date et heure de l'envoi du message au format ISO 8601.
        - 'is_read' (bool): Indique si le message a été lu.

    Si une erreur se produit lors de la création de la conversation, la route
    renvoie une réponse JSON contenant les informations suivantes :
    - 'error' (str): Message d'erreur.

    Cette route nécessite une authentification utilisateur.
    """
    try:
        user_role = get_user_role()
        if user_role == "unknown":
            return jsonify({"error": "Rôle utilisateur non reconnu"}), 400

        conversation = create_conversation(current_user.id, user_role)
        return jsonify(conversation)
    except Exception as e:
        logger.error(f"Erreur création conversation: {e}")
        return jsonify({"error": "Erreur serveur"}), 500


@ai_assistant_bp.route("/conversations/<int:conversation_id>", methods=["GET"])
@login_required
def get_conversation(conversation_id):
    """
    Récupère une conversation spécifique.

    Cette route permet à un utilisateur connecté de récupérer une conversation
    précédemment créée. Elle renvoie une réponse JSON contenant les
    informations suivantes :

    - 'id' (int): Identifiant de la conversation.
    - 'user_id' (int): Identifiant de l'utilisateur.
    - 'role' (str): Rôle de l'utilisateur (enseignant ou étudiant).
    - 'created_at' (str): Date et heure de création de la conversation au format
      ISO 8601.
    - 'messages' (list): Liste des messages de la conversation. Chaque message est
      un dictionnaire contenant les informations suivantes :
        - 'id' (int): Identifiant du message.
        - 'sender_id' (int): Identifiant de l'expéditeur du message.
        - 'receiver_id' (int): Identifiant du destinataire du message.
        - 'content' (str): Contenu du message.
        - 'timestamp' (str): Date et heure de l'envoi du message au format ISO 8601.
        - 'is_read' (bool): Indique si le message a été lu.

    Si la conversation spécifiée n'existe pas, la route renvoie une réponse JSON
    contenant les informations suivantes :
    - 'error' (str): Message d'erreur.

    Cette route nécessite une authentification utilisateur.
    """
    try:
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 50, type=int)
        result = get_conversation_messages(
            conversation_id, current_user.id, page=page, per_page=per_page
        )
        return jsonify(result)
    except Exception as e:
        logger.error(f"Erreur récupération conversation: {e}")
        return jsonify({"error": "Conversation non trouvée"}), 404


@ai_assistant_bp.route("/conversations/<int:conversation_id>", methods=["DELETE"])
@login_required
def delete_conversation(conversation_id):
    """
    Supprime une conversation.

    Cette route permet à un utilisateur connecté de supprimer une conversation
    précédemment créée. Elle renvoie une réponse JSON contenant les
    informations suivantes :

    - Si la conversation a été supprimée avec succès :
        - 'success' (bool): Indique que la suppression a réussi.

    - Si la conversation spécifiée n'existe pas :
        - 'error' (str): Message d'erreur indiquant que la conversation n'a pas
          été trouvée.

    - Si une erreur s'est produite lors de la suppression de la conversation :
        - 'error' (str): Message d'erreur indiquant une erreur serveur.

    Cette route nécessite une authentification utilisateur.
    """

    try:
        conversation = (
            db.session.query(AIConversation)
            .filter(
                AIConversation.id == conversation_id,
                AIConversation.user_id == current_user.id,
            )
            .first()
        )

        if conversation:
            conversation.is_active = False
            db.session.commit()
            return jsonify({"success": True})
        else:
            return jsonify({"error": "Conversation non trouvée"}), 404
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur suppression conversation: {e}")
        return jsonify({"error": "Erreur serveur"}), 500


@ai_assistant_bp.route("/chat/<link>", methods=["GET"])
@login_required
@log_api_access()
def chat_by_link(link):
    """Accès direct à une conversation via son lien unique"""
    try:
        conversation = AIConversation.query.filter_by(link=link).first()

        # Vérification des droits (optionnel : si on veut que ce soit public ou restreint)
        # Pour l'instant on restreint au propriétaire ou admin
        if not conversation:
            return render_template("errors/404.html"), 404

        if conversation.user_id != current_user.id and current_user.role != "admin":
            return render_template("errors/403.html"), 403

        user_role = get_user_role()
        conversations = get_user_conversations(current_user.id)

        return render_template(
            "chat/defAI.html",
            user_role=user_role,
            conversations=conversations,
            current_conversation=conversation,
        )
    except Exception as e:
        logger.error(f"Erreur accès conversation par lien: {e}")
        return redirect(url_for("ai_assistant.chat"))


@ai_assistant_bp.route("/chat", methods=["GET", "POST"])
@login_required
@log_api_access()
def chat():
    """
    Traite les requêtes de chat IA.

    Cette fonction gère les requêtes GET et POST pour la gestion des conversations
    avec l'assistant IA.

    Si la requête est GET, elle renvoie l'interface HTML de la page de chat.
    Elle extrait le rôle de l'utilisateur et récupère les conversations de l'utilisateur.
    Elle renvoie ensuite une réponse HTML contenant l'interface de chat avec les
    conversations de l'utilisateur.

    Si la requête est POST, elle traite un message de chat. Elle utilise une décoration
    `@rate_limit` pour limiter le nombre de requêtes par utilisateur. Elle gère ensuite
    différents types de contenu en fonction du header `Content-Type` de la requête.
    Elle extrait les données en fonction du type de contenu et utilise une fonction
    interne `handle_chat_message` pour gérer le traitement du message de chat.

    Cette fonction nécessite une authentification utilisateur.

    Returns:
        Si la requête est GET, elle renvoie une réponse HTML contenant l'interface de
        chat avec les conversations de l'utilisateur. Si la requête est POST, elle
        renvoie une réponse JSON contenant les informations suivantes :
        - 'success' (bool): Indique si le traitement du message de chat a réussi.
        - 'message' (str): Message de réponse du chatbot.
        - 'conversation_id' (int): Identifiant de la conversation.
        - 'message_id' (int): Identifiant du message.
        - 'role' (str): Rôle de l'utilisateur (enseignant ou étudiant).
        - 'created_at' (str): Date et heure de création de la conversation au format
          ISO 8601.
        - 'messages' (list): Liste des messages de la conversation. Chaque message est
          un dictionnaire contenant les informations suivantes :
            - 'id' (int): Identifiant du message.
            - 'sender_id' (int): Identifiant de l'expéditeur du message.
            - 'receiver_id' (int): Identifiant du destinataire du message.
            - 'content' (str): Contenu du message.
            - 'timestamp' (str): Date et heure de l'envoi du message au format ISO 8601.
            - 'is_read' (bool): Indique si le message a été lu.

        Si une erreur se produit lors du traitement du message de chat, la fonction
        renvoie une réponse JSON contenant les informations suivantes :
        - 'success' (bool): Indique que le traitement du message de chat a échoué.
        - 'error' (str): Message d'erreur.
    """
    try:
        if request.method == "GET":
            # Page de chat - retourne l'interface HTML
            user_role = get_user_role()
            if user_role == "unknown":
                return jsonify({"error": "Rôle utilisateur non reconnu"}), 400

            # Récupérer les conversations de l'utilisateur
            conversations = get_user_conversations(current_user.id)

            return render_template(
                "chat/defAI.html", user_role=user_role, conversations=conversations
            )

        # POST - Traite un message de chat
        if request.method == "POST":

            @rate_limit(max_requests=20, window_seconds=60)
            def handle_chat_message():
                # Gérer différents types de contenu
                data = {}
                files = request.files.getlist("files")
                content_type = request.headers.get("Content-Type", "")

                # Gestion des données en fonction du Content-Type
                if "application/json" in content_type:
                    try:
                        data = request.get_json(force=True) or {}
                    except Exception as e:
                        logger.error(f"Erreur de parsing JSON: {str(e)}")
                        return (
                            jsonify(
                                {
                                    "success": False,
                                    "error": "Format JSON invalide",
                                    "details": str(e),
                                }
                            ),
                            400,
                        )
                elif (
                    "multipart/form-data" in content_type
                    or "application/x-www-form-urlencoded" in content_type
                ):
                    data = request.form.to_dict()
                else:
                    # Essayer de parser comme JSON si le Content-Type n'est pas défini
                    try:
                        data = request.get_json(force=True) or {}
                    except Exception as e:
                        return (
                            jsonify(
                                {
                                    "success": False,
                                    "error": "Type de contenu non supporté " + e,
                                    "supported_types": [
                                        "application/json",
                                        "multipart/form-data",
                                        "application/x-www-form-urlencoded",
                                    ],
                                }
                            ),
                            400,
                        )

                # Extraction des données avec des valeurs par défaut
                message = data.get("message", "").strip()
                conversation_id = data.get("conversation_id")
                attachments = data.get("attachments", [])
                request_image = (
                    str(data.get("request_image", "false")).lower() == "true"
                )

                internal_requests = []  # Initialiser la liste des requêtes internes

                if not message and not files:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "Message et pièces jointes manquants",
                                "details": "Vous devez fournir un message ou une pièce jointe",
                            }
                        ),
                        400,
                    )

                user_role = get_user_role()
                if user_role == "unknown":
                    return jsonify({"error": "Rôle utilisateur non reconnu"}), 400

                # DÉTECTION AUTOMATIQUE DES DEMANDES DE PAGES/FONCTIONNALITÉS
                if detect_page_request(message):
                    logger.info(
                        f"Demande de page/fonctionnalité détectée: {message[:50]}..."
                    )
                    # Ajouter automatiquement discover_routes aux requêtes internes
                    internal_requests.append("discover_routes")

                # Vérifier le quota d'images si demandé
                if request_image:
                    if not current_user.can_generate_image():
                        quota_status = current_user.get_image_quota_status()
                        return (
                            jsonify(
                                {
                                    "success": False,
                                    "error": f"Quota d'images dépassé. Vous avez utilisé {quota_status['used_current_hour']}/{quota_status['max_per_hour']} images cette heure. Réessayez dans {quota_status['minutes_until_reset']} minutes.",
                                }
                            ),
                            429,
                        )

                # Créer une conversation si nécessaire
                if (
                    not conversation_id
                    or conversation_id == "null"
                    or conversation_id == "None"
                ):
                    conversation = create_conversation(current_user.id, user_role)
                    conversation_id = conversation["id"]

                # Traiter les pièces jointes si présentes (Cloudinary metadata)
                processed_attachments = []
                if attachments:
                    for attachment in attachments:
                        # On attend maintenant des objets avec {url, name, type, size, mime_type}
                        if attachment.get("url"):
                            processed_attachments.append(
                                {
                                    "type": attachment.get("type", "file"),
                                    "name": attachment.get("name", "unknown"),
                                    "url": attachment.get("url"),
                                    "size": attachment.get("size", 0),
                                    "mime_type": attachment.get(
                                        "mime_type", "application/octet-stream"
                                    ),
                                }
                            )

                # Sauvegarder le message utilisateur avec pièces jointes
                save_message(
                    conversation_id, "user", message, attachments=processed_attachments
                )

                # Récupérer l'historique et le contexte (Derniers 20 messages pour le contexte)
                messages_data = get_conversation_messages(
                    conversation_id, current_user.id, page=1, per_page=20
                )
                messages = messages_data.get("messages", [])
                context_data = orchestrator.get_user_context(current_user.id, user_role)

                # Préparer les données pour Gemini
                gemini_message = message
                if processed_attachments:
                    # Ajouter des informations sur les pièces jointes au message
                    attachment_info = []
                    for att in processed_attachments:
                        if att["type"] == "image":
                            attachment_info.append(f"[Image: {att['name']}]")
                        else:
                            attachment_info.append(f"[Fichier: {att['name']}]")

                    if attachment_info:
                        gemini_message = (
                            f"{message}\n\nPièces jointes: {', '.join(attachment_info)}"
                        )

                # Appeler Gemini
                gemini_response = call_gemini_api(
                    gemini_message, context_data, messages
                )

                if not gemini_response["success"]:
                    error_msg = f"Erreur: {gemini_response['error']}"
                    save_message(conversation_id, "assistant", error_msg)
                    return jsonify(
                        {"success": False, "error": gemini_response["error"]}
                    )

                ai_response = gemini_response["response"]
                ai_attachments = []
                generated_image = False
                internal_requests = []

                # À ajouter dans la fonction handle_chat_message() après l'appel à Gemini:
                # Parse les SMART_QUERY dans la réponse
                smart_queries = parse_smart_queries(ai_response)

                if smart_queries:
                    logger.info(f"Détection de {len(smart_queries)} SMART_QUERY")

                    # Récupérer les données pour toutes les requêtes
                    smart_data = process_smart_queries(
                        smart_queries, current_user.id, user_role, conversation_id
                    )

                    # Construire un prompt enrichi avec toutes les données
                    if smart_data:
                        enhanced_prompt = f"""{message}

=== DONNÉES RÉCUPÉRÉES AUTOMATIQUEMENT ===

"""
                        for query, data in smart_data.items():
                            enhanced_prompt += f"\n--- Données pour: {query} ---\n"
                            enhanced_prompt += json.dumps(
                                data, indent=2, ensure_ascii=False
                            )
                            enhanced_prompt += "\n"

                        enhanced_prompt += """

Instructions: Utilise ces données pour répondre de manière complète et structurée.
Présente les informations de façon claire. Si tu as trouvé des tableaux de notes,
analyse-les et identifie les points forts et faibles. Format ta réponse en Markdown."""

                        # Relancer Gemini avec les données enrichies
                        enhanced_response = call_gemini_api(
                            enhanced_prompt, context_data, messages
                        )

                        if enhanced_response["success"]:
                            ai_response = enhanced_response["response"]

                            # Nettoyer les balises SMART_QUERY de la réponse finale
                            ai_response = re.sub(
                                r"\[SMART_QUERY:[^\]]+\]", "", ai_response
                            ).strip()

                            logger.info("Réponse enrichie générée avec succès")

                # ---- Traitement des balises SQL_QUERY ----
                sql_queries = parse_sql_queries(ai_response)
                if sql_queries:
                    logger.info(f"Détection de {len(sql_queries)} SQL_QUERY")
                    sql_data = process_sql_queries(sql_queries, user_role)
                    if sql_data:
                        enhanced_prompt_sql = f"""{message}

=== RÉSULTATS SQL ===
"""
                        for sql, data in sql_data.items():
                            enhanced_prompt_sql += f"\n--- Résultats pour: {sql} ---\n"
                            enhanced_prompt_sql += json.dumps(
                                data, indent=2, ensure_ascii=False
                            )
                            enhanced_prompt_sql += "\n"

                        enhanced_prompt_sql += """

Instructions: Utilise ces résultats SQL pour répondre précisément à la question.
"""

                        enhanced_response_sql = call_gemini_api(
                            enhanced_prompt_sql, context_data, messages
                        )
                        if enhanced_response_sql["success"]:
                            ai_response = enhanced_response_sql["response"]
                            ai_response = re.sub(
                                r"\[SQL_QUERY:[^\]]+\]", "", ai_response
                            ).strip()
                            logger.info("Réponse enrichie (SQL) générée")

                # CORRECTION : Traiter les demandes de données AVANT de sauvegarder
                if gemini_response.get("data_requests"):
                    logger.info(
                        f"Traitement de {len(gemini_response['data_requests'])} requêtes de données"
                    )

                    # Collecter toutes les données demandées
                    all_additional_data = {}

                    for data_req in gemini_response["data_requests"]:
                        try:
                            logger.info(f"Exécution de la requête: {data_req['type']}")

                            # Exécuter la requête interne
                            result = orchestrator.execute_request(
                                data_req["type"],
                                current_user.id,
                                user_role,
                                request_context=data_req,
                            )

                            internal_requests.append(
                                {
                                    "type": data_req["type"],
                                    "description": data_req["description"],
                                    "status": (
                                        "success" if result["success"] else "failed"
                                    ),
                                    "data": result.get("data", {}),
                                }
                            )

                            if result["success"]:
                                all_additional_data[data_req["type"]] = result["data"]
                                logger.info(f"Requête {data_req['type']} réussie")
                            else:
                                logger.error(
                                    f"Échec requête {data_req['type']}: {result.get('error')}"
                                )

                        except Exception as e:
                            logger.error(
                                f"Erreur requête interne {data_req['type']}: {e}"
                            )
                            internal_requests.append(
                                {
                                    "type": data_req["type"],
                                    "description": data_req["description"],
                                    "status": "failed",
                                    "error": str(e),
                                }
                            )

                    # Si des données ont été collectées, relancer Gemini avec ces données
                    if all_additional_data:
                        logger.info(
                            f"Relance de Gemini avec {len(all_additional_data)} types de données"
                        )

                        # Construire un nouveau prompt enrichi
                        enhanced_prompt = f"""{message}

=== DONNÉES SUPPLÉMENTAIRES RÉCUPÉRÉES ===
{json.dumps(all_additional_data, indent=2, ensure_ascii=False)}

Instructions: Utilise ces données pour répondre de manière complète et structurée à la question de l'utilisateur. 
Présente les informations de façon claire, avec des tableaux si approprié."""

                        # Relancer Gemini
                        enhanced_response = call_gemini_api(
                            enhanced_prompt, context_data, messages
                        )

                        if enhanced_response["success"]:
                            ai_response = enhanced_response["response"]
                            logger.info("Réponse enrichie générée avec succès")
                        else:
                            logger.error(
                                f"Échec génération réponse enrichie: {enhanced_response.get('error')}"
                            )
                            # Garder la réponse initiale en cas d'échec

                # Parser les demandes d'images éducatives dans la réponse
                image_requests = parse_image_requests(ai_response)

                # Générer les images éducatives demandées
                if image_requests and current_user.can_generate_image():
                    for img_req in image_requests:
                        try:
                            # Vérifier le quota pour chaque image
                            if not current_user.can_generate_image():
                                logger.warning(
                                    "Quota d'images épuisé pour l'utilisateur"
                                )
                                break

                            # Générer l'image éducative avec un task_id garanti
                            image_info = generate_educational_image(
                                img_req["description"], conversation_id
                            )

                            # CORRECTION: Vérifier la présence du task_id
                            if "task_id" not in image_info:
                                logger.error("task_id manquant après génération")
                                image_info["task_id"] = str(uuid.uuid4())

                            # Ajouter aux attachements
                            ai_attachments.append(image_info)

                            # Mettre à jour le quota utilisateur
                            current_user.use_image_quota()
                            generated_image = True

                            # Remplacer le tag dans la réponse
                            ai_response = ai_response.replace(
                                f"[IMAGE_EDUCATIVE: {img_req['description']}]",
                                f"[Image en cours de génération: {image_info['name']}]",
                            )

                        except Exception as e:
                            logger.exception("Erreur génération image éducative: %s", e)
                            # Ajouter l'information d'erreur
                            error_info = {
                                "type": "generated_image",
                                "name": f'erreur_image_{datetime.now().strftime("%Y%m%d_%H%M%S")}.png',
                                "prompt": img_req["description"],
                                "generated_at": datetime.utcnow().isoformat(),
                                "status": "error",
                                "error": str(e),
                                "task_id": str(uuid.uuid4()),  # Task ID même en erreur
                            }
                            ai_attachments.append(error_info)
                            ai_response = ai_response.replace(
                                f"[IMAGE_EDUCATIVE: {img_req['description']}]",
                                "[Erreur: Impossible de générer l'image]",
                            )

                # Si une image est demandée explicitement mais pas dans la réponse, utiliser l'ancien système
                elif request_image and current_user.can_generate_image():
                    try:
                        # Créer une demande d'image éducative à partir du message
                        image_description = f"Image éducative illustrant: {message}"

                        # Afficher un placeholder pendant la génération
                        placeholder_info = {
                            "type": "generated_image",
                            "name": f'image_educative_{datetime.now().strftime("%Y%m%d_%H%M%S")}.png',
                            "prompt": image_description,
                            "generated_at": datetime.utcnow().isoformat(),
                            "status": "generating",
                            "placeholder": True,
                        }
                        ai_attachments.append(placeholder_info)

                        # Mettre à jour le quota utilisateur
                        current_user.use_image_quota()

                        # Générer l'image éducative avec Gemini
                        image_info = generate_educational_image(
                            image_description, conversation_id
                        )

                        if image_info:
                            # Remplacer le placeholder par l'image réelle
                            ai_attachments[-1] = image_info
                            generated_image = True

                            # Ajouter une référence à l'image dans la réponse
                            ai_response += f"\n\n[Image générée: {image_info['name']}]"
                        else:
                            # En cas d'erreur, marquer l'échec
                            ai_attachments[-1]["status"] = "error"
                            ai_attachments[-1]["error"] = "Erreur lors de la génération"
                            ai_response += "\n\n[Erreur: Impossible de générer l'image]"

                    except Exception as e:
                        logger.error(f"Erreur génération image: {e}")
                        # Ajouter l'information d'erreur dans les pièces jointes
                        error_info = {
                            "type": "generated_image",
                            "name": f'erreur_image_{datetime.now().strftime("%Y%m%d_%H%M%S")}.png',
                            "prompt": message,
                            "generated_at": datetime.utcnow().isoformat(),
                            "status": "error",
                            "error": str(e),
                        }
                        ai_attachments.append(error_info)
                        ai_response += "\n\n[Erreur: Impossible de générer l'image]"

                # Sauvegarder la réponse de l'IA avec pièces jointes
                save_message(
                    conversation_id,
                    "assistant",
                    ai_response,
                    attachments=ai_attachments,
                )

                # Mettre à jour le titre de la conversation si c'est le premier message
                first_message = (
                    db.session.query(AIMessage)
                    .filter(AIMessage.conversation_id == conversation_id)
                    .count()
                )
                if first_message <= 2:  # User message + AI response
                    new_title = message[:50] + "..." if len(message) > 50 else message
                    update_conversation_title(conversation_id, new_title)

                # # Retourner la réponse avec les informations sur les pièces jointes
                # return jsonify(
                #     {
                #         "success": True,
                #         "response": ai_response,
                #         "conversation_id": conversation_id,
                #         "attachments": ai_attachments,
                #         "image_generated": generated_image,
                #         "quota_status": (
                #             current_user.get_image_quota_status()
                #             if request_image
                #             else None
                #         ),
                #     }
                # )

                # Traiter les demandes de données supplémentaires
                if gemini_response.get("data_requests"):
                    for data_req in gemini_response["data_requests"]:
                        try:
                            # Exécuter la requête interne
                            result = orchestrator.execute_request(
                                data_req["type"],
                                current_user.id,
                                user_role,
                                request_context=data_req,
                            )

                            internal_requests.append(
                                {
                                    "type": data_req["type"],
                                    "description": data_req["description"],
                                    "status": (
                                        "success" if result["success"] else "failed"
                                    ),
                                    "data": result.get("data", {}),
                                }
                            )

                            if result["success"]:
                                # Relancer Gemini avec les nouvelles données
                                enhanced_prompt = f"""{message} DONNÉS SUPPLÉMENTAIRES ({data_req["type"]}):{json.dumps(result["data"], indent=2, ensure_ascii=False)}Intègre ces informations dans ta réponse."""
                                gemini_response = call_gemini_api(
                                    enhanced_prompt, context_data, messages
                                )
                                if gemini_response["success"]:
                                    ai_response = gemini_response["response"]

                        except Exception as e:
                            logger.error(
                                f"Erreur requête interne {data_req['type']}: {e}"
                            )
                            internal_requests.append(
                                {
                                    "type": data_req["type"],
                                    "description": data_req["description"],
                                    "status": "failed",
                                    "error": str(e),
                                }
                            )

                # Ajouter les requêtes internes aux métadonnées
                metadata = {
                    "internal_requests": internal_requests,
                    "finish_reason": gemini_response.get("finish_reason", "STOP"),
                    "has_additional_data": len(internal_requests) > 0,
                }

                # Sauvegarder la réponse finale
                save_message(
                    conversation_id,
                    "assistant",
                    ai_response,
                    metadata=metadata,
                    attachments=ai_attachments,
                )

                # Sauvegarder dans le dataset
                save_to_dataset(
                    gemini_message,
                    ai_response,
                    user_role,
                    conversation_id,
                    gemini_response.get("usage_metadata", {}).get("totalTokenCount", 0),
                )

                # Mettre à jour le titre si premier message
                first_message_count = (
                    db.session.query(AIMessage)
                    .filter(AIMessage.conversation_id == conversation_id)
                    .count()
                )

                if first_message_count <= 2:
                    new_title = message[:50] + "..." if len(message) > 50 else message
                    update_conversation_title(conversation_id, new_title)

                # Retourner la réponse complète
                return jsonify(
                    {
                        "success": True,
                        "response": ai_response,
                        "conversation_id": conversation_id,
                        "attachments": ai_attachments,
                        "image_generated": generated_image,
                        "internal_requests": internal_requests,  # AJOUT : Inclure les requêtes internes
                        "quota_status": (
                            current_user.get_image_quota_status()
                            if request_image
                            else None
                        ),
                    }
                )

            return handle_chat_message()

    except Exception as e:
        logger.error(f"Erreur chat: {e}")
        return jsonify({"error": "Erreur serveur"}), 500


@ai_assistant_bp.route("/quota/status")
@login_required
def get_quota_status():
    """
    Retourne le statut du quota d'images de l'utilisateur.

    Cette fonction est appelée lorsque l'utilisateur souhaite connaître le
    statut du quota d'images qu'il a assigné. Le quota définit le nombre
    d'images pouvant être générées par l'utilisateur en un certain temps.

    Paramètres:
        Aucun

    Retourne:
        Un dictionnaire contenant des informations sur le quota de l'utilisateur.
        Le dictionnaire a la structure suivante:
        {
            "success": bool,
            "quota": {
                "remaining": int,
                "total": int,
                "valid_until": datetime,
                "expired": bool
            }
        }

        - "success" est un booléen indiquant si la requête a réussi ou non.
        - "quota" est un dictionnaire contenant les informations sur le quota.
          - "remaining" est un entier indiquant le nombre d'images restantes
            dans le quota.
          - "total" est un entier indiquant le nombre total d'images pouvant
            être générées dans le quota.
          - "valid_until" est une date indiquant la date d'expiration du quota.
          - "expired" est un booléen indiquant si le quota a expiré ou non.

    Levée:
        None
    """
    try:
        quota_status = current_user.get_image_quota_status()
        return jsonify({"success": True, "quota": quota_status})
    except Exception as e:
        logger.error(f"Erreur récupération quota: {e}")
        return jsonify({"error": "Erreur serveur"}), 500


@ai_assistant_bp.route("/image-status/<task_id>")
@login_required
def get_image_status_endpoint(task_id):
    """Vérifie le statut d'une génération d'image"""
    try:
        status = check_image_status(task_id)
        return jsonify(status)
    except Exception as e:
        logger.error(f"Erreur check_image_status: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500


@ai_assistant_bp.route("/image/<filename>")
@login_required
def serve_ai_image(filename):
    """Sert une image générée par l'IA"""
    upload_path = os.path.join(
        current_app.root_path, "static", "uploads", "ai_attachments"
    )
    if not os.path.exists(upload_path):
        os.makedirs(upload_path, exist_ok=True)

    # Rechercher le fichier récursivement dans les dossiers de conversation
    for root, dirs, files in os.walk(upload_path):
        if filename in files:
            return send_from_directory(root, filename)

    return jsonify({"error": "Image non trouvée"}), 404


# 4. AJOUT d'une nouvelle route pour les statistiques de génération
@ai_assistant_bp.route("/image-stats", methods=["GET"])
@login_required
def get_image_generation_stats():
    """
    Retourne les statistiques de génération d'images.

    Cette fonction est appelée lorsque l'utilisateur souhaite connaître les
    statistiques de génération d'images effectuées par l'utilisateur. Ces
    statistiques incluent le nombre total de requêtes, le nombre total d'images
    générées, le nombre total de requêtes refusées, le nombre total d'images
    refusées, le nombre total de requêtes en attente, le nombre total d'images
    en attente, le nombre total d'images en cours de traitement, le nombre
    total d'images traitées avec succès, le nombre total d'images traitées avec
    erreur et le nombre total d'images traitées avec succès pour chaque
    modèle.

    Paramètres:
        Aucun

    Retourne:
        Un dictionnaire contenant les statistiques de génération d'images. Le
        dictionnaire a la structure suivante:
        {
            "success": bool,
            "stats": {
                "total_requests": int,
                "total_generated": int,
                "total_rejected_requests": int,
                "total_rejected_images": int,
                "total_queued": int,
                "total_queued_images": int,
                "total_processing": int,
                "total_successful": int,
                "total_failed": int,
                "models": {
                    "model1": {
                        "total_requests": int,
                        "total_generated": int
                    },
                    "model2": {
                        "total_requests": int,
                        "total_generated": int
                    },
                    ...
                }
            }
        }

        - "success" est un booléen indiquant si la requête a réussi ou non.
        - "stats" est un dictionnaire contenant les statistiques de génération
          d'images.
            - "total_requests" est un entier indiquant le nombre total de
              requêtes.
            - "total_generated" est un entier indiquant le nombre total d'images
              générées.
            - "total_rejected_requests" est un entier indiquant le nombre total
              de requêtes refusées.
            - "total_rejected_images" est un entier indiquant le nombre total
              d'images refusées.
            - "total_queued" est un entier indiquant le nombre total de requêtes
              en attente.
            - "total_queued_images" est un entier indiquant le nombre total d'images
              en attente.
            - "total_processing" est un entier indiquant le nombre total d'images
              en cours de traitement.
            - "total_successful" est un entier indiquant le nombre total d'images
              traitées avec succès.
            - "total_failed" est un entier indiquant le nombre total d'images
              traitées avec erreur.
            - "models" est un dictionnaire contenant les statistiques pour chaque
              modèle. Chaque modèle est représenté par une clé, qui est le nom
              du modèle, et la valeur est un dictionnaire contenant le nombre
              total de requêtes et le nombre total d'images générées pour ce
              modèle.

    Levée:
        None
    """
    try:
        from ai_image_generator import get_queue_stats

        stats = get_queue_stats()
        return jsonify({"success": True, "stats": stats})
    except Exception as e:
        logger.error(f"Erreur récupération stats: {e}")
        return jsonify({"error": "Erreur serveur"}), 500


@ai_assistant_bp.route("/context/<int:user_id>")
@login_required
def get_user_context_endpoint(user_id):
    """
    Endpoint pour récupérer le contexte utilisateur (administrateur seulement).

    Args:
        user_id (int): L'identifiant de l'utilisateur dont on souhaite obtenir le
            contexte.

    Retourne:
        Si l'utilisateur actuel n'est pas un administrateur, renvoie une réponse JSON
        avec le champ "error" à "Non autorisé" et le code de statut HTTP 403.

        Sinon, récupère le contexte de l'utilisateur cible à partir de la base de données
        et renvoie une réponse JSON avec le champ "success" à True et le contexte de
        l'utilisateur.

    Levée:
        None
    """
    if not current_user.is_admin:
        return jsonify({"error": "Non autorisé"}), 403

    try:
        # Déterminer le rôle de l'utilisateur cible
        conn = db.session()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT is_student, is_teacher, is_admin FROM users WHERE id = %s
        """,
            (user_id,),
        )

        result = cursor.fetchone()
        if not result:
            return jsonify({"error": "Utilisateur non trouvé"}), 404

        is_student, is_teacher, is_admin = result
        if is_student:
            role = "student"
        elif is_teacher:
            role = "teacher"
        elif is_admin:
            role = "admin"
        else:
            role = "unknown"

        cursor.close()
        conn.close()

        context = orchestrator.get_user_context(user_id, role)
        return jsonify(context)

    except Exception as e:
        logger.error(f"Erreur contexte utilisateur: {e}")
        return jsonify({"error": "Erreur serveur"}), 500


# Exemple de fonction utilitaire pour formater les données de routes
def format_route_data_for_display(data):
    """Formate les données extraites des routes pour un affichage clair"""
    formatted = []

    for source in data.get("data_sources", []):
        section = f"\n### {source['source']}\n\n"

        # Afficher les tableaux
        if "tables" in source["data"]:
            for table in source["data"]["tables"]:
                section += "| " + " | ".join(table["columns"]) + " |\n"
                section += "| " + " | ".join(["---"] * len(table["columns"])) + " |\n"

                for row in table["data"]:
                    values = [str(row.get(col, "")) for col in table["columns"]]
                    section += "| " + " | ".join(values) + " |\n"

                section += "\n"

        # Afficher les statistiques
        if "statistics" in source["data"]:
            section += "\n**Statistiques:**\n"
            for key, value in source["data"]["statistics"].items():
                section += f"- {key}: {value}\n"

        formatted.append(section)

    return "\n".join(formatted)
