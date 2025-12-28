from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db, login_manager


class User(UserMixin, db.Model):
    # Ensure the User model maps to the 'users' table (plural) which is used by migrations
    # and other models (PasswordResetToken, etc.).
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(100), nullable=False)
    prenom = db.Column(db.String(100), nullable=False)
    email = db.Column(
        db.String(255), unique=True, nullable=False, index=True
    )  # Augmenté à 255 caractères
    password_hash = db.Column(
        db.String(255), nullable=True  # Augmenté à 255 caractères
    )  # Nullable pour la connexion sociale
    role = db.Column(
        db.String(50), nullable=False, default="etudiant"
    )  # Augmenté à 50 caractères
    date_naissance = db.Column(db.Date, nullable=True)
    sexe = db.Column(db.String(20), nullable=True)  # Augmenté à 20 caractères
    telephone = db.Column(db.String(30), nullable=True)  # Augmenté à 30 caractères
    adresse = db.Column(
        db.Text, nullable=True
    )  # Changé en Text pour les adresses longues
    linkedin = db.Column(
        db.Text, nullable=True
    )  # Changé en Text pour les adresses longues
    github = db.Column(
        db.Text, nullable=True
    )  # Changé en Text pour les adresses longues
    bio = db.Column(db.Text, nullable=True)  # Changé en Text pour les adresses longues
    ville = db.Column(db.String(150), nullable=True)  # Augmenté à 150 caractères
    code_postal = db.Column(db.String(20), nullable=True)  # Augmenté à 20 caractères
    pays = db.Column(db.String(150), nullable=True)  # Augmenté à 150 caractères
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    date_derniere_connexion = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    email_confirmed = db.Column(db.Boolean, default=False, nullable=False)
    photo_profil = db.Column(
        db.String(500),
        nullable=True,  # Augmenté à 500 caractères pour les chemins de fichiers longs
    )  # Nom du fichier de la photo de profil
    age = db.Column(db.Integer, nullable=True)  # Âge de l'utilisateur
    # 'en_attente', 'approuve', 'rejete'
    statut = db.Column(db.String(50), default="en_attente")  # Augmenté à 50 caractères

    # Relations
    # etudiant sera défini après que Etudiant soit défini
    etudiant = db.relationship("Etudiant", back_populates="user", uselist=False)
    # enseignant sera défini après que Enseignant soit défini
    enseignant = db.relationship("Enseignant", back_populates="user", uselist=False)

    # Relations avec les publications et commentaires
    # posts sera défini après que Post soit défini
    posts = db.relationship(
        "Post", back_populates="auteur", cascade="all, delete-orphan"
    )
    # commentaires sera défini après que Commentaire soit défini
    commentaires = db.relationship(
        "Commentaire", back_populates="auteur", cascade="all, delete-orphan"
    )

    # Relations avec les notifications
    notifications = db.relationship(
        "Notification", back_populates="utilisateur", lazy="dynamic"
    )

    # Relations avec l'administration des filières (through enseignant relationship)
    # filieres_admin relationship is not needed since we can access through enseignant

    # Explicitly set primaryjoin so SQLAlchemy can resolve the relationship even
    # if PasswordResetToken is not yet fully mapped when this class is imported.
    password_reset_tokens = db.relationship(
        "PasswordResetToken",
        backref="user",
        cascade="all, delete-orphan",
        primaryjoin="User.id==PasswordResetToken.user_id",
        lazy="dynamic",
    )

    # Relations avec la bibliothèque (models not implemented yet)
    # documents_telecharges sera défini après que Document soit défini
    # documents_telecharges = None
    # documents_favoris sera défini après que Document soit défini
    # documents_favoris = None

    # Relations avec les demandes de modification de profil
    profile_update_requests = db.relationship(
        "TeacherProfileUpdateRequest",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    # Quota d'images (2 images par heure)
    image_quota_reset = db.Column(
        db.DateTime, default=datetime.utcnow
    )  # Dernière réinitialisation du quota
    images_used_current_hour = db.Column(
        db.Integer, default=0
    )  # Images utilisées cette heure
    total_images_generated = db.Column(
        db.Integer, default=0
    )  # Total d'images générées par l'utilisateur

    # Propriétés calculées
    @property
    def nom_complet(self):
        return f"{self.prenom} {self.nom}"

    @property
    def password(self):
        raise AttributeError("Le mot de passe n'est pas un attribut lisible")

    @password.setter
    def password(self, password):
        self.password_hash = generate_password_hash(password)

    def verify_password(self, password):
        if self.password_hash is None:
            return False
        return check_password_hash(self.password_hash, password)

    def has_role(self, role_name):
        return self.role == role_name

    def is_admin(self):
        return self.role == "admin"

    def is_etudiant(self):
        return self.role == "etudiant"

    def is_enseignant(self):
        return self.role == "enseignant"

    def can_generate_image(self):
        """Vérifie si l'utilisateur peut générer une image selon son quota"""
        from datetime import datetime, timedelta

        now = datetime.utcnow()

        # Vérifier si le quota doit être réinitialisé (toutes les heures)
        if now - self.image_quota_reset >= timedelta(hours=1):
            self.images_used_current_hour = 0
            self.image_quota_reset = now
            db.session.commit()

        # Vérifier si l'utilisateur a atteint son quota de 2 images/heure
        return self.images_used_current_hour < 2

    def use_image_quota(self):
        """Utilise une image du quota de l'utilisateur"""
        if self.can_generate_image():
            self.images_used_current_hour += 1
            self.total_images_generated += 1
            db.session.commit()
            return True
        return False

    def get_image_quota_status(self):
        """Retourne le statut du quota d'images"""
        from datetime import datetime

        now = datetime.utcnow()
        time_until_reset = 60 - now.minute  # minutes until next hour

        return {
            "can_generate": self.can_generate_image(),
            "used_current_hour": self.images_used_current_hour,
            "max_per_hour": 2,
            "total_generated": self.total_images_generated,
            "minutes_until_reset": time_until_reset,
        }

    def get_id(self):
        return str(self.id)

    def __repr__(self):
        return f"<User {self.email}>"


@login_manager.user_loader
def load_user(user_id):
    user = User.query.get(int(user_id))
    # Si l'utilisateur n'existe plus, retourner None pour forcer la déconnexion
    return user
