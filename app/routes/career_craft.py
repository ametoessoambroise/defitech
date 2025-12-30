from flask import Blueprint, render_template, jsonify, request, send_file, current_app
from flask_login import login_required, current_user
import traceback


# Import existing CV generator
from app.services.cv_generator import CVGenerator

# Create blueprint
career_craft_bp = Blueprint("career_craft", __name__, template_folder="templates")


@career_craft_bp.route("/career-craft")
@login_required
def career_craft():
    """
    Affiche l'interface CareerCraft.

    Cette fonction est mappée sur l'URL "/career-craft" et est accessible uniquement
    aux utilisateurs connectés. Elle renvoie le template "career_craft.html" qui
    représente l'interface de l'outil CareerCraft.

    Retourne:
        Un template "career_craft.html" qui affiche l'interface CareerCraft.
    """
    return render_template("chat/career_craft.html")

@career_craft_bp.route("/api/career-craft/preview", methods=["POST"])
@login_required
def preview_cv():
    """
    Récupère les données de l'utilisateur pour l'aperçu.

    Cette fonction est mappée sur l'URL "/api/career-craft/preview" et est accessible
    aux utilisateurs connectés. Elle est appelée lorsque l'utilisateur souhaite obtenir un
    aperçu de son CV. Elle récupère les données de l'utilisateur, les formate et les renvoie
    sous forme de réponse JSON. Si une erreur se produit lors de la récupération des données,
    une réponse JSON avec un message d'erreur est renvoyée avec un code d'état 500. Si le
    jeton CSRF est manquant ou incorrect, une réponse JSON avec un message d'erreur est
    renvoyée avec un code d'état 403.

    Retourne:
        Si la requête est valide et les données de l'utilisateur sont correctement récupérées,
        une réponse JSON contenant les informations suivantes :
        - success (bool): Indique si la requête a été effectuée avec succès
        - data (dict): Dictionnaire contenant les données de l'utilisateur mises en forme
            pour l'aperçu
    """
    try:
        # Check CSRF token from headers using Flask-WTF
        from flask_wtf.csrf import validate_csrf
        csrf_token = request.headers.get("X-CSRFToken")
        try:
            validate_csrf(csrf_token)
        except Exception:
            current_app.logger.warning("Invalid or missing CSRF token")
            return jsonify({"success": False, "message": "Invalid CSRF token"}), 403

        # Initialize CV generator with current user
        cv_generator = CVGenerator(current_user.id)

        # Get user data for preview
        user_data = cv_generator.get_user_data()

        return jsonify({"success": True, "data": user_data})
    except Exception as e:
        current_app.logger.error(f"Error in preview_cv: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500


@career_craft_bp.route("/api/career-craft/preview", methods=["GET"])
@login_required
def preview_cv_interface():
    """
    Récupère les données de l'utilisateur pour l'aperçu.

    Cette fonction est mappée sur l'URL "/api/career-craft/preview" et est accessible
    aux utilisateurs connectés. Elle est appelée lorsque l'utilisateur souhaite obtenir un
    aperçu de son CV. Elle récupère les données de l'utilisateur, les formate et les renvoie
    sous forme de réponse JSON.

    Retourne:
        Si la requête est valide et les données de l'utilisateur sont correctement récupérées,
        une réponse JSON contenant les informations suivantes :
        - success (bool): Indique si la requête a été effectuée avec succès
        - data (dict): Dictionnaire contenant les données de l'utilisateur mises en forme
            pour l'aperçu
    """
    try:
        cv_generator = CVGenerator(current_user.id)
        user_data = cv_generator.get_user_data()
        return jsonify({"success": True, "data": user_data})
    except Exception as e:
        current_app.logger.error(
            f"Error in preview_cv: {str(e)}\n{traceback.format_exc()}"
        )
        return jsonify({"success": False, "message": str(e)}), 500


@career_craft_bp.route("/api/career-craft/generate", methods=["POST"])
@login_required
def generate_cv():
    """
    Génère le CV dans le format demandé.

    Cette fonction est mappée sur l'URL "/api/career-craft/generate" et est accessible
    aux utilisateurs connectés. Elle est appelée lorsque l'utilisateur souhaite générer son
    CV dans un format spécifique (par exemple PDF, DOCX, HTML, etc.). Elle récupère les données
    de l'utilisateur, les formate et les génère dans le format demandé. Si une erreur se
    produit lors de la génération du CV, une réponse JSON avec un message d'erreur est renvoyée
    avec un code d'état 500.

    Retourne:
        Si la requête est valide et le CV est correctement généré, une réponse JSON contenant
        les informations suivantes :
        - success (bool): Indique si la requête a été effectuée avec succès
        - preview (str): Contenu HTML de l'aperçu du CV si le format demandé est "preview"
        - fichier (file): Fichier généré du CV si le format demandé est "pdf" ou "docx"
    """
    try:
        # Check CSRF token from headers using Flask-WTF
        from flask_wtf.csrf import validate_csrf
        csrf_token = request.headers.get("X-CSRFToken")
        try:
            validate_csrf(csrf_token)
        except Exception:
            current_app.logger.warning("Invalid or missing CSRF token")
            return jsonify({"success": False, "message": "Invalid CSRF token"}), 403

        data = request.get_json()
        format_type = data.get("format", "pdf")
        template_id = data.get("template", "modern")

        # Initialize CV generator with current user
        cv_generator = CVGenerator(current_user.id)

        # Generate the CV in the requested format
        if format_type == "preview":
            # Generate HTML preview
            html_content = cv_generator.generate_preview(template_id)
            return jsonify({"success": True, "preview": html_content})
        elif format_type == "pdf":
            # Generate PDF
            output_path = cv_generator.generate_pdf(template_id=template_id)
            return send_file(
                output_path,
                as_attachment=True,
                download_name=f"CV_{current_user.nom}_{current_user.prenom}.pdf",
                mimetype="application/pdf",
            )
        elif format_type.lower() == "docx":
            # Generate DOCX
            output_path = cv_generator.generate_docx(template_id=template_id)
            return send_file(
                output_path,
                as_attachment=True,
                download_name=f"CV_{current_user.nom}_{current_user.prenom}.docx",
                mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        elif format_type == "linkedin":
            # Generate LinkedIn data
            linkedin_data = cv_generator.generate_linkedin_data()
            return jsonify(
                {
                    "success": True,
                    "data": linkedin_data,
                    "url": "#",  # This would be the URL to export to LinkedIn
                }
            )
        else:
            return jsonify({"success": False, "message": "Format non supporté"}), 400

    except Exception as e:
        current_app.logger.error(f"Error in generate_cv: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500


# Register error handlers
@career_craft_bp.errorhandler(404)
def not_found_error(error):
    return jsonify({"success": False, "message": "Ressource non trouvée"}), 404


@career_craft_bp.errorhandler(500)
def internal_error(error):
    return jsonify({"success": False, "message": "Erreur interne du serveur"}), 500
