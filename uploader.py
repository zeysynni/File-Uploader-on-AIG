"""Upload the intranet org-chart export into the knowledge base as facts.

Uploads each of the four CSV files of one export as one fact, its text
unchanged, under the topic of its file: organisationseinheiten, leiter,
stellvertretende, beauftragte. Facts are stored whole (no server-side
chunking). A file over the facts endpoint's token limit (~8190) is split
between CSV records into the fewest parts that fit, as evenly as possible,
each starting with the header line.

The ids of everything uploaded are kept in kb_facts_state.json, so the next run
replaces the previous upload instead of adding duplicates. See README.md.

    python uploader.py                      # dry run: list the facts, upload nothing
    python uploader.py --upload             # upload, then delete the previous upload
    python uploader.py --delete             # delete everything in the state file
    python uploader.py --dir Files --export 20261029-0555   # pick an export explicitly
"""
import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import requests
import tiktoken
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

KNOWLEDGE_BASE_ID = os.getenv("KNOWLEDGE_BASE_ID")
FACTS_URL = f"https://aigateway.eu/api/knowledge/base/v1/knowledgebases/{KNOWLEDGE_BASE_ID}/facts"
TOPICS_URL = f"https://aigateway.eu/api/knowledge/base/v1/knowledgebases/{KNOWLEDGE_BASE_ID}/topics"
STATE_FILE = HERE / "kb_facts_state.json"

MAX_FACT_TOKENS = 8000      # the endpoint rejects facts over ~8190 cl100k tokens
ENCODING = tiktoken.get_encoding("cl100k_base")
TIMEOUT = 60

TOPICS = {                  # part -> topic name in the knowledge base
    "units": "organisationseinheiten",
    "heads": "leiter",
    "deputies": "stellvertretende",
    "officers": "beauftragte",
}

PARTS = {
    "units": "organisationseinheiten_kein_lf",
    "heads": "leiter",
    "deputies": "stellvertreter",
    "officers": "beauftragte",
}


# --------------------------------------------------------------------------- reading

def find_export(folder: Path, export: str | None) -> tuple[str, dict[str, Path]]:
    """Return (export prefix, {part: path}) for the given or newest export in folder."""
    prefixes = defaultdict(dict)
    for p in folder.glob("*_intranet_export_ki_*.csv"):
        prefix, _, part = p.stem.partition("_intranet_export_ki_")
        for key, name in PARTS.items():
            if part == name:
                prefixes[prefix][key] = p
    if export:
        chosen = export
    else:
        complete = sorted(k for k, v in prefixes.items() if len(v) == len(PARTS))
        if not complete:
            raise SystemExit(f"No complete export (all of {list(PARTS.values())}) in {folder}")
        chosen = complete[-1]
    files = prefixes.get(chosen, {})
    missing = [PARTS[k] for k in PARTS if k not in files]
    if missing:
        raise SystemExit(f"Export {chosen} in {folder} is missing: {missing}")
    return chosen, files


def token_count(text: str) -> int:
    return len(ENCODING.encode(text))


# --------------------------------------------------------------------------- building facts

def csv_records(text: str, filename: str) -> list[tuple[int, int, str]]:
    """Split the file text into CSV records: [(first line, last line, raw text)].

    A record ends at a newline outside double quotes, so a quoted field that
    contains a line break stays in one record. The raw text is kept exactly,
    including its line ending.
    """
    records, buf, quotes, first = [], [], 0, 0
    lines = [line for line in re.split(r"(?<=\n)", text) if line]
    for no, line in enumerate(lines, 1):
        if not buf:
            first = no
        buf.append(line)
        quotes += line.count('"')
        if quotes % 2 == 0:               # quotes balanced: the record is complete
            records.append((first, no, "".join(buf)))
            buf, quotes = [], 0
    if buf:
        raise SystemExit(f"{filename}: unclosed quote in the record starting at line {first}. Nothing was uploaded.")
    return records


def pack(header_tokens: int, sizes: list[int], cap: int) -> list[list[int]]:
    """Fill parts in order up to `cap` tokens each; returns the record indices of each part."""
    parts, current, size = [], [], header_tokens
    for i, t in enumerate(sizes):
        if current and size + t > cap:
            parts.append(current)
            current, size = [], header_tokens
        current.append(i)
        size += t
    parts.append(current)
    return parts


def split_records(header: str, records: list[tuple[int, int, str]], filename: str) -> list[tuple[str, str]]:
    """Split a file that is too long for one fact into the fewest parts that fit.

    Splits only between records; every part starts with the original header
    line. Among the splits with the fewest parts it picks the most even one.
    Returns [(line range, text)].
    """
    h = token_count(header)
    sizes = [token_count(raw) for _, _, raw in records]
    for (first, last, _), t in zip(records, sizes):
        if h + t > MAX_FACT_TOKENS:
            where = f"line {first}" if first == last else f"lines {first}-{last}"
            raise SystemExit(f"{filename}: the record at {where} is {t} tokens; with the header ({h} tokens) "
                             f"it exceeds the fact limit of {MAX_FACT_TOKENS}. Nothing was uploaded.")

    limit = MAX_FACT_TOKENS
    while True:
        fewest = len(pack(h, sizes, limit))   # filling each part up to the limit gives the fewest parts
        lo, hi = h + max(sizes), limit        # smallest cap that still needs no more parts = most even split
        while lo < hi:
            mid = (lo + hi) // 2
            if len(pack(h, sizes, mid)) <= fewest:
                hi = mid
            else:
                lo = mid + 1
        parts = [(f"header + lines {records[p[0]][0]}-{records[p[-1]][1]}", header + "".join(records[i][2] for i in p))
                 for p in pack(h, sizes, lo)]
        # Token counts of joined text can differ slightly from the sum of the pieces; check the real count.
        over = max(token_count(text) for _, text in parts) - MAX_FACT_TOKENS
        if over <= 0:
            return parts
        limit -= over


def build_facts(files: dict[str, Path]) -> list[dict]:
    """One fact per file with its text unchanged (only the byte-order mark is dropped).

    A file over the endpoint's token limit is split between CSV records into the
    fewest parts that fit, each starting with the header line.
    """
    facts = []
    for part, topic in TOPICS.items():
        path = files[part]
        with open(path, encoding="utf-8-sig", newline="") as f:
            text = f.read()
        records = csv_records(text, path.name)
        if token_count(text) <= MAX_FACT_TOKENS:
            facts.append({"topic": topic, "key": topic, "content": text, "lines": f"lines 1-{records[-1][1]}"})
            continue
        header, body = records[0][2], records[1:]
        parts = split_records(header, body, path.name)
        for i, (lines, t) in enumerate(parts, 1):
            facts.append({"topic": topic, "key": f"{topic}:part{i}of{len(parts)}", "content": t, "lines": lines})
    for f in facts:
        f["tokens"] = token_count(f["content"])
    return facts


# --------------------------------------------------------------------------- API

def headers() -> dict:
    key = os.getenv("AIGATEWAY_KEY")
    if not key or not KNOWLEDGE_BASE_ID:
        raise SystemExit("AIGATEWAY_KEY or KNOWLEDGE_BASE_ID not found. Check your .env file.")
    return {"Authorization": f"Bearer {key}"}


def ensure_topics(names: list[str]) -> dict[str, str]:
    """Return {name: topic_id}, reusing existing topics and creating missing ones."""
    r = requests.get(TOPICS_URL, headers=headers(), timeout=TIMEOUT)
    r.raise_for_status()
    existing = {t["name"]: t["id"] for t in r.json()["topics"]}
    ids = {}
    for name in names:
        if name in existing:
            ids[name] = existing[name]
            continue
        c = requests.post(TOPICS_URL, headers=headers(), json={"name": name}, timeout=TIMEOUT)
        if not c.ok:
            raise SystemExit(f"Could not create topic {name!r}: HTTP {c.status_code} {c.text[:300]}")
        body = c.json()
        ids[name] = body.get("id") or body.get("topic", {}).get("id")
        if not ids[name]:
            raise SystemExit(f"Created topic {name!r} but found no id in the response: {body}")
        print(f"  created topic {name!r}: {ids[name]}")
    return ids


def fact_topic_id(fact_id: str) -> str | None:
    r = requests.get(f"{FACTS_URL}/{fact_id}", headers=headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()["fact"].get("topic_id")


def post_fact(content: str, topic_id: str) -> str:
    """Create one fact and return its id. One fact per request, because the API
    returns the ids of a multi-fact request in no particular order."""
    body = {"facts": [{"content": content}], "topic_id": topic_id}
    r = requests.post(FACTS_URL, headers=headers(), json=body, timeout=TIMEOUT)
    if r.status_code != 201:
        raise RuntimeError(f"POST facts: HTTP {r.status_code} {r.text[:500]}")
    ids = r.json().get("uuids", [])
    if len(ids) != 1:
        raise RuntimeError(f"POST facts: expected 1 id, got {ids}")
    return ids[0]


def delete_facts(ids: list[str]) -> list[str]:
    """Delete facts and check each is gone. Returns the ids that could not be deleted."""
    failed = []
    for i, fact_id in enumerate(ids, 1):
        d = requests.delete(f"{FACTS_URL}/{fact_id}", headers=headers(), timeout=TIMEOUT)
        if d.status_code == 404:
            continue                                  # already gone
        g = requests.get(f"{FACTS_URL}/{fact_id}", headers=headers(), timeout=TIMEOUT)
        if g.status_code != 404:
            print(f"  ! {fact_id}: delete HTTP {d.status_code}, still present (GET {g.status_code})")
            failed.append(fact_id)
        if i % 25 == 0:
            print(f"  deleted {i}/{len(ids)}")
    return failed


# --------------------------------------------------------------------------- state

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"current": None, "pending_delete": []}


def save_state(state: dict) -> None:
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATE_FILE)


def check_same_kb(state: dict) -> None:
    """The ids in the state file only mean something in the KB they were created in."""
    kb = (state.get("current") or {}).get("knowledge_base_id")
    if kb and kb != KNOWLEDGE_BASE_ID:
        raise SystemExit(f"{STATE_FILE.name} belongs to knowledge base {kb}, but .env points to "
                         f"{KNOWLEDGE_BASE_ID}. Switch .env back and run --delete first, or move the state file away.")


def all_ids(state: dict) -> list[str]:
    ids = list(state.get("pending_delete", []))
    if state.get("current"):
        ids += state["current"]["facts"].values()
    return ids


# --------------------------------------------------------------------------- commands

def upload(facts: list[dict], export: str) -> None:
    state = load_state()
    check_same_kb(state)
    topic_ids = ensure_topics(list(TOPICS.values()))
    created: dict[str, str] = {}
    try:
        for topic in TOPICS.values():
            for f in (f for f in facts if f["topic"] == topic):
                fact_id = post_fact(f["content"], topic_ids[topic])
                created[f["key"]] = fact_id
                if fact_topic_id(fact_id) != topic_ids[topic]:
                    raise RuntimeError(f"fact {fact_id} was not filed under topic {topic!r}")
                print(f"  uploaded {f['key']} ({f['tokens']} tokens) -> {fact_id}")
    except (RuntimeError, requests.RequestException) as e:
        print(f"Upload failed: {e}\nRolling back the {len(created)} facts created in this run ...")
        left = delete_facts(list(created.values()))
        if left:
            state["pending_delete"] = state.get("pending_delete", []) + left
            save_state(state)
            print(f"{len(left)} facts could not be rolled back; they are in {STATE_FILE.name} "
                  "and will be deleted by the next --upload or --delete.")
        raise SystemExit(1)

    # Record the new upload before deleting the old one, so no id is ever forgotten.
    old = all_ids(state)
    state = {
        "current": {
            "export": export,
            "knowledge_base_id": KNOWLEDGE_BASE_ID,
            "topics": topic_ids,
            "uploaded_at": datetime.now().isoformat(timespec="seconds"),
            "facts": created,
        },
        "pending_delete": old,
    }
    save_state(state)
    print(f"Uploaded {len(created)} facts from export {export}.")

    if old:
        print(f"Deleting {len(old)} facts of the previous upload ...")
        state["pending_delete"] = delete_facts(old)
        save_state(state)
        if state["pending_delete"]:
            print(f"{len(state['pending_delete'])} old facts could not be deleted; "
                  "they stay in the state file and are retried next run.")
            raise SystemExit(1)
    print("Done.")


def delete_all() -> None:
    state = load_state()
    check_same_kb(state)
    ids = all_ids(state)
    if not ids:
        print("Nothing to delete: the state file has no ids.")
        return
    print(f"Deleting {len(ids)} facts ...")
    left = delete_facts(ids)
    save_state({"current": None, "pending_delete": left})
    print(f"Deleted {len(ids) - len(left)}, failed {len(left)}.")
    if left:
        raise SystemExit(1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=str(HERE / "Files"), help="folder with the CSV export (default: Files)")
    ap.add_argument("--export", help="export prefix such as 20261029-0555 (default: newest complete one)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--upload", action="store_true", help="upload and replace the previous upload")
    mode.add_argument("--delete", action="store_true", help="delete everything listed in the state file")
    args = ap.parse_args()

    if args.delete:
        delete_all()
        return

    export, files = find_export(Path(args.dir), args.export)
    facts = build_facts(files)
    counts = ", ".join(f"{t}: {sum(f['topic'] == t for f in facts)}" for t in TOPICS.values())
    print(f"Export {export} -> knowledge base {KNOWLEDGE_BASE_ID}\n"
          f"{len(facts)} facts ({counts}), largest {max(f['tokens'] for f in facts)} tokens.")

    if args.upload:
        upload(facts, export)
        return

    for f in facts:
        print(f"  [{f['topic']}] {f['key']}: {f['lines']}, {f['tokens']} tokens, {len(f['content'])} characters")
    state = load_state()
    if state.get("current"):
        print(f"\nAn --upload would replace {len(all_ids(state))} facts of export "
              f"{state['current']['export']} (uploaded {state['current']['uploaded_at']}).")
    print("\nDry run, nothing uploaded. Use --upload to upload.")


if __name__ == "__main__":
    sys.exit(main())
