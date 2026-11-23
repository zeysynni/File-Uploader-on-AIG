import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

KNOWLEDGE_BASE_ID = os.getenv("KNOWLEDGE_BASE_ID")
API_KEY = os.getenv("AIGATEWAY_KEY")
if not API_KEY or not KNOWLEDGE_BASE_ID:
    raise SystemExit("AIGATEWAY_KEY or KNOWLEDGE_BASE_ID not found. Check your .env file.")

BASE_URL = f"https://aigateway.eu/api/knowledge/base/v1/knowledgebases/{KNOWLEDGE_BASE_ID}/files"

AUTH_HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
}


def delete_file(file_id: str) -> None:
    response = requests.delete(f"{BASE_URL}/{file_id}", headers=AUTH_HEADERS)
    print(f"Status  : {response.status_code}")
    print(f"Response: {response.text}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python delete_test.py <file_id>")
    delete_file(sys.argv[1])
