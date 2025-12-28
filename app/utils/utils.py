"""
Fichier utilitaire pour l'application DEFITECH
"""

ALLOWED_EXTENSIONS = {
    "pdf",
    "docx",
    "xlsx",
    "jpg",
    "jpeg",
    "png",
    "ico",
    "avif",
    "mp4",
    "avi",
    "mov",
    "zip",
    "rar",
    "7z",
    "tar",
    "gz",
    "bz2",
    "html",
    "css",
    "js",
    "jsx",
    "tsx",
    "ts",
    "py",
    "c",
    "cpp",
    "java",
    "jar",
    "class",
    "pyc",
    "pyo",
    "bat",
    "vbs",
}


def allowed_file(filename):
    """
    Vérifie si l'extension du fichier est autorisée

    Args:
        filename (str): Nom du fichier à vérifier

    Returns:
        bool: True si l'extension est autorisée, False sinon
    """
    if not filename:
        return False

    # Obtenir l'extension du fichier
    extension = filename.rsplit(".", 1)[1].lower() if "." in filename else ""

    return extension in ALLOWED_EXTENSIONS
