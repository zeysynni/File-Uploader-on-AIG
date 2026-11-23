# KB Uploader

Uploads the intranet org-chart export (four CSV files) into an aigateway.eu
knowledge base as **facts**, one fact per file, with the customer data unchanged.

| CSV file (`<export>_intranet_export_ki_…`) | Topic in the knowledge base |
|---|---|
| `organisationseinheiten_kein_lf.csv` | `organisationseinheiten` |
| `leiter.csv` | `leiter` |
| `stellvertreter.csv` | `stellvertretende` |
| `beauftragte.csv` | `beauftragte` |

- **Not chunked:** facts are stored whole. Uploading through the files endpoint
  would instead cut the text into chunks.
- **Unchanged:** each fact is the file's exact text. Only the byte-order mark
  at the start of the file is dropped.
- **Size limit:** the facts endpoint rejects a fact over ~8,190 tokens. A file
  over the limit is split into several facts. See
  [Files that are too long](#files-that-are-too-long). Currently
  `organisationseinheiten` (~14.5k tokens) becomes 2 facts.
- **Topics** are created automatically if they don't exist yet.

## Setup

Requires Python 3.10+.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # then fill in the two values
```

`.env`:

```
AIGATEWAY_KEY=<API key from aigateway.eu>
KNOWLEDGE_BASE_ID=<id of the target knowledge base>
```

Check that the key and the knowledge base work. This creates one test fact,
reads it back and deletes it:

```bash
.venv/bin/python tests/smoke_test.py
```

## Usage

Put the four CSV files of an export into `Files/`, then:

```bash
.venv/bin/python uploader.py            # dry run: lists the facts it would upload, uploads nothing
.venv/bin/python uploader.py --upload   # upload
.venv/bin/python uploader.py --delete   # remove everything the uploader uploaded
```

Options:

- `--dir PATH` reads the CSV files from another folder (default `Files/`).
- `--export 20261029-0555` picks a specific export. By default the uploader
  uses the newest export with all four files.

### Updating with a new export

Drop the new CSV files into `Files/` and run `--upload` again. The previous
upload is **replaced**, not duplicated. It works like this:

1. The new facts are uploaded.
2. Their ids are saved to `kb_facts_state.json`.
3. Only then are the old facts deleted.

If an upload fails halfway, the facts created in that run are rolled back and
the previous upload stays live. Facts that could not be deleted are kept in the
state file and retried on the next `--upload` or `--delete`.

**Keep `kb_facts_state.json`.** It is the only record of which facts the
uploader created. If it is lost, the next upload cannot remove the old facts,
and they have to be deleted by hand in aigateway.eu. The uploader only ever
deletes facts listed in this file, never anything else in the knowledge base.

The state file belongs to one knowledge base. If `.env` points to a different
one, the uploader stops rather than deleting by the wrong ids.

## Files that are too long

The uploader treats any file over 8,000 tokens (counted with `tiktoken`
`cl100k_base`, safely under the API's ~8,190) like this:

- **Split only between CSV records.** A record ends at a line break outside
  double quotes, so a quoted field that contains line breaks is never cut.
- **Every part starts with the file's original header line.** Records are
  copied exactly, line endings included. Joined back together (header once),
  the parts give the original file.
- **Fewest parts, as even as possible.** The uploader first works out the
  minimum number of parts needed, then picks the most even split with that
  number. Example: a 58k-token file becomes 8 parts of about 7.2k tokens.
- **Same topic.** All parts go into the file's topic, as
  `<topic>:part1of2`, `<topic>:part2of2`, … The dry run shows the lines and
  token count of each part.

**When it stops instead.** Before anything is uploaded, the uploader stops with
the file name and line number if:

- one record plus the header is over the limit, e.g. `…kein_lf.csv: the record
  at line 12 is 9008 tokens; with the header (14 tokens) it exceeds the fact
  limit of 8000. Nothing was uploaded.`
- a quote is never closed, e.g. `…: unclosed quote in the record starting at
  line 7.`

All facts are built before the first request, so a problem in any file means
nothing is uploaded and the knowledge base is not touched.

**Known limitations:**

- A question that needs rows from two parts of a split file has to draw on
  two facts.
- Only the four expected file names are read. Other files in `Files/` are
  skipped without a warning.

## Files

```
uploader.py            the uploader
requirements.txt       Python dependencies
.env.example           template for .env (copy to .env, never share .env)
.gitignore             keeps .env, .venv and the customer CSVs out of git
kb_facts_state.json    ids of the current upload (created by --upload)
Files/                 the CSV export to upload (not in git, see below)
test_data/             mock CSVs and the ids of their one-time upload (not in git)
tests/                 manual test scripts, see below
```

### test_data/ (mock data, local only)

`test_data/` is in `.gitignore`, so it exists only on the machine where the
mock upload was made. It holds four mock CSV files with made-up people and phone numbers:
`organisationseinheiten_MOCK.csv`, `leiter_MOCK.csv`, `stellvertreter_MOCK.csv`
and `beauftragte_MOCK.csv`. They were uploaded **once**, on 2026-11-21, into
the same knowledge base, one fact per file, in their own topics:

| File | Topic |
|---|---|
| `organisationseinheiten_MOCK.csv` | `organisationseinheiten_mock` |
| `leiter_MOCK.csv` | `leiter_mock` |
| `stellvertreter_MOCK.csv` | `stellvertretende_mock` |
| `beauftragte_MOCK.csv` | `beauftragte_mock` |

- **No script for this.** It was a one-time upload, so the project has none.
- **`test_data/mock_upload_ids.json`** holds the fact and topic ids. Keep it:
  it is the only record of which facts are mock data, and since it is not in
  git, this local copy is the only one.
- **The uploader ignores the mock facts.** They are not in
  `kb_facts_state.json`, so `uploader.py --upload` and `--delete` never touch
  them.
- **To remove the mock data**, delete each fact id from
  `mock_upload_ids.json` (`DELETE …/knowledgebases/<id>/facts/<fact_id>`),
  then remove the four empty `_mock` topics in aigateway.eu.

### tests/

These are scripts you run by hand against the real knowledge base (not a
pytest suite). Run them from the project folder; they read `../.env`.

| Script | What it does | Changes the KB? |
|---|---|---|
| `smoke_test.py` | Checks the key and the knowledge base, then creates, reads and deletes one test fact | No, it cleans up after itself |
| `split_test.py` | Offline checks of the splitting rules above, on made-up files built from `Files/` | No, makes no API calls |
| `upload_test.py <file>…` | Uploads files through the v2 **files** endpoint (server-side chunking, 500 characters); ids are logged to `tests/upload_log.json` | **Yes**: remove with `delete_test.py` |
| `delete_test.py <file_id>` | Deletes a file uploaded with `upload_test.py` | Yes, deletes |
| `facts_limit_test.py <chars>` | Posts one fact of the given length to see whether it is accepted | **Yes** if it is accepted |
| `facts_limit_search.py` | Binary-searches the exact token limit of a fact; deletes every fact it creates | No |

`sample.txt` is a small file for trying out `upload_test.py`.

## Working with Git

- **Never committed:** `.env` (API keys), `.venv/`, the real CSV export in
  `Files/` (customer data) and `test_data/` (mock data). The repository contains only an empty
  `Files/` folder. Copy the export into it on each machine.
- **Committed:** `kb_facts_state.json`, so everyone who runs the uploader
  replaces the same facts. After every `--upload` or `--delete`, commit and
  push the updated file right away. Before uploading, pull first. Two people
  uploading from different copies of the state file leave duplicate facts
  behind.

## Notes

- API used: `https://aigateway.eu/api/knowledge/base/v1/knowledgebases/<id>/facts` and `/topics`.
- A fact goes into a topic through `topic_id`. The API silently ignores a topic *name*.
- Each fact is sent in its own request, because the API returns the ids of a
  multi-fact request in no particular order.
- Token counts use `tiktoken` (`cl100k_base`). On first use it downloads the
  encoding, so the first run needs internet access.
