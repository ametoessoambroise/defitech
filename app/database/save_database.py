import subprocess
import datetime
import os

# Informations de connexion
DB_URI = "postgresql+psycopg2://defitech_user:smiler_12@localhost/defitech_db"

# Sortie du dump
timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
output_file = f"defitech_db_backup_{timestamp}.sql"

# Construction de la commande pg_dump
# On enlève "postgresql+psycopg2://" pour récupérer les morceaux
user = "defitech_user"
password = "smiler_12"
host = "localhost"
dbname = "defitech_db"

# IMPORTANT : pg_dump lit le mot de passe via la variable PGPASSWORD
os.environ["PGPASSWORD"] = password

pg_dump_path = r"C:\Program Files\PostgreSQL\18\bin\pg_dump.exe"

cmd = [
    pg_dump_path,
    "-U", user, # utilisateur
    "-h", host, # hote
    "-d", dbname, # base de données
    "-f", output_file, # fichier de sortie
    "-p", "5432", # port
    "-E", "UTF8", # encodage
]

try:
    print("📥 Sauvegarde de la base en cours...")
    subprocess.run(cmd, check=True)
    print(f"✅ Sauvegarde terminée : {output_file}")
except subprocess.CalledProcessError as e:
    print("❌ Erreur durant le dump :", e)
