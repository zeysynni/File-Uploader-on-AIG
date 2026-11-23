"""Binary-search the exact maximum fact length (in tokens) of the facts endpoint.

Every accepted fact is deleted immediately and checked to be gone (GET -> 404),
so the production knowledge base ends unchanged. Lengths are counted with
tiktoken's cl100k_base, the tokenizer of OpenAI's embedding models.

    python facts_limit_search.py            # search between 8000 and 8200 tokens
"""
import requests
import tiktoken

from facts_limit_test import FACTS_URL, HEADERS, MARKER

enc = tiktoken.get_encoding("cl100k_base")
SOURCE = enc.encode(MARKER * 3000)


def text_of(tokens: int) -> str:
    """A text that re-encodes to exactly `tokens` tokens."""
    n = tokens
    while True:
        text = enc.decode(SOURCE[:n])
        actual = len(enc.encode(text))
        if actual == tokens:
            return text
        n += tokens - actual


def accepted(tokens: int) -> bool:
    text = text_of(tokens)
    r = requests.post(FACTS_URL, headers=HEADERS, json={"facts": [{"content": text}]}, timeout=60)
    if r.status_code == 201:
        for fact_id in r.json()["uuids"]:
            d = requests.delete(f"{FACTS_URL}/{fact_id}", headers=HEADERS, timeout=60)
            gone = requests.get(f"{FACTS_URL}/{fact_id}", headers=HEADERS, timeout=60).status_code == 404
            print(f"  created {fact_id} -> deleted {d.status_code}, gone: {gone}")
            if not gone:
                raise SystemExit(f"FACT {fact_id} NOT DELETED — delete it by hand")
        print(f"{tokens} tokens ({len(text)} chars): accepted")
        return True
    if r.status_code == 400 and "maximum input length" in r.text:
        print(f"{tokens} tokens ({len(text)} chars): rejected (token limit)")
        return False
    raise SystemExit(f"{tokens} tokens: unexpected {r.status_code} {r.text[:300]}")


if __name__ == "__main__":
    lo, hi = 8000, 8200          # lo must be accepted, hi rejected
    assert accepted(lo) and not accepted(hi)
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if accepted(mid):
            lo = mid
        else:
            hi = mid
    print(f"\nMAXIMUM: {lo} tokens accepted, {hi} rejected")
