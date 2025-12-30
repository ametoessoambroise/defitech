"""
Module d'intégration avec l'API Gemini pour l'assistant IA defAI
Gère la communication, le parsing des réponses et la gestion d'erreurs
"""

import requests
import json
import re
import logging
from typing import Dict, Any, Optional, List
from app.services.system_prompt import PromptBuilder

logger = logging.getLogger(__name__)


class GeminiIntegration:
    """Gestionnaire de l'intégration avec l'API Gemini"""

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash"):
        self.api_key = api_key
        self.model = model
        self.base_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        self.max_retries = 3
        self.timeout = 300  # Augmentation à 300 secondes (5 minutes)

    def _build_prompt(
        self,
        user_prompt: str,
        context: Optional[Dict] = None,
        conversation_history: Optional[List[Dict]] = None,
    ) -> str:
        """
        Construit le prompt complet pour l'API Gemini

        Args:
            user_prompt: Message de l'utilisateur
            context: Contexte utilisateur optionnel
            conversation_history: Historique de conversation optionnel

        Returns:
            Prompt complet formaté
        """
        builder = PromptBuilder()
        return builder.build_complete_prompt(
            user_prompt=user_prompt,
            context=context or {},
            conversation_history=conversation_history or [],
        )

    def _prepare_request(self, prompt: str, temperature: float) -> Dict[str, Any]:
        """Prépare les données de la requête API avec les outils activés"""

        return {
            "contents": [{"parts": [{"text": prompt}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": {
                "temperature": temperature,
                "topK": 40,
                "topP": 0.95,
                "maxOutputTokens": 8192,
                "candidateCount": 1,
                "stopSequences": [],
            },
            "safetySettings": [
                {
                    "category": "HARM_CATEGORY_HARASSMENT",
                    "threshold": "BLOCK_MEDIUM_AND_ABOVE",
                },
                {
                    "category": "HARM_CATEGORY_HATE_SPEECH",
                    "threshold": "BLOCK_MEDIUM_AND_ABOVE",
                },
                {
                    "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                    "threshold": "BLOCK_MEDIUM_AND_ABOVE",
                },
                {
                    "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                    "threshold": "BLOCK_MEDIUM_AND_ABOVE",
                },
            ],
        }

    def _call_api_with_retry(self, request_data: Dict[str, Any]) -> requests.Response:
        """Effectue l'appel API avec mécanisme de retry"""

        last_exception = None

        for attempt in range(self.max_retries):
            try:
                # Ajouter un délai exponentiel entre les tentatives
                if attempt > 0:
                    backoff = min(2**attempt, 10)  # Maximum 10 secondes de délai
                    logger.info(f"Nouvelle tentative dans {backoff} secondes...")
                    import time

                    time.sleep(backoff)

                logger.info(
                    f"Envoi de la requête à {self.base_url} (timeout: {self.timeout}s)"
                )
                response = requests.post(
                    f"{self.base_url}?key={self.api_key}",
                    headers={"Content-Type": "application/json"},
                    json=request_data,
                    timeout=self.timeout,  # Utilisation du timeout configuré
                )

                # Log de la réponse pour debug
                logger.info(
                    f"API Gemini - Tentative {attempt + 1}, Status: {response.status_code}"
                )

                if response.status_code == 200:
                    return response
                elif response.status_code == 429:  # Rate limit
                    wait_time = 2**attempt  # Exponential backoff
                    logger.warning(f"Rate limit atteint, attente de {wait_time}s")
                    import time

                    time.sleep(wait_time)
                    continue
                elif response.status_code >= 500:  # Erreur serveur
                    logger.warning(
                        f"Erreur serveur Gemini {response.status_code}, retry..."
                    )
                    continue
                else:
                    # Erreur client (4xx), ne pas retry
                    error_msg = f"Erreur API Gemini: {response.status_code}"
                    if response.text:
                        try:
                            error_data = response.json()
                            error_msg += f" - {error_data.get('error', {}).get('message', 'Unknown error')}"
                        except Exception:
                            error_msg += f" - {response.text[:200]}"

                    raise requests.RequestException(error_msg)

            except requests.Timeout:
                last_exception = requests.Timeout("Timeout de l'API Gemini")
                logger.warning(f"Timeout, tentative {attempt + 1}/{self.max_retries}")
                continue
            except requests.RequestException as e:
                last_exception = e
                if "429" in str(e) or "5" in str(
                    e
                ):  # Retry sur rate limit et erreurs serveur
                    continue
                else:
                    break  # Ne pas retry sur les erreurs 4xx autres que rate limit

        # Si toutes les tentatives ont échoué
        raise last_exception or requests.RequestException(
            "Échec de toutes les tentatives d'appel API"
        )

    def _process_response(
        self, response: requests.Response, prompt: str = ""
    ) -> Dict[str, Any]:
        """Traite la réponse de l'API Gemini"""

        try:
            result = response.json()

            # Logger la structure de la réponse pour debug
            logger.debug(f"Structure réponse Gemini: {list(result.keys())}")

            # Vérifier la présence de candidates
            if "candidates" not in result or len(result["candidates"]) == 0:
                return {
                    "success": False,
                    "error": "Aucune réponse générée par Gemini",
                    "error_type": "no_candidates",
                    "raw_response": result,
                }

            candidate = result["candidates"][0]
            finish_reason = candidate.get("finishReason", "STOP")

            # Vérifier si le contenu a été bloqué
            if finish_reason in ["SAFETY", "BLOCKED", "RECITATION"]:
                safety_ratings = candidate.get("safetyRatings", [])
                blocked_categories = [
                    rating["category"]
                    for rating in safety_ratings
                    if rating.get("blocked", False)
                ]

                return {
                    "success": False,
                    "error": f"Contenu bloqué pour des raisons de sécurité: {', '.join(blocked_categories)}",
                    "error_type": "content_blocked",
                    "finish_reason": finish_reason,
                    "safety_ratings": safety_ratings,
                    "raw_response": result,
                }

            # Vérifier la structure du contenu
            if "content" not in candidate:
                return {
                    "success": False,
                    "error": f"Structure de réponse invalide: pas de contenu (finishReason: {finish_reason})",
                    "error_type": "invalid_structure",
                    "finish_reason": finish_reason,
                    "raw_response": result,
                }

            content = candidate["content"]

            # Vérifier la présence de parts
            if "parts" not in content or len(content["parts"]) == 0:
                return {
                    "success": False,
                    "error": f"Structure de contenu invalide: pas de parts (finishReason: {finish_reason})",
                    "error_type": "invalid_content_structure",
                    "finish_reason": finish_reason,
                    "content": content,
                    "raw_response": result,
                }

            # Extraire le texte
            text_response = content["parts"][0].get("text", "")

            # Détecter la recherche web (grounding)
            grounding_metadata = candidate.get("groundingMetadata", {})
            has_web_search = bool(
                grounding_metadata.get("searchEntryPoint")
                or grounding_metadata.get("groundingChunks")
            )

            if not text_response:
                return {
                    "success": False,
                    "error": "Réponse vide de Gemini",
                    "error_type": "empty_response",
                    "finish_reason": finish_reason,
                    "raw_response": result,
                }

            # Analyser les demandes de données dans la réponse
            data_requests = self._parse_data_requests(text_response)

            # Détecter la génération d'images
            has_image_generation = "[IMAGE_EDUCATIVE:" in text_response

            # Nettoyer la réponse
            logger.info(f"Réponse brute de Gemini: {text_response[:200]}...")
            cleaned_response = self._clean_response_text(text_response, prompt)
            logger.info(f"Réponse nettoyée: {cleaned_response[:200]}...")

            return {
                "success": True,
                "response": cleaned_response,
                "data_requests": data_requests,
                "has_web_search": has_web_search,
                "has_image_generation": has_image_generation,
                "grounding_metadata": grounding_metadata,
                "finish_reason": finish_reason,
                "usage_metadata": result.get("usageMetadata", {}),
                "model_version": result.get("modelVersion", "unknown"),
            }

        except json.JSONDecodeError as e:
            return {
                "success": False,
                "error": f"Erreur parsing JSON de la réponse: {str(e)}",
                "error_type": "json_decode_error",
                "raw_text": response.text[
                    :500
                ],  # Limiter pour éviter les logs trop longs
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Erreur traitement réponse: {str(e)}",
                "error_type": "processing_error",
                "raw_response": (
                    response.text[:500]
                    if hasattr(response, "text")
                    else str(response)[:500]
                ),
            }

    def _parse_data_requests(self, response_text: str) -> List[Dict[str, str]]:
        """
        Extrait les demandes de données de la réponse de l'IA

        Format attendu: [NEED_DATA: type_de_donnée, description_brève]
        """

        pattern = r"\[NEED_DATA:\s*([^,]+),\s*([^\]]+)\]"
        matches = re.findall(pattern, response_text, re.IGNORECASE)

        requests = []
        for data_type, description in matches:
            requests.append(
                {"type": data_type.strip(), "description": description.strip()}
            )

        if requests:
            logger.info(
                f"Demandes de données détectées: {[req['type'] for req in requests]}"
            )

        return requests

    def _process_security_alerts(self, text: str, user_message: str = ""):
        """Détecte et exécute les alertes de sécurité dans la réponse de l'IA"""
        import re

        # Chercher les patterns d'alertes de sécurité
        alert_pattern = (
            r"\[SECURITY_ALERT:\s*([^,]+),\s*([^,]+),\s*([^,]+),\s*([^\]]+)\]"
        )
        matches = re.findall(alert_pattern, text, flags=re.IGNORECASE)

        if matches:
            for alert_type, description, severity, timestamp in matches:
                try:
                    # Importer et utiliser la fonction d'alerte
                    from system_prompt import SecurityConfig

                    # Nettoyer les valeurs
                    alert_type = alert_type.strip()
                    description = description.strip()
                    severity = severity.strip()
                    timestamp = timestamp.strip()

                    # Envoyer l'alerte email avec le vrai message utilisateur
                    SecurityConfig.send_security_alert(
                        alert_type=alert_type,
                        user_message=user_message
                        or "Message utilisateur non disponible",
                        threat_description=f"{description} (Sévérité: {severity}, Timestamp: {timestamp})",
                    )

                    logger.warning(
                        f" Alerte de sécurité déclenchée: {alert_type} - {description}"
                    )

                except Exception as e:
                    logger.error(
                        f" Erreur lors du traitement de l'alerte de sécurité: {str(e)}"
                    )

    def _clean_response_text(self, text: str, user_message: str = "") -> str:
        """Nettoie le texte de la réponse et traite les alertes de sécurité"""

        logger.info(f"_clean_response_text appelé avec text: {text[:100]}...")

        # Détecter et traiter les alertes de sécurité
        self._process_security_alerts(text, user_message)

        # Supprimer les backticks markdown
        text = re.sub(r"```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"```\s*$", "", text)

        # ❌ NE PAS nettoyer les espaces multiples car ça détruit les sauts de ligne!
        # Cette ligne remplaçait TOUS les \n par des espaces simples
        # text = re.sub(r"\s+", " ", text)

        # Supprimer les demandes de données du texte final (elles seront traitées séparément)
        text = re.sub(r"\[NEED_DATA:[^\]]+\]", "", text, flags=re.IGNORECASE)

        # Supprimer les signalements de sécurité du texte final (ils sont traités séparément)
        text = re.sub(r"\[SECURITY_ALERT:[^\]]+\]", "", text, flags=re.IGNORECASE)

        return text.strip()

    def test_connection(self) -> Dict[str, Any]:
        """Teste la connexion à l'API Gemini"""

        try:
            test_prompt = "Bonjour, peux-tu me répondre simplement 'Test OK' ?"

            response = self.generate_response(
                prompt=test_prompt,
                context=None,
                conversation_history=None,
                temperature=0.1,
            )

            if response["success"]:
                return {
                    "success": True,
                    "message": "Connexion à l'API Gemini réussie",
                    "test_response": response["response"][:100],
                }
            else:
                return {
                    "success": False,
                    "error": response["error"],
                    "error_type": response.get("error_type", "unknown"),
                }

        except Exception as e:
            return {
                "success": False,
                "error": f"Erreur test connexion: {str(e)}",
                "error_type": "connection_test_failed",
            }

    def generate_response(
        self,
        prompt: str,
        context: Optional[Dict] = None,
        conversation_history: Optional[List[Dict]] = None,
        temperature: float = 0.7,
    ) -> Dict[str, Any]:
        """
        Génère une réponse via l'API Gemini avec gestion complète des erreurs

        Args:
            prompt: Le message de l'utilisateur
            context: Données contextuelles (profil, notes, etc.)
            conversation_history: Historique de conversation
            temperature: Température de génération

        Returns:
            Dict contenant la réponse ou les erreurs
        """

        try:
            # Construire le prompt complet
            full_prompt = self._build_prompt(prompt, context, conversation_history)

            # Préparer la requête
            request_data = self._prepare_request(full_prompt, temperature)

            # Ajouter un log pour le débogage
            logger.info(f"Envoi de la requête à Gemini (timeout: {self.timeout}s)")

            # Effectuer l'appel API avec retry
            response = self._call_api_with_retry(request_data)

            # Traiter la réponse
            return self._process_response(response, prompt)

        except Exception as e:
            logger.error(f"Erreur génération réponse Gemini: {e}")
            return {
                "success": False,
                "error": f"Erreur interne: {str(e)}",
                "error_type": "internal_error",
            }

    def build_complete_prompt(
        self,
        user_prompt: str,
        context: Optional[Dict] = None,
        conversation_history: Optional[List[Dict]] = None,
        formatter=None,
    ) -> str:
        """
        Construit un prompt complet avec tous les éléments

        Args:
            user_prompt: Question de l'utilisateur
            context: Contexte utilisateur optionnel
            conversation_history: Historique optionnel
            formatter: Fonction de formatage des dictionnaires

        Returns:
            Prompt complet assemblé
        """
        prompt_parts = []

        # Instructions système
        prompt_parts.append(self.build_system_prompt())

        # Contexte utilisateur
        if context:
            fmt = formatter if formatter else self._format_dict_as_list
            context_section = self.build_context_section(context, fmt)
            if context_section:
                prompt_parts.append(context_section)

        # Historique
        if conversation_history:
            history_section = self.build_history_section(conversation_history)
            if history_section:
                prompt_parts.append(history_section)

        # Question actuelle
        prompt_parts.append(self.build_current_question_section(user_prompt))

        return "\n\n".join(prompt_parts)

    def _format_dict_as_list(self, data: Any) -> str:
        """Formatage auxiliaire pour convertir dict ou list en liste lisible"""
        if not data:
            return "    Aucune donnée disponible"

        lines: List[str] = []

        # Si le contenu est une liste, itérer avec indice
        if isinstance(data, list):
            for idx, item in enumerate(data, 1):
                label = f"Élément {idx}"
                if isinstance(item, dict):
                    lines.append(f"    - {label}:")
                    for sub_key, sub_val in item.items():
                        readable_key = sub_key.replace("_", " ").title()
                        rendered_val = (
                            json.dumps(sub_val, ensure_ascii=False, indent=4)
                            if isinstance(sub_val, (dict, list))
                            else str(sub_val)
                        )
                        lines.append(f"        · {readable_key}: {rendered_val}")
                else:
                    rendered_val = (
                        json.dumps(item, ensure_ascii=False, indent=4)
                        if isinstance(item, (dict, list))
                        else str(item)
                    )
                    lines.append(f"    - {label}: {rendered_val}")
            return "\n".join(lines)

        # Sinon, traiter comme un dictionnaire
        if isinstance(data, dict):
            for key, value in data.items():
                readable_key = key.replace("_", " ").title()
                if isinstance(value, (dict, list)):
                    rendered_val = json.dumps(value, ensure_ascii=False, indent=4)
                else:
                    rendered_val = str(value)
                lines.append(f"    - {readable_key}: {rendered_val}")
            return "\n".join(lines)

        # Fallback pour types simples
        return f"    - {str(data)}"
