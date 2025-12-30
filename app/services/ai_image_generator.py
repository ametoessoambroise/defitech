import os
import uuid
import logging
import requests
import threading
from datetime import datetime
from typing import Dict, Any, Optional
from queue import Queue
import time
import base64

# Configuration du logging
logger = logging.getLogger(__name__)

# Récupération de la clé d'API (doit être configurée dans l'environnement)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")


class GeminiImageGenerator:
    """Générateur d'images utilisant l'API Imagen 3 de Google"""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or GEMINI_API_KEY
        self.model = "imagen-4.0-generate-001"
        self.base_url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:predict"
        self.queue = Queue()
        self.results = {}
        self.running = False
        self.worker_thread = None

    def start_worker(self):
        """Démarre le worker de traitement en arrière-plan"""
        if self.worker_thread is None or not self.worker_thread.is_alive():
            self.running = True
            self.worker_thread = threading.Thread(
                target=self._process_queue, daemon=True
            )
            self.worker_thread.start()
            logger.info("Worker de génération d'images Gemini démarré")

    def stop_worker(self):
        """Arrête le worker"""
        self.running = False
        if self.worker_thread:
            self.worker_thread.join(timeout=1.0)

    def add_task(self, prompt: str, filepath: str) -> str:
        """Ajoute une tâche de génération à la file d'attente"""
        task_id = str(uuid.uuid4())
        self.results[task_id] = {"status": "pending", "progress": 0}
        self.queue.put((task_id, prompt, filepath))

        # S'assurer que le worker tourne
        self.start_worker()

        return task_id

    def get_status(self, task_id: str) -> Dict[str, Any]:
        """Récupère le statut d'une tâche"""
        return self.results.get(task_id, {"status": "not_found"})

    def _process_queue(self):
        """Boucle de traitement des tâches"""
        while self.running:
            try:
                # Attente non bloquante pour pouvoir s'arrêter
                if self.queue.empty():
                    time.sleep(1)
                    continue

                task_id, prompt, filepath = self.queue.get()
                self.results[task_id]["status"] = "processing"
                logger.info(f"Traitement tâche {task_id}: {prompt[:50]}...")

                success = self._generate_with_gemini(prompt, filepath)

                if success:
                    self.results[task_id].update(
                        {
                            "status": "completed",
                            "progress": 100,
                            "url": filepath,
                            "completed_at": datetime.utcnow().isoformat(),
                        }
                    )
                    logger.info(f"Tâche {task_id} terminée avec succès")
                else:
                    self.results[task_id].update(
                        {"status": "failed", "error": "La génération a échoué"}
                    )
                    logger.error(f"Tâche {task_id} a échoué")

                self.queue.task_done()
            except Exception as e:
                logger.error(f"Erreur dans le worker d'images: {e}")
                time.sleep(2)

    def _generate_with_gemini(self, prompt: str, filepath: str) -> bool:
        """Appel effectif à l'API Imagen 3 via Gemini"""
        if not self.api_key:
            logger.error("Clé API Gemini manquante pour la génération d'images")
            return False

        headers = {"Content-Type": "application/json"}

        # Construction du payload pour Imagen 3
        payload = {
            "instances": [{"prompt": prompt}],
            "parameters": {"sampleCount": 1, "aspectRatio": "1:1"},
        }

        try:
            response = requests.post(
                f"{self.base_url}?key={self.api_key}",
                headers=headers,
                json=payload,
                timeout=60,
            )

            if response.status_code == 200:
                result = response.json()
                predictions = result.get("predictions", [])
                if predictions and "bytesBase64Encoded" in predictions[0]:
                    img_data = base64.b64decode(predictions[0]["bytesBase64Encoded"])
                    with open(filepath, "wb") as f:
                        f.write(img_data)
                    return True
                else:
                    logger.error(f"Format de réponse inattendu: {result}")
            else:
                logger.error(
                    f"Erreur API Gemini Image ({response.status_code}): {response.text}"
                )

        except Exception as e:
            logger.error(f"Exception lors de l'appel Gemini Image: {e}")

        return False


# Singleton pour le générateur
_generator = None


def get_generator():
    """Récupère l'instance unique du générateur"""
    global _generator
    if _generator is None:
        _generator = GeminiImageGenerator()
    return _generator


def generate_image_async(
    prompt: str, conversation_id: int, upload_folder: str
) -> Dict[str, Any]:
    """Point d'entrée pour la génération asynchrone"""
    try:
        # Création du dossier si nécessaire
        upload_dir = os.path.join(upload_folder, "ai_attachments", str(conversation_id))
        os.makedirs(upload_dir, exist_ok=True)

        filename = f"gemini_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.png"
        filepath = os.path.abspath(os.path.join(upload_dir, filename))

        generator = get_generator()
        task_id = generator.add_task(prompt, filepath)

        return {
            "type": "generated_image",
            "name": filename,
            "prompt": prompt,
            "status": "generating",
            "task_id": task_id,
            "created_at": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        logger.error(f"Erreur lors de l'ajout de la tâche de génération: {e}")
        return {
            "type": "generated_image",
            "status": "error",
            "error": str(e),
            "task_id": str(uuid.uuid4()),
        }


def check_image_status(task_id: str) -> Dict[str, Any]:
    """Récupère le statut d'une génération en cours"""
    generator = get_generator()
    return generator.get_status(task_id)
