"""Offline checks of how uploader.py splits files that are too long for one fact.

Builds made-up exports in a temporary folder from the real CSVs in Files/ and
checks the split logic. Makes no API calls; the knowledge base is not touched.

    python tests/split_test.py
"""
import math
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import uploader as u  # noqa: E402

failures = 0


def check(ok: bool, message: str) -> None:
    global failures
    print(("  OK   " if ok else "  FAIL ") + message)
    failures += not ok


def build(tmp: Path, name: str, units_text: str) -> list[dict] | str:
    """Write an export whose units file is `units_text`; return its unit facts or the error text."""
    folder = tmp / name
    folder.mkdir()
    for key, part in u.PARTS.items():
        text = units_text if key == "units" else ORIGINAL[key]
        (folder / f"20990101-0000_intranet_export_ki_{part}.csv").write_text(text, encoding="utf-8", newline="")
    try:
        facts = u.build_facts(u.find_export(folder, None)[1])
    except SystemExit as e:
        return str(e)
    return [f for f in facts if f["topic"] == "organisationseinheiten"]


def rejoin(parts: list[dict], header: str) -> str:
    return parts[0]["content"] + "".join(p["content"][len(header):] for p in parts[1:])


if __name__ == "__main__":
    real = u.find_export(Path(u.HERE / "Files"), None)[1]
    ORIGINAL = {k: open(p, encoding="utf-8-sig", newline="").read() for k, p in real.items()}
    header, *rows = ORIGINAL["units"].splitlines(keepends=True)

    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)

        print("Real export: every fact is the file text unchanged")
        facts = u.build_facts(real)
        for key, text in ORIGINAL.items():
            of_file = [f for f in facts if f["topic"] == u.TOPICS[key]]
            joined = rejoin(of_file, header if key == "units" else "")
            check(joined == text, f"{u.TOPICS[key]}: {len(of_file)} fact(s) rebuild the file exactly")
        check(all(f["tokens"] <= u.MAX_FACT_TOKENS for f in facts), "all facts within the token limit")

        print("File 4x too long: fewest parts, even sizes, unchanged")
        text = header + "".join(rows) * 4
        parts = build(tmp, "x4", text)
        lower = math.ceil(u.token_count("".join(rows) * 4) / (u.MAX_FACT_TOKENS - u.token_count(header)))
        check(len(parts) == lower, f"{len(parts)} parts, minimum possible is {lower}")
        check(all(p["tokens"] <= u.MAX_FACT_TOKENS for p in parts), "every part within the limit")
        check(all(p["content"].startswith(header) for p in parts), "every part starts with the header line")
        check(rejoin(parts, header) == text, "parts rebuild the file exactly")

        print("One row over the limit: stops with file and line")
        error = build(tmp, "huge", header + "".join(rows[:10]) + "X|X|X|" + "Wort " * 9000 + "\r\n" + "".join(rows[10:]))
        check(isinstance(error, str) and "line 12" in error and "kein_lf.csv" in error, f"error: {error}")

        print("Quoted field with line breaks: record is never cut")
        record = 'Ref. Q|Q|"Mehrzeilig\r\nzweite Zeile\r\ndritte"|Aufgabe\r\n'
        text = header + "".join(rows[:50]) + record + "".join(rows[50:])
        parts = build(tmp, "quoted", text)
        check(sum(record in p["content"] for p in parts) == 1, "multi-line record is whole in one part")
        check(rejoin(parts, header) == text, "parts rebuild the file exactly")

        print("Unclosed quote: stops with file and line")
        error = build(tmp, "unclosed", header + "".join(rows[:5]) + 'Ref. Q|Q|"kaputt|x\r\n' + "".join(rows[5:]))
        check(isinstance(error, str) and "line 7" in error, f"error: {error}")

    print("All checks passed." if not failures else f"{failures} check(s) failed.")
    sys.exit(1 if failures else 0)
