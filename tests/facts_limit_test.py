"""Find the maximum length of one fact for the facts endpoint.

Writes to the PRODUCTION knowledge base if a fact is accepted, so it starts
with lengths that should be rejected (a 422 usually names the limit) and
prints the response of every request, including ids of anything created, so
it can be deleted again.

    python facts_limit_test.py 50000            # one fact of 50000 characters
    python facts_limit_test.py 50000 --topic <uuid>
"""
import json
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

KNOWLEDGE_BASE_ID = os.getenv("KNOWLEDGE_BASE_ID")
_BASE = "https://aigateway.eu/api/knowledge/base"
FACTS_URL = f"{_BASE}/v1/knowledgebases/{KNOWLEDGE_BASE_ID}/facts"
API_KEY = os.getenv("AIGATEWAY_KEY")
if not API_KEY or not KNOWLEDGE_BASE_ID:
    raise SystemExit("AIGATEWAY_KEY or KNOWLEDGE_BASE_ID not found. Check your .env file.")
HEADERS = {"Authorization": f"Bearer {API_KEY}"}

MARKER = "TEST-FAKT bitte ignorieren (Längentest api_test). "


def content_of(length: int) -> str:
    return (MARKER * (length // len(MARKER) + 1))[:length]


def post_fact(length: int, topic_id: str | None) -> requests.Response:
    body = {"facts": [{"content": content_of(length)}]}
    if topic_id:
        body["topic_id"] = topic_id
    return requests.post(FACTS_URL, headers=HEADERS, json=body, timeout=60)


if __name__ == "__main__":
    length = int(sys.argv[1])
    topic = sys.argv[sys.argv.index("--topic") + 1] if "--topic" in sys.argv else None
    r = post_fact(length, topic)
    print(f"length {length}: HTTP {r.status_code}")
    try:
        print(json.dumps(r.json(), ensure_ascii=False, indent=1)[:2000])
    except ValueError:
        print(r.text[:2000])
