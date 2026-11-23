"""Check that this machine can reach the knowledge base and write to it.

Run this first on a new laptop. It:
  1. checks that .env has AIGATEWAY_KEY and KNOWLEDGE_BASE_ID,
  2. checks that the key can see the knowledge base and lists its topics,
  3. creates one marked test fact, reads it back, deletes it, and checks it is gone.

The knowledge base ends unchanged. Nothing from Files/ is uploaded.

    python tests/smoke_test.py
"""
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

BASE = "https://aigateway.eu/api/knowledge/base/v1"
KB = os.getenv("KNOWLEDGE_BASE_ID")
KEY = os.getenv("AIGATEWAY_KEY")
TEXT = "SMOKE-TEST bitte ignorieren: Verbindungstest des Uploaders."


def step(ok: bool, message: str) -> None:
    print(("  OK   " if ok else "  FAIL ") + message)
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    step(bool(KEY), "AIGATEWAY_KEY is set in .env")
    step(bool(KB), "KNOWLEDGE_BASE_ID is set in .env")
    h = {"Authorization": f"Bearer {KEY}"}

    r = requests.get(f"{BASE}/knowledgebases", headers=h, timeout=60)
    step(r.status_code == 200, f"API key accepted (HTTP {r.status_code})")
    visible = {kb["id"]: kb["name"] for kb in r.json()["knowledge_bases"]}
    step(KB in visible, f"key can see knowledge base {KB}"
         + (f" ({visible[KB]})" if KB in visible else f"; it sees only {visible}"))

    r = requests.get(f"{BASE}/knowledgebases/{KB}/topics", headers=h, timeout=60)
    step(r.ok, f"topics readable (HTTP {r.status_code})")
    for t in r.json()["topics"]:
        print(f"         topic {t['name']!r}: {t['fact_count']} facts")

    facts_url = f"{BASE}/knowledgebases/{KB}/facts"
    r = requests.post(facts_url, headers=h, json={"facts": [{"content": TEXT}]}, timeout=60)
    step(r.status_code == 201, f"test fact created (HTTP {r.status_code}) {'' if r.ok else r.text[:300]}")
    fact_id = r.json()["uuids"][0]
    try:
        r = requests.get(f"{facts_url}/{fact_id}", headers=h, timeout=60)
        step(r.ok and r.json()["fact"]["content"] == TEXT, "test fact read back unchanged")
    finally:
        d = requests.delete(f"{facts_url}/{fact_id}", headers=h, timeout=60)
        gone = requests.get(f"{facts_url}/{fact_id}", headers=h, timeout=60).status_code == 404
        step(gone, f"test fact deleted (HTTP {d.status_code})"
             + ("" if gone else f" - delete fact {fact_id} by hand"))
    print("All checks passed. You can run: python uploader.py")
