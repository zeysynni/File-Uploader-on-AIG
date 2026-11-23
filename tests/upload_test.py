"""Upload files to the knowledge base through the v2 files endpoint (server-side chunking).

    python upload_test.py <file> [<file> ...]
"""
import json
import mimetypes
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

KNOWLEDGE_BASE_ID = os.getenv("KNOWLEDGE_BASE_ID")
API_KEY = os.getenv("AIGATEWAY_KEY")
if not API_KEY or not KNOWLEDGE_BASE_ID:
    raise SystemExit("AIGATEWAY_KEY or KNOWLEDGE_BASE_ID not found. Check your .env file.")

API_ENDPOINT = f"https://aigateway.eu/api/knowledge/base/v2/knowledgebases/{KNOWLEDGE_BASE_ID}/files"
AUTH_HEADERS = {"Authorization": f"Bearer {API_KEY}"}

IMPORT_STRATEGY_ID = "df561ba3-7001-4eb7-8f94-b50872c9f9fa"  # default

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "upload_log.json")


def save_log(entry: dict) -> None:
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            log = json.load(f)
    else:
        log = []
    log.append(entry)
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)


def upload_file(filepath: str) -> None:
    filename = os.path.basename(filepath)
    mime = mimetypes.guess_type(filename)[0] or ("text/markdown" if filename.endswith(".md") else "text/plain")
    with open(filepath, "rb") as f:
        files = {"uploaded_files": (filename, f, mime)}
        data = {
            "import_strategy_id": IMPORT_STRATEGY_ID,
            "overlap": 0,
            "max_characters": 500,
            "new_after_n_chars": 500,
        }
        response = requests.post(API_ENDPOINT, headers=AUTH_HEADERS, files=files, data=data, timeout=120)
    print(f"{filename}: HTTP {response.status_code}")
    print(f"Response: {response.text}")

    if response.status_code == 201:
        for f in response.json().get("uploaded_files", []):
            save_log({"file_id": f["file_id"], "filename": f["filename"], "status": f["status"],
                      "knowledge_base_id": KNOWLEDGE_BASE_ID})


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    for path in sys.argv[1:]:
        upload_file(path)
