"""
Routes pour la gestion des notifications (API et standard)
"""

from flask import Blueprint, jsonify, request, flash, redirect, url_for, current_app
from flask_login import login_required, current_user
from app.models.notification import Notification
from app.extensions import db, csrf

notifications_bp = Blueprint("notifications", __name__, url_prefix="/notifications")


@notifications_bp.route("/api", methods=["GET"])
@login_required
def api_get_notifications():
    """
    API endpoint to get user notifications
    Returns JSON with notifications and unread count
    """
    try:
        notifications = (
            Notification.query.filter_by(user_id=current_user.id)
            .order_by(Notification.date_created.desc())
            .limit(50)
            .all()
        )

        unread_count = Notification.query.filter_by(
            user_id=current_user.id, est_lue=False
        ).count()

        notifications_data = [
            {
                "id": n.id,
                "titre": n.titre or "Notification",
                "message": n.message,
                "type": n.type or "info",
                "est_lue": n.est_lue,
                "lien": n.link,
                "date_creation": n.date_created.isoformat() if n.date_created else None,
            }
            for n in notifications
        ]

        return jsonify(
            {
                "success": True,
                "notifications": notifications_data,
                "unread_count": unread_count,
            }
        )
    except Exception as e:
        current_app.logger.error(f"Error fetching notifications: {str(e)}")
        return jsonify({"success": False, "error": "Failed to load notifications"}), 500


@notifications_bp.route("/api/count", methods=["GET"])
@login_required
def api_get_notification_count():
    """
    API endpoint to get unread notification count
    """
    try:
        unread_count = Notification.query.filter_by(
            user_id=current_user.id, est_lue=False
        ).count()

        # Get the latest notification
        latest = (
            Notification.query.filter_by(user_id=current_user.id)
            .order_by(Notification.date_created.desc())
            .first()
        )

        latest_data = None
        if latest:
            latest_data = {
                "id": latest.id,
                "titre": latest.titre or "Notification",
                "message": latest.message,
                "type": latest.type or "info",
            }

        return jsonify(
            {"success": True, "unread_count": unread_count, "latest": latest_data}
        )
    except Exception as e:
        current_app.logger.error(f"Error fetching notification count: {str(e)}")
        return (
            jsonify({"success": False, "error": "Failed to get notification count"}),
            500,
        )


@notifications_bp.route("/api/<int:notification_id>/mark-read", methods=["POST"])
@csrf.exempt
@login_required
def api_mark_notification_read(notification_id):
    """
    API endpoint to mark a notification as read
    """
    try:
        notification = Notification.query.get_or_404(notification_id)

        # Verify ownership
        if notification.user_id != current_user.id:
            return jsonify({"success": False, "error": "Unauthorized"}), 403

        notification.est_lue = True
        db.session.commit()

        return jsonify({"success": True, "message": "Notification marked as read"})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error marking notification as read: {str(e)}")
        return (
            jsonify({"success": False, "error": "Failed to mark notification as read"}),
            500,
        )


@notifications_bp.route("/api/mark-all-read", methods=["POST"])
@csrf.exempt
@login_required
def api_mark_all_notifications_read():
    """
    API endpoint to mark all notifications as read
    """
    try:
        Notification.query.filter_by(user_id=current_user.id, est_lue=False).update(
            {"est_lue": True}
        )
        db.session.commit()

        return jsonify({"success": True, "message": "All notifications marked as read"})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error marking all notifications as read: {str(e)}")
        return (
            jsonify(
                {"success": False, "error": "Failed to mark all notifications as read"}
            ),
            500,
        )


@notifications_bp.route("/api/<int:notification_id>", methods=["DELETE"])
@csrf.exempt
@login_required
def api_delete_notification(notification_id):
    """
    API endpoint to delete a notification
    """
    try:
        notification = Notification.query.get_or_404(notification_id)

        # Verify ownership
        if notification.user_id != current_user.id:
            return jsonify({"success": False, "error": "Unauthorized"}), 403

        db.session.delete(notification)
        db.session.commit()

        return jsonify({"success": True, "message": "Notification deleted"})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting notification: {str(e)}")
        return (
            jsonify({"success": False, "error": "Failed to delete notification"}),
            500,
        )


@notifications_bp.route("/api/clear-all", methods=["DELETE"])
@csrf.exempt
@login_required
def api_clear_all_notifications():
    """
    API endpoint to delete all notifications for current user
    """
    try:
        Notification.query.filter_by(user_id=current_user.id).delete()
        db.session.commit()

        return jsonify({"success": True, "message": "All notifications cleared"})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error clearing all notifications: {str(e)}")
        return (
            jsonify({"success": False, "error": "Failed to clear notifications"}),
            500,
        )


@notifications_bp.route("/lue/<int:notif_id>")
@login_required
def marquer_notification_lue(notif_id):
    """
    Route standard pour marquer une notification comme lue (utilisée par les liens directs email/templates).
    """
    notif = Notification.query.get_or_404(notif_id)
    if notif.user_id != current_user.id:
        flash("Accès non autorisé.", "error")
        return redirect(url_for("main.index"))

    notif.est_lue = True
    db.session.commit()

    # Rediriger vers le lien de la notification si présent, sinon vers le dashboard
    if hasattr(notif, "link") and notif.link:
        return redirect(notif.link)

    if current_user.role == "etudiant":
        return redirect(url_for("students.etudiant_dashboard"))
    elif current_user.role == "enseignant":
        return redirect(url_for("teachers.dashboard"))
    else:
        return redirect(url_for("admin.dashboard"))
