import os
from dotenv import load_dotenv
import requests

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    print("No API Key found")
else:
    r = requests.get(
        f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    )
    print(r.json())
