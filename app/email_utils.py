"""
Module d'utilitaires pour l'envoi d'emails via SMTP

Ce module fournit des fonctions pour envoyer différents types d'emails :
- Emails de réinitialisation de mot de passe
- Emails de validation de compte
- Emails de notifications globales
- Emails de confirmation d'inscription

Configuration SMTP dans config.py :
MAIL_SERVER = 'smtp.gmail.com'
MAIL_PORT = 587
MAIL_USE_TLS = True
MAIL_USERNAME = 'votre-email@gmail.com'
MAIL_PASSWORD = 'votre-mot-de-passe-app'
MAIL_DEFAULT_SENDER = 'votre-email@gmail.com'
"""

from flask_mail import Mail, Message
from flask import current_app, render_template_string, url_for
from threading import Thread
import logging

# Configuration du logger
logger = logging.getLogger(__name__)

# Templates d'emails professionnels avec Tailwind CSS et Font Awesome
EMAIL_TEMPLATES = {
    "room_invitation": {
        "subject": "Cours en direct - {{ course.nom }}",
        "template": """
        <!DOCTYPE html>
        <html lang="fr">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Invitation à un cours en direct</title>
            <script src="https://cdn.tailwindcss.com"></script>
            <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
        </head>
        <body class="bg-gray-50 font-sans">
            <div class="max-w-2xl mx-auto my-8 bg-white shadow-lg rounded-lg overflow-hidden">
                <!-- Header -->
                <div class="bg-gradient-to-r from-blue-600 to-indigo-700 px-8 py-6">
                    <div class="flex items-center justify-between">
                        <div>
                            <h1 class="text-2xl font-bold text-white">Cours en direct</h1>
                            <p class="text-blue-100 text-sm">Rejoignez votre session d'apprentissage</p>
                        </div>
                        <i class="fas fa-video text-white text-4xl opacity-80"></i>
                    </div>
                </div>

                <!-- Content -->
                <div class="px-8 py-8">
                    <p class="text-gray-700 mb-6">
                        Bonjour <strong>{{ etudiant.prenom }} {{ etudiant.nom }}</strong>,
                    </p>

                    <p class="text-gray-700 mb-6">
                        Vous êtes invité(e) à rejoindre le cours <strong>{{ course.nom }}</strong> 
                        dispensé par <strong>{{ enseignant.prenom }} {{ enseignant.nom }}</strong>.
                    </p>

                    <div class="bg-blue-50 border-l-4 border-blue-500 p-4 rounded-r mb-6">
                        <div class="flex">
                            <div class="flex-shrink-0">
                                <i class="fas fa-info-circle text-blue-500"></i>
                            </div>
                            <div class="ml-3">
                                <p class="text-sm text-blue-700">
                                    Le cours est sur le point de commencer. Cliquez sur le bouton ci-dessous pour rejoindre la salle de classe virtuelle.
                                </p>
                            </div>
                        </div>
                    </div>

                    <!-- Bouton CTA -->
                    <div class="text-center my-8">
                        <a href="{{ join_url }}" 
                           class="inline-flex items-center px-6 py-3 border border-transparent text-base font-medium rounded-md shadow-sm text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500">
                            <i class="fas fa-video mr-2"></i>
                            Rejoindre le cours
                        </a>
                    </div>

                    <div class="mt-8 pt-6 border-t border-gray-200">
                        <p class="text-sm text-gray-500">
                            <i class="far fa-clock mr-2"></i> Ce lien est valable uniquement pendant la durée du cours.
                        </p>
                        <p class="text-sm text-gray-500 mt-2">
                            <i class="fas fa-info-circle mr-2"></i> Assurez-vous d'avoir un micro et une caméra fonctionnels.
                        </p>
                    </div>
                </div>

                <!-- Footer -->
                <div class="bg-gray-50 px-8 py-6 border-t border-gray-200">
                    <div class="text-center text-gray-500 text-sm">
                        <p>Cet email a été envoyé automatiquement par la plateforme DEFITECH.</p>
                        <p class="mt-2">© 2025 DEFITECH. Tous droits réservés.</p>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """,
    },
    "password_reset": {
        "subject": "Réinitialisation de votre mot de passe - DEFITECH",
        "template": """
        <!DOCTYPE html>
        <html lang="fr">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Réinitialisation de mot de passe</title>
            <script src="https://cdn.tailwindcss.com"></script>
            <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
        </head>
        <body class="bg-gray-50 font-sans">
            <div class="max-w-2xl mx-auto my-8 bg-white shadow-lg rounded-lg overflow-hidden">
                <!-- Header -->
                <div class="bg-gradient-to-r from-blue-600 to-blue-700 px-8 py-6">
                    <div class="flex items-center justify-between">
                        <div>
                            <h1 class="text-3xl font-bold text-white mb-1">DEFITECH</h1>
                            <p class="text-blue-100 text-sm">Plateforme Éducative Collaborative</p>
                        </div>
                        <i class="fas fa-shield-alt text-white text-4xl opacity-80"></i>
                    </div>
                </div>

                <!-- Content -->
                <div class="px-8 py-8">
                    <!-- Icon -->
                    <div class="flex justify-center mb-6">
                        <div class="bg-blue-100 rounded-full p-4">
                            <i class="fas fa-key text-blue-600 text-3xl"></i>
                        </div>
                    </div>

                    <h2 class="text-2xl font-semibold text-gray-800 mb-4 text-center">
                        Réinitialisation de votre mot de passe
                    </h2>

                    <p class="text-gray-700 mb-4">
                        Bonjour <strong>{{ user.prenom }} {{ user.nom }}</strong>,
                    </p>

                    <p class="text-gray-600 mb-6 leading-relaxed">
                        Nous avons reçu une demande de réinitialisation de mot de passe pour votre compte DEFITECH. 
                        Si vous êtes à l'origine de cette demande, veuillez cliquer sur le bouton ci-dessous pour créer un nouveau mot de passe.
                    </p>

                    <!-- CTA Button -->
                    <div class="text-center my-8">
                        <a href="{{ reset_url }}" 
                           class="inline-block bg-blue-600 hover:bg-blue-700 text-white font-semibold px-8 py-4 rounded-lg shadow-lg transition duration-300 transform hover:scale-105 no-underline">
                            <i class="fas fa-lock-open mr-2"></i>
                            Réinitialiser mon mot de passe
                        </a>
                    </div>

                    <!-- Warning Box -->
                    <div class="bg-amber-50 border-l-4 border-amber-500 p-4 mb-6 rounded-r">
                        <div class="flex items-start">
                            <i class="fas fa-exclamation-triangle text-amber-600 mt-1 mr-3"></i>
                            <div>
                                <p class="text-amber-800 font-semibold mb-1">Important</p>
                                <p class="text-amber-700 text-sm">
                                    Ce lien de réinitialisation est valide pendant <strong>1 heure</strong> uniquement. 
                                    Pour des raisons de sécurité, il ne pourra être utilisé qu'une seule fois.
                                </p>
                            </div>
                        </div>
                    </div>

                    <!-- Security Notice -->
                    <div class="bg-gray-50 border border-gray-200 p-4 rounded-lg mb-6">
                        <div class="flex items-start">
                            <i class="fas fa-info-circle text-gray-500 mt-1 mr-3"></i>
                            <div class="text-sm text-gray-600">
                                <p class="font-semibold mb-1">Vous n'avez pas demandé cette réinitialisation ?</p>
                                <p>Si vous n'êtes pas à l'origine de cette demande, veuillez ignorer cet email. 
                                   Votre mot de passe actuel reste inchangé et sécurisé. Nous vous recommandons toutefois 
                                   de vérifier l'activité de votre compte.</p>
                            </div>
                        </div>
                    </div>

                    <!-- Link fallback -->
                    <div class="bg-gray-100 p-4 rounded-lg text-sm">
                        <p class="text-gray-600 mb-2 font-semibold">
                            <i class="fas fa-link mr-2"></i>Le bouton ne fonctionne pas ?
                        </p>
                        <p class="text-gray-500 mb-2">Copiez et collez ce lien dans votre navigateur :</p>
                        <p class="text-blue-600 break-all">
                            <a href="{{ reset_url }}" class="hover:underline">{{ reset_url }}</a>
                        </p>
                    </div>
                </div>

                <!-- Footer -->
                <div class="bg-gray-50 px-8 py-6 border-t border-gray-200">
                    <div class="text-center text-gray-500 text-sm mb-4">
                        <i class="fas fa-envelope mr-2"></i>
                        Cet email a été envoyé automatiquement. Merci de ne pas y répondre.
                    </div>
                    <div class="text-center text-gray-400 text-xs">
                        <p class="mb-2">© 2025 DEFITECH - Tous droits réservés</p>
                        <p class="flex items-center justify-center gap-4">
                            <a href="#" class="hover:text-blue-600 transition"><i class="fab fa-facebook"></i></a>
                            <a href="#" class="hover:text-blue-600 transition"><i class="fab fa-twitter"></i></a>
                            <a href="#" class="hover:text-blue-600 transition"><i class="fab fa-linkedin"></i></a>
                        </p>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """,
    },
    "account_validated": {
        "subject": "Bienvenue sur DEFITECH - Votre compte est activé",
        "template": """
        <!DOCTYPE html>
        <html lang="fr">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Compte validé avec succès</title>
            <script src="https://cdn.tailwindcss.com"></script>
            <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
        </head>
        <body class="bg-gray-50 font-sans">
            <div class="max-w-2xl mx-auto my-8 bg-white shadow-lg rounded-lg overflow-hidden">
                <!-- Header -->
                <div class="bg-gradient-to-r from-green-600 to-emerald-700 px-8 py-6">
                    <div class="flex items-center justify-between">
                        <div>
                            <h1 class="text-3xl font-bold text-white mb-1">DEFITECH</h1>
                            <p class="text-green-100 text-sm">Plateforme Éducative Collaborative</p>
                        </div>
                        <i class="fas fa-check-circle text-white text-4xl opacity-80"></i>
                    </div>
                </div>

                <!-- Success Banner -->
                <div class="bg-gradient-to-r from-green-50 to-emerald-50 px-8 py-6 border-b border-green-200">
                    <div class="flex items-center justify-center">
                        <div class="bg-white rounded-full p-3 shadow-lg mr-4">
                            <i class="fas fa-trophy text-green-600 text-3xl"></i>
                        </div>
                        <div>
                            <h2 class="text-2xl font-bold text-green-800 mb-1">
                                Félicitations ! 🎉
                            </h2>
                            <p class="text-green-700">Votre compte a été validé avec succès</p>
                        </div>
                    </div>
                </div>

                <!-- Content -->
                <div class="px-8 py-8">
                    <p class="text-gray-700 mb-4 text-lg">
                        Bonjour <strong class="text-green-700">{{ user.prenom }} {{ user.nom }}</strong>,
                    </p>

                    <p class="text-gray-600 mb-6 leading-relaxed">
                        Nous sommes ravis de vous informer que votre compte DEFITECH a été validé par notre équipe. 
                        Vous avez maintenant accès à l'ensemble des fonctionnalités de notre plateforme éducative.
                    </p>

                    <!-- CTA Button -->
                    <div class="text-center my-8">
                        <a href="{{ login_url }}" 
                           class="inline-block bg-blue-600 hover:bg-blue-700 text-white font-semibold px-8 py-4 rounded-lg shadow-lg transition duration-300 transform hover:scale-105 no-underline">
                            <i class="fas fa-sign-in-alt mr-2"></i>
                            Accéder à ma plateforme
                        </a>
                    </div>

                    <!-- Features Grid -->
                    <div class="bg-gradient-to-br from-gray-50 to-blue-50 p-6 rounded-lg mb-6 border border-blue-100">
                        <h3 class="text-xl font-semibold text-gray-800 mb-4 flex items-center">
                            <i class="fas fa-rocket text-blue-600 mr-3"></i>
                            Commencez votre aventure
                        </h3>
                        
                        <div class="grid md:grid-cols-2 gap-4">
                            <div class="bg-white p-4 rounded-lg shadow-sm border border-gray-100">
                                <div class="flex items-start">
                                    <div class="bg-blue-100 rounded-full p-2 mr-3">
                                        <i class="fas fa-user-circle text-blue-600"></i>
                                    </div>
                                    <div>
                                        <h4 class="font-semibold text-gray-800 mb-1">Personnalisez votre profil</h4>
                                        <p class="text-gray-600 text-sm">Complétez vos informations et ajoutez une photo</p>
                                    </div>
                                </div>
                            </div>

                            <div class="bg-white p-4 rounded-lg shadow-sm border border-gray-100">
                                <div class="flex items-start">
                                    <div class="bg-purple-100 rounded-full p-2 mr-3">
                                        <i class="fas fa-book-open text-purple-600"></i>
                                    </div>
                                    <div>
                                        <h4 class="font-semibold text-gray-800 mb-1">Explorez les ressources</h4>
                                        <p class="text-gray-600 text-sm">Accédez aux cours et supports pédagogiques</p>
                                    </div>
                                </div>
                            </div>

                            <div class="bg-white p-4 rounded-lg shadow-sm border border-gray-100">
                                <div class="flex items-start">
                                    <div class="bg-amber-100 rounded-full p-2 mr-3">
                                        <i class="fas fa-users text-amber-600"></i>
                                    </div>
                                    <div>
                                        <h4 class="font-semibold text-gray-800 mb-1">Rejoignez votre communauté</h4>
                                        <p class="text-gray-600 text-sm">Connectez-vous avec votre filière</p>
                                    </div>
                                </div>
                            </div>

                            <div class="bg-white p-4 rounded-lg shadow-sm border border-gray-100">
                                <div class="flex items-start">
                                    <div class="bg-green-100 rounded-full p-2 mr-3">
                                        <i class="fas fa-trophy text-green-600"></i>
                                    </div>
                                    <div>
                                        <h4 class="font-semibold text-gray-800 mb-1">Participez aux défis</h4>
                                        <p class="text-gray-600 text-sm">Relevez des challenges et progressez</p>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Support Box -->
                    <div class="bg-blue-50 border-l-4 border-blue-500 p-4 rounded-r">
                        <div class="flex items-start">
                            <i class="fas fa-life-ring text-blue-600 mt-1 mr-3 text-xl"></i>
                            <div>
                                <p class="text-blue-800 font-semibold mb-1">Besoin d'aide ?</p>
                                <p class="text-blue-700 text-sm">
                                    Notre équipe de support est à votre disposition pour répondre à toutes vos questions. 
                                    N'hésitez pas à nous contacter !
                                </p>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Footer -->
                <div class="bg-gray-50 px-8 py-6 border-t border-gray-200">
                    <div class="text-center text-gray-500 text-sm mb-4">
                        <p class="mb-2">
                            <i class="fas fa-heart text-red-500 mr-1"></i>
                            Merci de rejoindre la communauté DEFITECH
                        </p>
                    </div>
                    <div class="text-center text-gray-400 text-xs">
                        <p class="mb-2">© 2025 DEFITECH - Tous droits réservés</p>
                        <p class="flex items-center justify-center gap-4">
                            <a href="#" class="hover:text-green-600 transition"><i class="fab fa-facebook"></i></a>
                            <a href="#" class="hover:text-green-600 transition"><i class="fab fa-twitter"></i></a>
                            <a href="#" class="hover:text-green-600 transition"><i class="fab fa-linkedin"></i></a>
                        </p>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """,
    },
    "global_notification": {
        "subject": "{{ notification.titre }} - DEFITECH",
        "template": """
        <!DOCTYPE html>
        <html lang="fr">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Notification DEFITECH</title>
            <script src="https://cdn.tailwindcss.com"></script>
            <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
        </head>
        <body class="bg-gray-50 font-sans">
            <div class="max-w-2xl mx-auto my-8 bg-white shadow-lg rounded-lg overflow-hidden">
                <!-- Header -->
                <div class="px-8 py-6" style="background: {{ priority_color }};">
                    <div class="flex items-center justify-between">
                        <div>
                            <h1 class="text-3xl font-bold text-white mb-1">DEFITECH</h1>
                            <p class="text-white text-opacity-90 text-sm">Notification importante</p>
                        </div>
                        {% if notification.priorite >= 3 %}
                        <i class="fas fa-exclamation-circle text-white text-4xl opacity-80 animate-pulse"></i>
                        {% else %}
                        <i class="fas fa-bell text-white text-4xl opacity-80"></i>
                        {% endif %}
                    </div>
                </div>

                <!-- Content -->
                <div class="px-8 py-8">
                    <!-- Metadata Bar -->
                    <div class="flex flex-wrap items-center justify-between mb-6 pb-4 border-b border-gray-200">
                        <div class="flex items-center gap-2 mb-2">
                            {% if notification.type == 'info' %}
                            <span class="bg-blue-100 text-blue-800 text-xs font-bold px-3 py-1 rounded-full flex items-center">
                                <i class="fas fa-info-circle mr-1"></i> INFORMATION
                            </span>
                            {% elif notification.type == 'warning' %}
                            <span class="bg-amber-100 text-amber-800 text-xs font-bold px-3 py-1 rounded-full flex items-center">
                                <i class="fas fa-exclamation-triangle mr-1"></i> AVERTISSEMENT
                            </span>
                            {% elif notification.type == 'error' %}
                            <span class="bg-red-100 text-red-800 text-xs font-bold px-3 py-1 rounded-full flex items-center">
                                <i class="fas fa-times-circle mr-1"></i> URGENT
                            </span>
                            {% elif notification.type == 'success' %}
                            <span class="bg-green-100 text-green-800 text-xs font-bold px-3 py-1 rounded-full flex items-center">
                                <i class="fas fa-check-circle mr-1"></i> SUCCÈS
                            </span>
                            {% endif %}

                            {% if notification.priorite >= 3 %}
                            <span class="bg-red-100 text-red-800 text-xs font-bold px-3 py-1 rounded-full flex items-center">
                                <i class="fas fa-fire mr-1"></i> PRIORITÉ {{ 'CRITIQUE' if notification.priorite == 4 else 'ÉLEVÉE' }}
                            </span>
                            {% endif %}
                        </div>
                        
                        <div class="text-gray-500 text-sm flex items-center">
                            <i class="far fa-clock mr-2"></i>
                            {{ notification.date_creation.strftime('%d/%m/%Y à %H:%M') }}
                        </div>
                    </div>

                    <!-- Title -->
                    <h2 class="text-2xl font-bold text-gray-800 mb-6">
                        {{ notification.titre }}
                    </h2>

                    <!-- Message Content -->
                    <div class="bg-gray-50 p-6 rounded-lg mb-6 border border-gray-200">
                        <div class="text-gray-700 leading-relaxed prose max-w-none">
                            {{ notification.message|safe }}
                        </div>
                    </div>

                    <!-- Expiration Warning -->
                    {% if notification.date_expiration %}
                    <div class="bg-gradient-to-r from-amber-50 to-orange-50 border-l-4 border-amber-500 p-4 mb-6 rounded-r shadow-sm">
                        <div class="flex items-start">
                            <div class="bg-white rounded-full p-2 mr-3">
                                <i class="fas fa-hourglass-half text-amber-600"></i>
                            </div>
                            <div>
                                <p class="text-amber-800 font-semibold mb-1">
                                    <i class="fas fa-clock mr-1"></i>Notification à durée limitée
                                </p>
                                <p class="text-amber-700 text-sm">
                                    Cette notification expirera le <strong>{{ notification.date_expiration.strftime('%d/%m/%Y à %H:%M') }}</strong>
                                </p>
                            </div>
                        </div>
                    </div>
                    {% endif %}

                    <!-- CTA Button -->
                    <div class="text-center my-8">
                        <a href="{{ platform_url }}" 
                           class="inline-block text-white font-semibold px-8 py-4 rounded-lg shadow-lg transition duration-300 transform hover:scale-105 no-underline"
                           style="background: {{ priority_color }};">
                            <i class="fas fa-external-link-alt mr-2"></i>
                            Accéder à la plateforme
                        </a>
                    </div>

                    <!-- Additional Info -->
                    <div class="bg-blue-50 border border-blue-200 p-4 rounded-lg text-sm">
                        <div class="flex items-start">
                            <i class="fas fa-lightbulb text-blue-600 mt-1 mr-3"></i>
                            <div class="text-blue-800">
                                <p class="font-semibold mb-1">Conseil</p>
                                <p class="text-blue-700">
                                    Connectez-vous régulièrement à votre espace DEFITECH pour ne manquer aucune information importante.
                                </p>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Footer -->
                <div class="bg-gray-50 px-8 py-6 border-t border-gray-200">
                    <div class="text-center text-gray-500 text-sm mb-4">
                        <i class="fas fa-shield-alt mr-2"></i>
                        Cette notification a été envoyée automatiquement par DEFITECH.
                    </div>
                    <div class="text-center text-gray-400 text-xs">
                        <p class="mb-2">© 2025 DEFITECH - Tous droits réservés</p>
                        <p class="flex items-center justify-center gap-4">
                            <a href="#" class="hover:text-blue-600 transition"><i class="fab fa-facebook"></i></a>
                            <a href="#" class="hover:text-blue-600 transition"><i class="fab fa-twitter"></i></a>
                            <a href="#" class="hover:text-blue-600 transition"><i class="fab fa-linkedin"></i></a>
                        </p>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """,
    },
    "teacher_profile_request": {
        "subject": "Nouvelle demande de modification de profil enseignant - DEFITECH",
        "template": """
        <!DOCTYPE html>
        <html lang="fr">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Nouvelle demande de modification</title>
            <script src="https://cdn.tailwindcss.com"></script>
            <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
        </head>
        <body class="bg-gray-50 font-sans">
            <div class="max-w-2xl mx-auto my-8 bg-white shadow-lg rounded-lg overflow-hidden">
                <!-- Header -->
                <div class="bg-gradient-to-r from-yellow-600 to-orange-700 px-8 py-6">
                    <div class="flex items-center justify-between">
                        <div>
                            <h1 class="text-3xl font-bold text-white mb-1">DEFITECH</h1>
                            <p class="text-yellow-100 text-sm">Administration</p>
                        </div>
                        <i class="fas fa-user-edit text-white text-4xl opacity-80"></i>
                    </div>
                </div>

                <!-- Content -->
                <div class="px-8 py-8">
                    <!-- Icon -->
                    <div class="flex justify-center mb-6">
                        <div class="bg-yellow-100 rounded-full p-4">
                            <i class="fas fa-user-edit text-yellow-600 text-3xl"></i>
                        </div>
                    </div>

                    <h2 class="text-2xl font-semibold text-gray-800 mb-4 text-center">
                        Nouvelle demande de modification de profil
                    </h2>

                    <p class="text-gray-700 mb-4">
                        Bonjour <strong>{{ admin.prenom }} {{ admin.nom }}</strong>,
                    </p>

                    <p class="text-gray-600 mb-6 leading-relaxed">
                        Un enseignant a soumis une demande de modification de son profil qui nécessite votre approbation.
                    </p>

                    <!-- Teacher Info -->
                    <div class="bg-gray-50 border border-gray-200 p-6 rounded-lg mb-6">
                        <h3 class="text-lg font-semibold text-gray-800 mb-4 flex items-center">
                            <i class="fas fa-user-graduate text-blue-600 mr-2"></i>
                            Informations de l'enseignant
                        </h3>

                        <div class="grid md:grid-cols-2 gap-4">
                            <div>
                                <p class="text-sm font-medium text-gray-500">Nom complet</p>
                                <p class="text-gray-900 font-medium">{{ teacher.prenom }} {{ teacher.nom }}</p>
                            </div>
                            <div>
                                <p class="text-sm font-medium text-gray-500">Email</p>
                                <p class="text-gray-900">{{ teacher.email }}</p>
                            </div>
                            <div>
                                <p class="text-sm font-medium text-gray-500">Rôle</p>
                                <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800">
                                    <i class="fas fa-chalkboard-teacher mr-1"></i>
                                    Enseignant
                                </span>
                            </div>
                            <div>
                                <p class="text-sm font-medium text-gray-500">Date de demande</p>
                                <p class="text-gray-900">{{ request.date_creation.strftime('%d/%m/%Y à %H:%M') }}</p>
                            </div>
                        </div>
                    </div>

                    <!-- CTA Button -->
                    <div class="text-center my-8">
                        <a href="{{ url_for('admin_review_teacher_request', request_id=request.id, _external=True) }}"
                           class="inline-block bg-yellow-600 hover:bg-yellow-700 text-white font-semibold px-8 py-4 rounded-lg shadow-lg transition duration-300 transform hover:scale-105 no-underline">
                            <i class="fas fa-eye mr-2"></i>
                            Examiner la demande
                        </a>
                    </div>

                    <!-- Request Details -->
                    <div class="bg-blue-50 border-l-4 border-blue-500 p-4 rounded-r mb-6">
                        <div class="flex items-start">
                            <i class="fas fa-info-circle text-blue-600 mt-1 mr-3"></i>
                            <div>
                                <p class="text-blue-800 font-semibold mb-1">Détails de la demande</p>
                                <p class="text-blue-700 text-sm">
                                    {% if request.nom or request.prenom %}
                                    • Modification du nom/prénom<br>
                                    {% endif %}
                                    {% if request.email %}
                                    • Modification de l'adresse email<br>
                                    {% endif %}
                                    {% if request.telephone or request.adresse %}
                                    • Modification des coordonnées<br>
                                    {% endif %}
                                    {% if request.specialite or request.grade %}
                                    • Modification des informations professionnelles<br>
                                    {% endif %}
                                    {% if request.filieres_enseignees or request.annees_enseignees %}
                                    • Modification des filières/années enseignées<br>
                                    {% endif %}
                                    {% if request.photo_profil %}
                                    • Modification de la photo de profil<br>
                                    {% endif %}
                                </p>
                            </div>
                        </div>
                    </div>

                    <!-- Admin Actions -->
                    <div class="bg-gradient-to-br from-gray-50 to-blue-50 p-6 rounded-lg mb-6 border border-blue-100">
                        <h3 class="text-lg font-semibold text-gray-800 mb-4 flex items-center">
                            <i class="fas fa-cogs text-blue-600 mr-3"></i>
                            Actions disponibles
                        </h3>

                        <div class="grid md:grid-cols-2 gap-4">
                            <div class="bg-white p-4 rounded-lg shadow-sm border border-gray-100">
                                <div class="flex items-start">
                                    <div class="bg-green-100 rounded-full p-2 mr-3">
                                        <i class="fas fa-check text-green-600"></i>
                                    </div>
                                    <div>
                                        <h4 class="font-semibold text-gray-800 mb-1">Approuver</h4>
                                        <p class="text-gray-600 text-sm">Appliquer les modifications demandées</p>
                                    </div>
                                </div>
                            </div>

                            <div class="bg-white p-4 rounded-lg shadow-sm border border-gray-100">
                                <div class="flex items-start">
                                    <div class="bg-red-100 rounded-full p-2 mr-3">
                                        <i class="fas fa-times text-red-600"></i>
                                    </div>
                                    <div>
                                        <h4 class="font-semibold text-gray-800 mb-1">Rejeter</h4>
                                        <p class="text-gray-600 text-sm">Refuser la demande avec un commentaire</p>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Link fallback -->
                    <div class="bg-gray-100 p-4 rounded-lg text-sm">
                        <p class="text-gray-600 mb-2 font-semibold">
                            <i class="fas fa-link mr-2"></i>Le bouton ne fonctionne pas ?
                        </p>
                        <p class="text-gray-500 mb-2">Copiez et collez ce lien dans votre navigateur :</p>
                        <p class="text-blue-600 break-all">
                            <a href="{{ url_for('admin_review_teacher_request', request_id=request.id, _external=True) }}" class="hover:underline">{{ url_for('admin_review_teacher_request', request_id=request.id, _external=True) }}</a>
                        </p>
                    </div>
                </div>

                <!-- Footer -->
                <div class="bg-gray-50 px-8 py-6 border-t border-gray-200">
                    <div class="text-center text-gray-500 text-sm mb-4">
                        <i class="fas fa-shield-alt mr-2"></i>
                        Email envoyé automatiquement par le système DEFITECH.
                    </div>
                    <div class="text-center text-gray-400 text-xs">
                        <p class="mb-2">© 2025 DEFITECH - Tous droits réservés</p>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """,
    },
    "suggestion_notification": {
        "subject": "Nouvelle suggestion - DEFITECH",
        "template": """
        <!DOCTYPE html>
        <html lang="fr">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Nouvelle suggestion</title>
            <script src="https://cdn.tailwindcss.com"></script>
            <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
        </head>
        <body class="bg-gray-50 font-sans">
            <div class="max-w-2xl mx-auto my-8 bg-white shadow-lg rounded-lg overflow-hidden">
                <!-- Header -->
                <div class="bg-gradient-to-r from-yellow-600 to-orange-700 px-8 py-6">
                    <div class="flex items-center justify-between">
                        <div>
                            <h1 class="text-3xl font-bold text-white mb-1">DEFITECH</h1>
                            <p class="text-yellow-100 text-sm">Boîte à suggestions</p>
                        </div>
                        <i class="fas fa-lightbulb text-white text-4xl opacity-80"></i>
                    </div>
                </div>

                <!-- Content -->
                <div class="px-8 py-8">
                    <!-- Icon -->
                    <div class="flex justify-center mb-6">
                        <div class="bg-yellow-100 rounded-full p-4">
                            <i class="fas fa-lightbulb text-yellow-600 text-3xl"></i>
                        </div>
                    </div>

                    <h2 class="text-2xl font-semibold text-gray-800 mb-4 text-center">
                        Nouvelle suggestion reçue
                    </h2>

                    <p class="text-gray-700 mb-4">
                        Bonjour <strong>{{ admin.prenom }} {{ admin.nom }}</strong>,
                    </p>

                    <p class="text-gray-600 mb-6 leading-relaxed">
                        Un membre de la communauté DEFITECH a soumis une nouvelle suggestion qui nécessite votre attention.
                    </p>

                    <!-- Suggestion Info -->
                    <div class="bg-gray-50 border border-gray-200 p-6 rounded-lg mb-6">
                        <h3 class="text-lg font-semibold text-gray-800 mb-4 flex items-center">
                            <i class="fas fa-comment-dots text-blue-600 mr-2"></i>
                            Détails de la suggestion
                        </h3>

                        <div class="space-y-3">
                            <div class="flex justify-between items-start">
                                <span class="text-sm font-medium text-gray-500 w-32">Contenu :</span>
                                <p class="text-gray-900 flex-1 text-right">{{ suggestion.contenu }}</p>
                            </div>

                            {% if suggestion.auteur_anonyme %}
                            <div class="flex justify-between items-center">
                                <span class="text-sm font-medium text-gray-500 w-32">Auteur :</span>
                                <span class="text-gray-900">{{ suggestion.auteur_anonyme }}</span>
                            </div>
                            {% else %}
                            <div class="flex justify-between items-center">
                                <span class="text-sm font-medium text-gray-500 w-32">Auteur :</span>
                                <span class="text-gray-900">Anonyme</span>
                            </div>
                            {% endif %}

                            {% if suggestion.email_contact %}
                            <div class="flex justify-between items-center">
                                <span class="text-sm font-medium text-gray-500 w-32">Contact :</span>
                                <span class="text-gray-900">{{ suggestion.email_contact }}</span>
                            </div>
                            {% endif %}

                            <div class="flex justify-between items-center">
                                <span class="text-sm font-medium text-gray-500 w-32">Date :</span>
                                <span class="text-gray-900">{{ suggestion.date_creation.strftime('%d/%m/%Y à %H:%M') }}</span>
                            </div>
                        </div>
                    </div>

                    <!-- CTA Button -->
                    <div class="text-center my-8">
                        <a href="{{ url_for('admin_suggestions', _external=True) }}"
                           class="inline-block bg-yellow-600 hover:bg-yellow-700 text-white font-semibold px-8 py-4 rounded-lg shadow-lg transition duration-300 transform hover:scale-105 no-underline">
                            <i class="fas fa-cogs mr-2"></i>
                            Gérer les suggestions
                        </a>
                    </div>

                    <!-- Actions disponibles -->
                    <div class="bg-gradient-to-br from-gray-50 to-blue-50 p-6 rounded-lg mb-6 border border-blue-100">
                        <h3 class="text-lg font-semibold text-gray-800 mb-4 flex items-center">
                            <i class="fas fa-tools text-blue-600 mr-3"></i>
                            Actions disponibles
                        </h3>

                        <div class="grid md:grid-cols-2 gap-4">
                            <div class="bg-white p-4 rounded-lg shadow-sm border border-gray-100">
                                <div class="flex items-start">
                                    <div class="bg-blue-100 rounded-full p-2 mr-3">
                                        <i class="fas fa-reply text-blue-600"></i>
                                    </div>
                                    <div>
                                        <h4 class="font-semibold text-gray-800 mb-1">Répondre</h4>
                                        <p class="text-gray-600 text-sm">Fournir une réponse publique à la suggestion</p>
                                    </div>
                                </div>
                            </div>

                            <div class="bg-white p-4 rounded-lg shadow-sm border border-gray-100">
                                <div class="flex items-start">
                                    <div class="bg-green-100 rounded-full p-2 mr-3">
                                        <i class="fas fa-check-circle text-green-600"></i>
                                    </div>
                                    <div>
                                        <h4 class="font-semibold text-gray-800 mb-1">Statut</h4>
                                        <p class="text-gray-600 text-sm">Changer le statut (ouverte/en cours/fermée)</p>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Link fallback -->
                    <div class="bg-gray-100 p-4 rounded-lg text-sm">
                        <p class="text-gray-600 mb-2 font-semibold">
                            <i class="fas fa-link mr-2"></i>Le bouton ne fonctionne pas ?
                        </p>
                        <p class="text-gray-500 mb-2">Copiez et collez ce lien dans votre navigateur :</p>
                        <p class="text-blue-600 break-all">
                            <a href="{{ url_for('admin_suggestions', _external=True) }}" class="hover:underline">{{ url_for('admin_suggestions', _external=True) }}</a>
                        </p>
                    </div>
                </div>

                <!-- Footer -->
                <div class="bg-gray-50 px-8 py-6 border-t border-gray-200">
                    <div class="text-center text-gray-500 text-sm mb-4">
                        <i class="fas fa-shield-alt mr-2"></i>
                        Email envoyé automatiquement par le système DEFITECH.
                    </div>
                    <div class="text-center text-gray-400 text-xs">
                        <p class="mb-2">© 2025 DEFITECH - Tous droits réservés</p>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """,
    },
    "security_alert": {
        "subject": "🚨 ALERTE DE SÉCURITÉ CRITIQUE - DEFITECH",
        "template": """
        <!DOCTYPE html>
        <html lang="fr">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Alerte de Sécurité Critique</title>
            <script src="https://cdn.tailwindcss.com"></script>
            <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
        </head>
        <body class="bg-gray-50 font-sans">
            <div class="max-w-2xl mx-auto my-8 bg-white shadow-lg rounded-lg overflow-hidden">
                <!-- Header Critique -->
                <div class="bg-gradient-to-r from-red-600 to-red-800 px-8 py-6 animate-pulse">
                    <div class="flex items-center justify-between">
                        <div>
                            <h1 class="text-3xl font-bold text-white mb-1">🚨 ALERTE DE SÉCURITÉ</h1>
                            <p class="text-red-100 text-sm font-semibold">DÉTECTION DE MENACE CRITIQUE</p>
                        </div>
                        <i class="fas fa-shield-alt text-white text-4xl opacity-80"></i>
                    </div>
                </div>

                <!-- Alert Banner -->
                <div class="bg-gradient-to-r from-red-50 to-red-100 px-8 py-6 border-b-4 border-red-500">
                    <div class="flex items-center justify-center">
                        <div class="bg-white rounded-full p-3 shadow-lg mr-4">
                            <i class="fas fa-exclamation-triangle text-red-600 text-3xl animate-pulse"></i>
                        </div>
                        <div>
                            <h2 class="text-2xl font-bold text-red-800 mb-1">
                                MENACE DÉTECTÉE - ACTION IMMÉDIATE REQUISE
                            </h2>
                            <p class="text-red-700 font-semibold">{{ alert_type|upper }}</p>
                        </div>
                    </div>
                </div>

                <!-- Content -->
                <div class="px-8 py-8">
                    <p class="text-gray-700 mb-6 text-lg font-semibold">
                        Administrateur <strong>{{ admin_name }}</strong>,
                    </p>

                    <p class="text-gray-600 mb-6 leading-relaxed">
                        Une menace de sécurité critique a été détectée par l'assistant IA defAI. 
                        Une action immédiate est requise pour protéger l'intégrité de la plateforme.
                    </p>

                    <!-- Alert Details -->
                    <div class="bg-red-50 border-2 border-red-200 p-6 rounded-lg mb-6">
                        <h3 class="text-xl font-bold text-red-800 mb-4 flex items-center">
                            <i class="fas fa-bug text-red-600 mr-3"></i>
                            Détails de l'alerte
                        </h3>

                        <div class="space-y-4">
                            <div class="grid md:grid-cols-2 gap-4">
                                <div>
                                    <p class="text-sm font-bold text-red-700">Type de menace</p>
                                    <p class="text-gray-900 font-medium bg-white px-3 py-2 rounded border">{{ alert_type }}</p>
                                </div>
                                <div>
                                    <p class="text-sm font-bold text-red-700">Niveau de sévérité</p>
                                    <p class="text-gray-900 font-medium bg-white px-3 py-2 rounded border">
                                        <span class="text-red-600 font-bold">CRITIQUE</span>
                                    </p>
                                </div>
                                <div>
                                    <p class="text-sm font-bold text-red-700">Date/Heure</p>
                                    <p class="text-gray-900 font-medium bg-white px-3 py-2 rounded border">{{ timestamp }}</p>
                                </div>
                                <div>
                                    <p class="text-sm font-bold text-red-700">Source</p>
                                    <p class="text-gray-900 font-medium bg-white px-3 py-2 rounded border">Assistant IA defAI</p>
                                </div>
                            </div>

                            <div>
                                <p class="text-sm font-bold text-red-700 mb-2">Message utilisateur suspect</p>
                                <div class="bg-white p-3 rounded border border-red-200">
                                    <p class="text-gray-800 font-mono text-sm">{{ user_message }}</p>
                                </div>
                            </div>

                            <div>
                                <p class="text-sm font-bold text-red-700 mb-2">Description de la menace</p>
                                <div class="bg-white p-3 rounded border border-red-200">
                                    <p class="text-gray-800">{{ threat_description }}</p>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Actions Recommandées -->
                    <div class="bg-amber-50 border-l-4 border-amber-500 p-4 mb-6 rounded-r">
                        <div class="flex items-start">
                            <i class="fas fa-lightbulb text-amber-600 mt-1 mr-3 text-xl"></i>
                            <div>
                                <p class="text-amber-800 font-bold mb-2">ACTIONS RECOMMANDÉES:</p>
                                <ul class="text-amber-700 text-sm space-y-1">
                                    <li>• Vérifier les logs de l'utilisateur concerné</li>
                                    <li>• Analyser le pattern de requêtes suspectes</li>
                                    <li>• Envisager de suspendre temporairement le compte</li>
                                    <li>• Renforcer les mesures de sécurité si nécessaire</li>
                                    <li>• Documenter l'incident pour audit futur</li>
                                </ul>
                            </div>
                        </div>
                    </div>

                    <!-- CTA Buttons -->
                    <div class="text-center my-8 space-y-4">
                        <a href="{{ admin_dashboard_url }}" 
                           class="inline-block bg-red-600 hover:bg-red-700 text-white font-bold px-8 py-4 rounded-lg shadow-lg transition duration-300 transform hover:scale-105 no-underline">
                            <i class="fas fa-tachometer-alt mr-2"></i>
                            Accéder au Dashboard Admin
                        </a>
                        <br>
                        <a href="{{ security_logs_url }}" 
                           class="inline-block bg-gray-600 hover:bg-gray-700 text-white font-semibold px-6 py-3 rounded-lg shadow transition duration-300 no-underline">
                            <i class="fas fa-list-alt mr-2"></i>
                            Consulter les Logs de Sécurité
                        </a>
                    </div>
                </div>

                <!-- Footer -->
                <div class="bg-gray-900 text-white px-8 py-6">
                    <div class="text-center">
                        <p class="text-red-400 font-bold mb-2">
                            <i class="fas fa-exclamation-triangle mr-2"></i>
                            CETTE ALERTE NÉCESSITE UNE ATTENTION IMMÉDIATE
                        </p>
                        <p class="text-gray-400 text-sm mb-4">
                            Email généré automatiquement par le système de sécurité defAI
                        </p>
                        <div class="text-gray-500 text-xs">
                            <p class="mb-2">© 2025 DEFITECH - Système de Sécurité</p>
                            <p>Référence: SEC-{{ timestamp.replace(':', '').replace(' ', '').replace('/', '') }}</p>
                        </div>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """,
    },
    "registration_confirmation": {
        "subject": "Confirmation de votre inscription - DEFITECH",
        "template": """
        <!DOCTYPE html>
        <html lang="fr">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Inscription confirmée</title>
            <script src="https://cdn.tailwindcss.com"></script>
            <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
        </head>
        <body class="bg-gray-50 font-sans">
            <div class="max-w-2xl mx-auto my-8 bg-white shadow-lg rounded-lg overflow-hidden">
                <!-- Header -->
                <div class="bg-gradient-to-r from-blue-600 to-indigo-700 px-8 py-6">
                    <div class="flex items-center justify-between">
                        <div>
                            <h1 class="text-3xl font-bold text-white mb-1">DEFITECH</h1>
                            <p class="text-blue-100 text-sm">Plateforme Éducative Collaborative</p>
                        </div>
                        <i class="fas fa-user-plus text-white text-4xl opacity-80"></i>
                    </div>
                </div>

                <!-- Content -->
                <div class="px-8 py-8">
                    <p class="text-gray-700 mb-6 text-lg">
                        Bonjour <strong>{{ user.prenom }} {{ user.nom }}</strong>,
                    </p>

                    <p class="text-gray-600 mb-6 leading-relaxed">
                        Nous avons bien reçu votre demande d'inscription sur la plateforme DEFITECH. 
                        Votre compte est actuellement <strong>en attente de validation</strong> par l'administration.
                    </p>

                    <p class="text-gray-600 mb-6 leading-relaxed">
                        Vous recevrez un email dès que votre compte sera activé.
                    </p>

                    <div class="bg-blue-50 border-l-4 border-blue-500 p-4 rounded-r mb-6">
                        <div class="flex items-start">
                            <i class="fas fa-info-circle text-blue-600 mt-1 mr-3"></i>
                            <div>
                                <p class="text-blue-800 font-semibold mb-1">Information</p>
                                <p class="text-blue-700 text-sm">
                                    Cette procédure de validation nous permet de garantir la sécurité et l'intégrité de notre communauté éducative.
                                </p>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Footer -->
                <div class="bg-gray-50 px-8 py-6 border-t border-gray-200">
                    <div class="text-center text-gray-500 text-sm mb-4">
                        <i class="fas fa-envelope mr-2"></i>
                        Cet email a été envoyé automatiquement. Merci de ne pas y répondre.
                    </div>
                </div>
            </div>
        </body>
        </html>
        """,
    },
}

# Couleurs pour les priorités
PRIORITY_COLORS = {
    1: "#10b981",  # Vert - Faible
    2: "#f59e0b",  # Jaune - Moyenne
    3: "#ef4444",  # Rouge - Haute
    4: "#8b5cf6",  # Violet - Urgente
    5: "#000000",  # Noir - Critique
}


def send_async_email(app, msg):
    """Envoie un email de manière asynchrone"""
    with app.app_context():
        try:
            mail = Mail(app)
            mail.send(msg)
            logger.info(f"Email envoyé avec succès à {msg.recipients}")
        except Exception as e:
            logger.error(f"Erreur lors de l'envoi de l'email: {e}")


def send_email(to, subject, template_name, **kwargs):
    """
    Envoie un email en utilisant un template

    Args:
        to (str ou list): Adresse(s) email du destinataire
        subject (str): Sujet de l'email
        template_name (str): Nom du template à utiliser
        **kwargs: Variables à passer au template
    """
    app = current_app._get_current_object()

    if not app.config.get("MAIL_USERNAME"):
        logger.warning("Configuration email non définie. Email non envoyé.")
        return False

    try:
        # Récupérer le template
        template_info = EMAIL_TEMPLATES.get(template_name)
        if not template_info:
            logger.error(f"Template email '{template_name}' non trouvé")
            return False

        # Rendu du template
        html_content = render_template_string(template_info["template"], **kwargs)

        # Création du message
        msg = Message(
            subject=render_template_string(template_info["subject"], **kwargs),
            recipients=[to] if isinstance(to, str) else to,
            html=html_content,
            sender=app.config.get("MAIL_DEFAULT_SENDER"),
        )

        # Envoi asynchrone
        thread = Thread(target=send_async_email, args=[app, msg])
        thread.start()

        return True

    except Exception as e:
        logger.error(f"Erreur lors de la préparation de l'email: {e}")
        return False


def send_confirmation_email(user):
    """Envoie un email de confirmation d'inscription"""
    from flask import url_for

    login_url = url_for("auth.login", _external=True)

    return send_email(
        to=user.email,
        subject="Confirmation de votre inscription - DEFITECH",
        template_name="registration_confirmation",
        user=user,
        login_url=login_url,
    )


def send_password_reset_email(user, reset_token):
    """Envoie un email de réinitialisation de mot de passe"""
    from flask import url_for

    reset_url = url_for("auth.reset_password", token=reset_token, _external=True)

    return send_email(
        to=user.email,
        subject="Réinitialisation de votre mot de passe - DEFITECH",
        template_name="password_reset",
        user=user,
        reset_url=reset_url,
    )


def send_account_validation_email(user):
    """Envoie un email de validation de compte"""
    login_url = url_for("auth.login", _external=True)

    return send_email(
        to=user.email,
        subject="Bienvenue sur DEFITECH - Votre compte est activé",
        template_name="account_validated",
        user=user,
        login_url=login_url,
    )


def send_global_notification_email(user, notification):
    """Envoie un email de notification globale"""
    platform_url = url_for("main.index", _external=True)

    # Déterminer la couleur selon la priorité
    priority_color = PRIORITY_COLORS.get(notification.priorite, "#3b82f6")

    # Ajouter les informations de priorité au template
    notification.priority_color = priority_color
    notification.priorite_css = (
        "high"
        if notification.priorite >= 3
        else ("medium" if notification.priorite == 2 else "low")
    )

    return send_email(
        to=user.email,
        subject=f"{notification.titre} - DEFITECH",
        template_name="global_notification",
        user=user,
        notification=notification,
        platform_url=platform_url,
        priority_color=priority_color,
    )


def send_teacher_profile_request_email(admin, teacher, request):
    """Envoie un email de demande de modification de profil enseignant à un admin"""
    subject = (
        f"Demande de modification de profil - {teacher.user.prenom} {teacher.user.nom}"
    )
    return send_email(
        to=admin.email,
        subject=subject,
        template_name="teacher_profile_request",
        admin=admin,
        teacher=teacher,
        request=request,
    )


def send_security_alert_email(
    admin_email, admin_name, alert_type, user_message, threat_description
):
    """
    Envoie un email d'alerte de sécurité critique à l'administrateur

    Args:
        admin_email (str): Email de l'administrateur
        admin_name (str): Nom de l'administrateur
        alert_type (str): Type d'alerte (ex: "prompt_request", "credentials_request", "security_bypass")
        user_message (str): Message suspect de l'utilisateur
        threat_description (str): Description de la menace détectée
    """
    from flask import url_for
    from datetime import datetime

    timestamp = datetime.now().strftime("%d/%m/%Y à %H:%M:%S")

    return send_email(
        to=admin_email,
        subject=" ALERTE DE SÉCURITÉ CRITIQUE - DEFITECH",
        template_name="security_alert",
        admin_name=admin_name,
        alert_type=alert_type,
        timestamp=timestamp,
        user_message=user_message,
        threat_description=threat_description,
        admin_dashboard_url=url_for("admin.dashboard", _external=True),
        security_logs_url=url_for("security_logs", _external=True),
    )


def send_room_invitation(etudiant, enseignant, course, room_token, app):
    """
    Envoie une invitation par email pour rejoindre une salle de cours

    Args:
        etudiant: Objet Etudiant
        enseignant: Objet Enseignant
        course: Objet Matiere (cours)
        room_token: Token de la salle de cours
        app: Instance de l'application Flask
    """
    from flask import url_for

    # Construire l'URL complète pour rejoindre la salle
    join_url = url_for("room", token=room_token, _external=True)

    # Rendre l'URL HTTPS si en production
    if app.config.get("PREFERRED_URL_SCHEME") == "https":
        join_url = join_url.replace("http://", "https://")

    # Envoyer l'email
    return send_email(
        to=etudiant.user.email,
        subject=f"Cours en direct - {course.nom}",
        template_name="room_invitation",
        etudiant=etudiant.user,
        enseignant=enseignant.user if hasattr(enseignant, "user") else enseignant,
        course=course,
        join_url=join_url,
    )


def send_bulk_notification_email(users, notification):
    """
    Envoie une notification globale à plusieurs utilisateurs
    """
    success_count = 0
    failed_count = 0

    for user in users:
        # Avoid circular import issues by using the function here
        if send_global_notification_email(user, notification):
            success_count += 1
        else:
            failed_count += 1

    return success_count, failed_count
