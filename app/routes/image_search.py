from flask import Blueprint, request, jsonify
import os
import requests
from functools import wraps

image_search_bp = Blueprint("image_search", __name__)


def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Vérifier si la clé API est configurée
        unsplash_key = os.getenv("UNSPLASH_ACCESS_KEY")
        if not unsplash_key:
            return (
                jsonify(
                    {
                        "error": "Configuration manquante pour le service de recherche d'images"
                    }
                ),
                500,
            )
        return f(*args, **kwargs, unsplash_key=unsplash_key)

    return decorated_function


@image_search_bp.route("/api/search/images")
@require_api_key
def search_images(unsplash_key):
    """
    Route pour effectuer une recherche d'images via l'API Unsplash
    """
    query = request.args.get("query", "")
    page = request.args.get("page", 1, type=int)
    try:
        per_page = int(request.args.get("per_page", 12))
    except ValueError:
        per_page = 12
    per_page = min(per_page, 30)
    color = request.args.get("color", "")

    if not query:
        return jsonify({"error": "Le paramètre de recherche est requis"}), 400

    try:
        # Construire l'URL de l'API Unsplash
        url = "https://api.unsplash.com/search/photos"
        params = {
            "query": query,
            "page": page,
            "per_page": per_page,
            "client_id": unsplash_key,
        }

        # Ajouter le filtre de couleur si spécifié
        if color:
            params["color"] = color

        # Effectuer la requête vers l'API Unsplash
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()

        # Formater la réponse pour le frontend
        results = []
        for photo in data.get("results", []):
            results.append(
                {
                    "id": photo.get("id"),
                    "urls": {
                        "small": photo.get("urls", {}).get("small"),
                        "regular": photo.get("urls", {}).get("regular"),
                        "full": photo.get("urls", {}).get("full"),
                    },
                    "alt_description": photo.get("alt_description", ""),
                    "description": photo.get("description", ""),
                    "user": {
                        "name": photo.get("user", {}).get("name", "Auteur inconnu"),
                        "username": photo.get("user", {}).get("username", ""),
                        "links": {
                            "html": photo.get("user", {})
                            .get("links", {})
                            .get("html", "#")
                        },
                    },
                    "links": {"html": photo.get("links", {}).get("html", "#")},
                }
            )

        return jsonify(
            {
                "results": results,
                "total": data.get("total", 0),
                "total_pages": data.get("total_pages", 0),
            }
        )

    except requests.exceptions.RequestException as e:
        return (
            jsonify({"error": f"Erreur lors de la recherche d'images: {str(e)}"}),
            500,
        )
