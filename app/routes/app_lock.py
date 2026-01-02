from flask import Blueprint, request, jsonify, session
from flask_login import login_required, current_user
from app.extensions import db, csrf
from datetime import datetime, timedelta
import secrets
import base64
from webauthn import (
    generate_registration_options,
    verify_registration_response,
    generate_authentication_options,
    verify_authentication_response,
    options_to_json,
    base64url_to_bytes,
)
from webauthn.helpers.structs import (
    RegistrationCredential,
    AuthenticatorSelectionCriteria,
    UserVerificationRequirement,
)
from app.models.webauthn_credential import WebauthnCredential

app_lock_bp = Blueprint("app_lock", __name__)


@app_lock_bp.route("/api/app-lock/status", methods=["GET"])
@login_required
def get_status():
    """Récupère l'état du verrouillage pour l'utilisateur actuel."""
    return jsonify(
        {
            "enabled": current_user.is_app_lock_enabled,
            "biometric_enabled": current_user.is_biometric_enabled,
            "timeout": current_user.app_lock_timeout,
            "is_locked": session.get("app_unlocked_until") is None
            or datetime.utcnow().timestamp() > session.get("app_unlocked_until", 0),
        }
    )


@app_lock_bp.route("/api/app-lock/verify-pin", methods=["POST"])
@csrf.exempt
@login_required
def verify_pin():
    """Vérifie le code PIN et prolonge la session de déverrouillage."""
    data = request.get_json()
    pin_code = data.get("pin")

    if not pin_code:
        return jsonify({"success": False, "message": "Code PIN requis"}), 400

    if current_user.verify_pin(pin_code):
        # Déverrouiller pour X minutes
        timeout_min = current_user.app_lock_timeout or 5
        session["app_unlocked_until"] = (
            datetime.utcnow() + timedelta(minutes=timeout_min)
        ).timestamp()
        session["is_app_locked"] = False
        return jsonify(
            {
                "success": True,
                "message": "Application déverrouillée",
                "unlocked_until": session["app_unlocked_until"],
            }
        )
    else:
        # Gérer le cooldown si nécessaire
        message = "Code PIN incorrect"
        if current_user.failed_pin_attempts >= 5:
            message = "Trop de tentatives. Veuillez patienter 30 secondes."

        return jsonify({"success": False, "message": message}), 401


@app_lock_bp.route("/api/app-lock/verify-password", methods=["POST"])
@csrf.exempt
@login_required
def verify_password():
    """Vérifie le mot de passe principal en cas d'oubli du PIN."""
    data = request.get_json()
    password = data.get("password")

    if not password:
        return jsonify({"success": False, "message": "Mot de passe requis"}), 400

    if current_user.verify_password(password):
        # Déverrouiller pour X minutes
        timeout_min = current_user.app_lock_timeout or 5
        session["app_unlocked_until"] = (
            datetime.utcnow() + timedelta(minutes=timeout_min)
        ).timestamp()
        session["is_app_locked"] = False
        return jsonify(
            {
                "success": True,
                "message": "Application déverrouillée via mot de passe",
                "unlocked_until": session["app_unlocked_until"],
            }
        )
    else:
        return jsonify({"success": False, "message": "Mot de passe incorrect"}), 401


@app_lock_bp.route("/api/app-lock/set-pin", methods=["POST"])
@login_required
def set_pin():
    """Définit ou modifie le code PIN."""
    data = request.get_json()
    new_pin = data.get("pin")
    password = data.get("password")  # Validation par mot de passe pour la sécurité

    if not new_pin or not (4 <= len(new_pin) <= 6) or not new_pin.isdigit():
        return (
            jsonify(
                {"success": False, "message": "Le PIN doit contenir 4 à 6 chiffres"}
            ),
            400,
        )

    if not current_user.verify_password(password):
        return jsonify({"success": False, "message": "Mot de passe incorrect"}), 401

    current_user.pin = new_pin
    current_user.is_app_lock_enabled = True

    # Changer le PIN réinitialise la biométrie (Sécurité)
    current_user.is_biometric_enabled = False
    # Supprimer les credentials WebAuthn associés
    for cred in current_user.webauthn_credentials:
        db.session.delete(cred)

    db.session.commit()

    # Marquer comme déverrouillé immédiatement
    timeout_min = current_user.app_lock_timeout or 5
    session["app_unlocked_until"] = (
        datetime.utcnow() + timedelta(minutes=timeout_min)
    ).timestamp()

    return jsonify({"success": True, "message": "Code PIN configuré avec succès"})


@app_lock_bp.route("/api/app-lock/settings", methods=["POST"])
@login_required
def update_settings():
    """Met à jour les paramètres de verrouillage."""
    data = request.get_json()

    if "enabled" in data:
        current_user.is_app_lock_enabled = bool(data["enabled"])
    if "timeout" in data:
        try:
            timeout = int(data["timeout"])
            if 1 <= timeout <= 60:
                current_user.app_lock_timeout = timeout
        except ValueError:
            pass

    db.session.commit()
    return jsonify({"success": True, "message": "Paramètres mis à jour"})


# ==========================================
# WEBAUTHN (BIOMETRICS) ROUTES
# ==========================================


@app_lock_bp.route("/api/app-lock/webauthn/register-options", methods=["GET"])
@login_required
def registration_options():
    """Génère les options pour l'enregistrement d'une nouvelle clé biométrique."""
    if not current_user.app_lock_pin_hash:
        return jsonify({"success": False, "message": "Configurez d'abord un PIN"}), 400

    # Créer un challenge aléatoire
    challenge = secrets.token_bytes(32)
    session["webauthn_challenge"] = base64.b64encode(challenge).decode("utf-8")

    # Récupérer les credentials existants pour éviter les doublons
    existing_credentials = [
        RegistrationCredential(id=base64url_to_bytes(cred.credential_id))
        for cred in current_user.webauthn_credentials
    ]

    options = generate_registration_options(
        rp_id=request.host.split(":")[0],
        rp_name="DEFITECH PWA",
        user_id=str(current_user.id).encode("utf-8"),
        user_name=current_user.email,
        user_display_name=f"{current_user.prenom} {current_user.nom}",
        challenge=challenge,
        authenticator_selection=AuthenticatorSelectionCriteria(
            user_verification=UserVerificationRequirement.REQUIRED,
            resident_key=None,
        ),
        exclude_credentials=existing_credentials,
    )

    return options_to_json(options)


@app_lock_bp.route("/api/app-lock/webauthn/register-verify", methods=["POST"])
@login_required
def registration_verify():
    """Vérifie la réponse d'enregistrement et enregistre la clé."""
    data = request.get_json()
    challenge = base64.b64decode(session.get("webauthn_challenge", ""))

    try:
        verification = verify_registration_response(
            credential=data,
            expected_challenge=challenge,
            expected_origin=f"{request.scheme}://{request.host}",
            expected_rp_id=request.host.split(":")[0],
        )

        # Enregistrer le nouveau credential
        new_cred = WebauthnCredential(
            user_id=current_user.id,
            credential_id=data.get("id"),
            public_key=base64.b64encode(verification.credential_public_key).decode(
                "utf-8"
            ),
            sign_count=verification.sign_count,
            device_name=request.headers.get("User-Agent", "Appareil inconnu")[:100],
        )

        db.session.add(new_cred)
        current_user.is_biometric_enabled = True
        db.session.commit()

        return jsonify({"success": True, "message": "Biométrie activée avec succès"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 400


@app_lock_bp.route("/api/app-lock/webauthn/login-options", methods=["GET"])
@login_required
def authentication_options():
    """Génère les options pour l'authentification par biométrie."""
    if not current_user.webauthn_credentials:
        return jsonify({"success": False, "message": "Aucune clé enregistrée"}), 404

    challenge = secrets.token_bytes(32)
    session["webauthn_challenge"] = base64.b64encode(challenge).decode("utf-8")

    allow_credentials = [
        RegistrationCredential(id=base64url_to_bytes(cred.credential_id))
        for cred in current_user.webauthn_credentials
    ]

    options = generate_authentication_options(
        rp_id=request.host.split(":")[0],
        challenge=challenge,
        allow_credentials=allow_credentials,
        user_verification=UserVerificationRequirement.REQUIRED,
    )

    return options_to_json(options)


@app_lock_bp.route("/api/app-lock/webauthn/login-verify", methods=["POST"])
@csrf.exempt
@login_required
def authentication_verify():
    """Vérifie la réponse d'authentification et déverrouille l'application."""
    data = request.get_json()
    challenge = base64.b64decode(session.get("webauthn_challenge", ""))

    credential_id = data.get("id")
    db_cred = WebauthnCredential.query.filter_by(
        credential_id=credential_id, user_id=current_user.id
    ).first()

    if not db_cred:
        return jsonify({"success": False, "message": "Clé inconnue"}), 404

    try:
        verification = verify_authentication_response(
            credential=data,
            expected_challenge=challenge,
            expected_origin=f"{request.scheme}://{request.host}",
            expected_rp_id=request.host.split(":")[0],
            credential_public_key=base64.b64decode(db_cred.public_key),
            credential_current_sign_count=db_cred.sign_count,
        )

        # Mettre à jour le compteur et la date
        db_cred.sign_count = verification.new_sign_count
        db_cred.last_use = datetime.utcnow()

        # Déverrouiller la session
        timeout_min = current_user.app_lock_timeout or 5
        session["app_unlocked_until"] = (
            datetime.utcnow() + timedelta(minutes=timeout_min)
        ).timestamp()
        session["is_app_locked"] = False

        db.session.commit()

        return jsonify(
            {
                "success": True,
                "message": "Déverrouillage réussi",
                "unlocked_until": session["app_unlocked_until"],
            }
        )
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 400
