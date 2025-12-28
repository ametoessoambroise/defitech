import os
import sys
from dotenv import load_dotenv
import psycopg2

print("Script started", flush=True)

if os.path.exists(".env"):
    print(".env file exists", flush=True)
else:
    print(".env file NOT found", flush=True)

print("Loading .env...", flush=True)
load_dotenv()
print(".env loaded", flush=True)

uri = os.getenv("SQLALCHEMY_DATABASE_URI")
print(f"URI from env: {uri}", flush=True)

if uri:
    print(f"URI Length: {len(uri)}", flush=True)
    try:
        encoded = uri.encode("utf-8")
        print(f"URI Encoded (UTF-8): {encoded}", flush=True)
    except Exception as e:
        print(f"Error encoding URI: {e}", flush=True)

if uri and uri.startswith("postgresql"):
    try:
        # Simplify for psycopg2
        dsn = uri.replace("postgresql+psycopg2://", "postgresql://")
        print(f"Connecting to DSN: {dsn}", flush=True)
        conn = psycopg2.connect(dsn)
        print("Connection successful!", flush=True)
        conn.close()
    except Exception as e:
        print(f"Connection failed: {e}", flush=True)
        import traceback

        traceback.print_exc()

print("Script finished", flush=True)
