# TimeProof — technical reference

> Everything needed to code one's part without asking again. The JSONL formats exchanged between modules are in [section 15](#15-exchange-formats-jsonl).
> **Tested** = checked by the team on the Friday evening. The rest is a team decision, to apply as written.

## Contents
1. [Stack and file tree](#1-stack-and-file-tree)
2. [Environment variables](#2-environment-variables)
3. [The data](#3-the-data)
4. [Database schema](#4-database-schema)
5. [Loading the history with the real dates (Léopold)](#5-loading-the-history-with-the-real-dates-léopold)
6. [Reading the wikitext: pictures, sources, words, coordination (Maël)](#6-reading-the-wikitext-pictures-sources-words-coordination-maël)
7. [Calling Nemotron (Maël)](#7-calling-nemotron-maël)
8. [Calling Gemini (Nathanaël)](#8-calling-gemini-nathanaël)
9. [The Wikimedia APIs (everyone)](#9-the-wikimedia-apis-everyone)
10. [Account patterns, exposure, reliability (Nathanaël)](#10-account-patterns-exposure-reliability-nathanaël)
11. [The site's API: response formats (Léopold → Eléa)](#11-the-sites-api-response-formats-léopold--eléa)
12. [The Lens (Eléa)](#12-the-lens-eléa)
13. [Deployment: VPS + CRACI (Léopold, Eléa)](#13-deployment-vps--craci-léopold-eléa)
14. [Pitfalls already met](#14-pitfalls-already-met)
15. [Exchange formats (JSONL)](#15-exchange-formats-jsonl)

---

## 1. Stack and file tree

| Layer | Choice | Why |
|---|---|---|
| Database | **MariaDB `mariadb:lts`** (Docker), **system-versioned** tables | The heart of the MariaDB challenge; tested on 12.3.3 |
| Server | **Python 3.12 + FastAPI + uvicorn**, database access with **PyMySQL** | Simple, everyone reads Python |
| Analysis scripts | **Python 3.12 + pyarrow + httpx** | Read the parquet files, call the APIs |
| Site | **Plain HTML + CSS + JS**, no framework, served **by FastAPI** as static files | No build step, no extra server |
| Models | **Nemotron 3.5 Super VL** (server provided, hosted at Verda) + **Gemini** (Google API) | Both speak the OpenAI format |
| Hosting | **Hostinger VPS KVM 2** (2 vCPU, 8 GB RAM, 100 GB disk), Docker Compose | Required by the Hostinger challenge |
| CI/CD | **CRACI** (`runs-on: craci`): checks and deploys on every push to `main` | CRACI tech challenge |

```
TimeProof/
├── docs/                     these documents
├── docker-compose.yml        Léopold: db + server services
├── .env.example              Léopold: list of variables, without values
├── .gitignore                Léopold
├── db/schema.sql             Léopold: section 4
├── server/                   Léopold: FastAPI (main.py), load_versions.py, import_jsonl.py, watch.py, wikitext.py
├── analysis/                 Maël: find_candidates.py, fetch_images.py, run_nemotron.py
├── decision/                 Nathanaël: decide.py, accounts.py, exposure.py, quality.py
├── web/                      Eléa: index.html, case.html, timemachine.html, quality.html, style.css, app.js, mock/*.json
├── lens/                     Eléa: build_bookmarklet.py, lens.js, bookmarklet.txt
├── .github/workflows/        Eléa: deploy.yml (CRACI)
└── data/                     NEVER in git: versions-XX.parquet, exchange/*.jsonl
```

**Ports**: the server listens on 8000 in its container, published on **80** on the VPS (8000 locally). **MariaDB is never published** (no `ports:` for `db`).

**The site is served by FastAPI**: the `/api/...` routes first, then `app.mount("/", StaticFiles(directory="web", html=True))`. The `web/` folder is mounted in the container.

## 2. Environment variables

`.env` file at the root (never committed; `.env.example` without values is committed). Keys travel **by private Discord message**.

```
# Database
DB_HOST=db
DB_PORT=3306
DB_NAME=timeproof
DB_USER=timeproof
DB_PASSWORD=
DB_ROOT_PASSWORD=
APP_PORT=8000                 # 80 on the VPS

# true = no key needed, external calls return simulated data in the right format
USE_MOCK=true

# Nemotron (server provided, hosted at Verda) — tested
VERDA_INFERENCE_KEY=
NEMOTRON_BASE_URL=https://containers.datacrunch.io/nemotron-3-5-super-vl-b300/v1
NEMOTRON_MODEL=nemotron-3.5-super-vl

# Gemini — key from aistudio.google.com; copy a "Flash" model id from AI Studio
GEMINI_API_KEY=
GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
GEMINI_MODEL=

# Sent to the Wikimedia APIs (without it: HTTP 429) — tested
WIKI_USER_AGENT=TimeProofBot/0.1 (https://hackjunction.com; Junction 2026 hackathon prototype)
```

Backup key if the Nemotron server goes down: an `nvapi-…` key from build.nvidia.com, address `https://integrate.api.nvidia.com/v1`, model `nvidia/nemotron-3.5-super-vl-120b-a12b` (≈ 40 calls/min per key). **The Verda key does not work at that address** (error 401, tested).

## 3. The data

Source: [MariaDB/mariadb-wikipedia-datasets](https://github.com/MariaDB/mariadb-wikipedia-datasets), set **M** ("every version").

- 16 files: `https://github.com/MariaDB/mariadb-wikipedia-datasets/releases/download/m-2026-10/versions-01.parquet` … `versions-16.parquet` (315 MB in total; `SHA256SUMS` in the same release).
- File 01 is 20 MB and holds **281 articles, 103,607 versions**, including *Suomen sisällissota* (`page_id` 1150, 3,357 versions), *Talvisota* (1256), *Urho Kekkonen* (1275), *Carl Gustaf Emil Mannerheim* (6021).
- Rows are ordered **by article, from the oldest to the most recent**.

| Column | Type | Content |
|---|---|---|
| `page_id` | uint32 | Wikipedia id of the article |
| `title` | string | Title **at this version** (articles are sometimes renamed) |
| `rev_id` | uint32 | Id of the version (`https://fi.wikipedia.org/?oldid=<rev_id>`) |
| `parent_id` | uint32 | Previous version |
| `timestamp` | timestamp[ms, tz=UTC] | Date of the edit (UTC) |
| `user` | string | Account name, IP address or temporary account `~2026-…` |
| `anonymous` | bool | Anonymous edit (19% of versions) |
| `comment` | string | Edit summary |
| `minor` | bool | Marked "minor" |
| `sha1` | string | Fingerprint of the text: **same sha1 = same text** (used to spot reverts) |
| `bytes` | uint32 | Size of the text |
| `text` | string | **Raw wikitext** (no clean Markdown for old versions) |

**Reading a parquet file without filling the memory** (the text of file 01 is about 760 MB):
```python
import pyarrow.parquet as pq
pf = pq.ParquetFile("data/versions-01.parquet")
for batch in pf.iter_batches(batch_size=2000):            # in batches
    for row in batch.to_pylist():
        ...
# or only some articles:
table = pq.read_table("data/versions-01.parquet", filters=[("page_id", "in", [1150, 1256])])
```

**A revert** is a version whose `sha1` equals that of an **earlier version of the same article**, but differs from that of the version just before.

Measured on Friday on file 01, reverts excluded:
- 5,771 versions change at least one picture;
- 2,315 changed captions and 1,442 picture replacements;
- 1,605 versions remove references (11,421 references removed);
- 274 articles out of 281 have at least one picture change.

## 4. Database schema

Content of `db/schema.sql` (Léopold). The `article` table follows the schema of the official MariaDB example ([mariadb-system-versioning-wikipedia](https://github.com/MariaDB/mariadb-system-versioning-wikipedia), MIT license, to credit in the README).

```sql
-- One row per article = what Wikipedia shows today; each past version
-- is a history row, written with the real Wikipedia date.
CREATE TABLE IF NOT EXISTS article (
  page_id    INT UNSIGNED NOT NULL,
  title      VARCHAR(255) NOT NULL,
  rev_id     INT UNSIGNED NOT NULL,
  parent_id  INT UNSIGNED,
  user       VARCHAR(255),             -- stays in the database; never returned by the public API
  anonymous  BOOL NOT NULL DEFAULT 0,
  comment    TEXT,
  minor      BOOL NOT NULL DEFAULT 0,
  sha1       CHAR(31),
  len        INT UNSIGNED,
  text       MEDIUMTEXT COMPRESSED NOT NULL,
  row_start  TIMESTAMP(6) GENERATED ALWAYS AS ROW START INVISIBLE,
  row_end    TIMESTAMP(6) GENERATED ALWAYS AS ROW END INVISIBLE,
  PERIOD FOR SYSTEM_TIME (row_start, row_end),
  PRIMARY KEY (page_id),
  KEY (sha1), KEY (rev_id), KEY (user),
  KEY start_key (page_id, row_start)   -- makes old "as of" dates fast
) CHARACTER SET utf8mb4 WITH SYSTEM VERSIONING;

-- Imported from data/exchange/*.jsonl by server/import_jsonl.py
CREATE TABLE IF NOT EXISTS candidate (
  rev_id INT UNSIGNED PRIMARY KEY, page_id INT UNSIGNED NOT NULL, title VARCHAR(255),
  kind ENUM('framing','image','sources','coordination') NOT NULL,
  edited_at DATETIME(6) NOT NULL, account_hash CHAR(16), synthetic BOOL NOT NULL DEFAULT 0,
  data JSON NOT NULL,                  -- the full JSONL line
  KEY (page_id), KEY (kind)
) CHARACTER SET utf8mb4;

CREATE TABLE IF NOT EXISTS analysis (
  rev_id INT UNSIGNED PRIMARY KEY, model VARCHAR(120) NOT NULL,
  suspicious BOOL, data JSON NOT NULL
) CHARACTER SET utf8mb4;

-- Versioned: we can prove when a case was published or withdrawn
CREATE TABLE IF NOT EXISTS decision (
  rev_id INT UNSIGNED PRIMARY KEY,
  decision ENUM('flag','dismiss','human_review') NOT NULL,
  publish BOOL NOT NULL DEFAULT 0, confidence FLOAT,
  days_live FLOAT, readers_est INT UNSIGNED, still_online BOOL,
  data JSON NOT NULL
) CHARACTER SET utf8mb4 WITH SYSTEM VERSIONING;

CREATE TABLE IF NOT EXISTS account_profile (
  account_hash CHAR(16) PRIMARY KEY,
  kind ENUM('declared_bot','bot_like','throwaway','single_purpose','normal') NOT NULL,
  score FLOAT, data JSON NOT NULL
) CHARACTER SET utf8mb4;
```

For the import, one JSONL line gives one table row: the columns are used to filter and sort, the full line goes into `data` (JSON). The reliability figures do not go into the database: Nathanaël writes `data/exchange/quality.json`, which the API returns as it is.

## 5. Loading the history with the real dates (Léopold)

**The problem**: a system-versioned table dates each row **at the time of the insert**. With a normal insert, every version would be dated Saturday, and "as of 2015" would return nothing.

**The solution** (method of the official MariaDB example, tested on Friday): write `row_start` and `row_end` ourselves.

```sql
SET time_zone = '+00:00';                       -- Wikipedia is in UTC
SET system_versioning_insert_history = 1;      -- allows writing row_start/row_end
-- every version except the last: start = its date, end = the date of the next version
INSERT INTO article (page_id, title, rev_id, parent_id, user, anonymous, comment, minor, sha1, len, text, row_start, row_end)
VALUES (...);
-- the current version: only the start (MariaDB sets the end to "still current")
INSERT INTO article (page_id, title, rev_id, parent_id, user, anonymous, comment, minor, sha1, len, text, row_start)
VALUES (...);
SET system_versioning_insert_history = 0;
```

The algorithm, per article:
1. Sort the versions by (`timestamp`, `rev_id`).
2. If two versions share the same second, add **1 microsecond** to the second one, otherwise a version would end where it starts.
3. Insert in **batches of at most ~8 MB of text** (not by row count) and start MariaDB with `--max-allowed-packet=256M`.
4. One transaction per article; if the article is already in the database, move on to the next one, so the load can be restarted after a crash.

**Measured on Friday**: 3,357 versions of article 1150 in **61 s**, peak of about **1.3 GB** of RAM. The whole M set is **estimated at 4–6 h** (extrapolation, maybe more on 2 vCPU) → to run **in the background** on the VPS, file by file, with a log.

**The script runs INSIDE the `server` container**. On the VPS itself the database cannot be reached (`db` only exists in the Docker network) and `pyarrow` is not installed. The `server/` folder is copied into `/app` in the container, and the data is mounted on `/data`:
```bash
# 1. first check that the tables exist
docker compose exec -T db mariadb -u timeproof -p"$DB_PASSWORD" timeproof -e "SHOW TABLES"
# 2. load the 16 files in the background
nohup bash -c 'for i in $(seq -w 1 16); do docker compose exec -T server python load_versions.py /data/versions-$i.parquet; done' > load.log 2>&1 &
tail -f load.log
```

**Creating the tables**: `db/schema.sql` is mounted in the `db` service on `/docker-entrypoint-initdb.d/`. MariaDB runs it **only once, on first start, when the volume is empty**. To change the schema later: `docker compose down -v` (erases the database!) or an `ALTER TABLE` by hand (on a versioned table: `SET system_versioning_alter_history = KEEP;` first).

**Key queries**:
```sql
-- the article as it stood on 1 June 2015 (date AND time required)
SELECT title, rev_id, row_start, text FROM article
  FOR SYSTEM_TIME AS OF TIMESTAMP '2015-06-01 00:00:00' WHERE page_id = 1150;
-- every version, with the reverts
SELECT rev_id, row_start, sha1 <> LAG(sha1) OVER (ORDER BY row_start)
         AND MIN(row_start) OVER (PARTITION BY sha1) < row_start AS is_revert
FROM article FOR SYSTEM_TIME ALL WHERE page_id = 1150 ORDER BY row_start;
```

**Test that must pass**: `as_of=2006-01-01` on 1150 returns a version from 2005 (checked on Friday: rev 472288, 11 Oct 2005).

**After the load**, a new version (live watch) is added with a plain `UPDATE article SET … WHERE page_id = …`: MariaDB archives the old version by itself.

## 6. Reading the wikitext: pictures, sources, words, coordination (Maël)

**Always analyse the raw wikitext BEFORE cleaning it**, because cleaning erases the pictures and the references.

**Pictures**: links `[[Tiedosto:Name.jpg|thumb|…|Caption]]` (prefixes: `Tiedosto`, `Kuva`, `File`, `Image`). The caption is the **last** piece after `|`. It can contain `[[links]]`, so we count the brackets instead of using a simple regular expression:
```python
import re
PREFIX = re.compile(r"\[\[\s*(Tiedosto|Kuva|File|Image)\s*:", re.I)

def images(text: str) -> dict[str, str]:
    """{file_name: caption}"""
    out, i = {}, 0
    while (m := PREFIX.search(text, i)):
        depth, j = 0, m.start()
        while j < len(text) - 1:
            if text.startswith("[[", j): depth += 1; j += 2
            elif text.startswith("]]", j):
                depth -= 1; j += 2
                if depth == 0: break
            else: j += 1
        parts = text[m.end():j - 2].split("|")
        name = parts[0].strip().replace("_", " ")
        if name:
            out[name[:1].upper() + name[1:]] = parts[-1].strip() if len(parts) > 1 else ""
        i = j
    return out
```
Compare with the previous version: file added, removed, replaced, or **caption changed** (same file, different caption, not empty on either side). Limit: pictures placed inside templates (`{{Infobox …|kuva=…}}`) are not seen.

**Sources**: `len(re.findall(r"<ref[\s>]", text, re.I))`. If the count goes down → `kind: "sources"`.

**Cleaning to compare words**: remove the `<!-- -->` comments, the `<ref>…</ref>`, the `{| … |}` tables, the `{{…}}` templates (in a loop, because they nest), the file links; replace `[[target|text]]` with `text`, and remove `'''` and `''`. Then compare **word by word**, only in the paragraphs that changed (`difflib.SequenceMatcher` on the word lists), otherwise a fixed typo counts as a whole paragraph.

**Watched words for framing drift** (1918, to extend with Gemini's help for other themes): `vapaussota` (war of liberation), `sisällissota` (civil war), `kansalaissota`, `luokkasota` (class war), `punakapina` (red rebellion), `veljessota` (fratricidal war). The signal is the **ratio** between terms over time, not the raw count. Measured on 1150: *sisällissota* / *vapaussota* goes from about 1:1 (2005) to about 3:1 (2026).

**Coordination (simple version, no model)**:
1. For each added text of at least 20 words: lower case, no punctuation, cut into runs of 8 consecutive words, each turned into a fingerprint (`hash`).
2. Group them: the same run added by **at least 2 different accounts**, on **at least 2 different articles**, within **14 days** → `kind: "coordination"`.
3. Reverts, minor edits and official bots are ignored.

**Priorities for Nemotron** (do not launch 100,000 calls): first the changed captions and picture replacements of sensitive articles (1918, wars, presidents, Karelia), then coordination, then removed sources, then drift.

**All reverts and minor edits are excluded** from the sorting. The fingerprint of an account: `hashlib.sha256(user.encode()).hexdigest()[:16]`.

## 7. Calling Nemotron (Maël)

**Tested on Friday**: it understands Finnish (it spotted "civil war" → "war of liberation" and explained the change of framing), describes a photo and exposed a false caption. Duration: **1.3 s** for text, **2.3 s** with a picture. The picture can be sent **by its link** (Wikimedia thumbnail).

```python
import json, os, httpx

def ask_nemotron(prompt: str, image_url: str | None = None) -> dict:
    content = prompt if not image_url else [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": image_url}},
    ]
    r = httpx.post(
        os.environ["NEMOTRON_BASE_URL"] + "/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['VERDA_INFERENCE_KEY']}"},
        json={"model": os.environ["NEMOTRON_MODEL"], "temperature": 0.6, "top_p": 0.95,
              "max_tokens": 1500, "messages": [{"role": "user", "content": content}]},
        timeout=180,
    )
    r.raise_for_status()
    text = r.json()["choices"][0]["message"].get("content") or ""   # any reasoning is in "reasoning_content"
    return json.loads(text[text.find("{"): text.rfind("}") + 1])    # keep only the JSON
```

The investigator's instructions are in `analysis/run_nemotron.py` (`INVESTIGATOR_PROMPT`). The user message holds the `candidates.jsonl` line (added/removed text, captions, account in anonymous form).

**Limits**: the server is **shared** between teams (unknown call limit → ask Verda on Discord), so no more than 2 to 4 calls at once without their agreement. Write each result into `analysis.jsonl` as soon as it arrives, and skip the `rev_id`s already done on restart.

## 8. Calling Gemini (Nathanaël)

Same format as Nemotron (Google's OpenAI compatibility, checked on Friday in their documentation):
```python
r = httpx.post(os.environ["GEMINI_BASE_URL"] + "chat/completions",       # the address already ends with "/"
               headers={"Authorization": f"Bearer {os.environ['GEMINI_API_KEY']}"},
               json={"model": os.environ["GEMINI_MODEL"], "temperature": 0.2,
                     "messages": [{"role": "system", "content": DECIDER_PROMPT},
                                  {"role": "user", "content": json.dumps(analysis_line, ensure_ascii=False)}]},
               timeout=120)
```

The decider's instructions are in `decision/decide.py` (`DECIDER_PROMPT`).

**Two-model rule, applied in the code and not left to the model**:
- `flag` if Gemini says `flag` **and** Nemotron says `suspicious: true`;
- `dismiss` if both say "not suspicious";
- `human_review` in every other case, **and for any answer outside these 3 values**;
- `publish` is only possible for a `flag`.

**Cost**: call Gemini only on the cases Nemotron finds "suspicious", plus a sample of about 50 non-suspicious ones (to measure disagreements). **All the others** (Nemotron says "not suspicious" and the case is not drawn) get `dismiss` **by rule**, without a call to Gemini, with `"decided_by": "rule"` in the line.

## 9. The Wikimedia APIs (everyone)

**Always** send the header `User-Agent: $WIKI_USER_AGENT`. With a generic identifier we got **error 429** on Friday. No more than a few requests per second.

| Need | Address |
|---|---|
| Thumbnail + author + license of a picture (≤ 50 titles per request) | `https://fi.wikipedia.org/w/api.php?action=query&format=json&prop=imageinfo&iiprop=url\|extmetadata&iiurlwidth=800&titles=Tiedosto:A.jpg\|Tiedosto:B.jpg` → `thumburl`, `extmetadata.Artist`, `extmetadata.LicenseShortName` |
| Summary + main picture of an article | `https://fi.wikipedia.org/api/rest_v1/page/summary/Suomen_sisällissota` |
| Views per day (since 07/2015) | `https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/fi.wikipedia/all-access/user/<Title_with_underscores>/daily/<YYYYMMDD>/<YYYYMMDD>` |
| New versions of an article (live watch) — **to check on the first call** | `https://fi.wikipedia.org/w/api.php?action=query&format=json&prop=revisions&pageids=<id>&rvdir=newer&rvstart=<ISO date>&rvlimit=50&rvprop=ids\|timestamp\|user\|comment\|sha1\|size\|flags\|content&rvslots=main` (one article per request) |
| List of official bots — **to check on the first call** | `https://fi.wikipedia.org/w/api.php?action=query&format=json&list=allusers&augroup=bot&aulimit=500` |
| Links for the site | version: `https://fi.wikipedia.org/?oldid=<rev_id>` · difference with the previous one: `https://fi.wikipedia.org/w/index.php?diff=prev&oldid=<rev_id>` |

Checked on Friday: the page views API answers for *Suomen_sisällissota* (136 months, 1,874,510 views from July 2015 to October 2026).

## 10. Account patterns, exposure, reliability (Nathanaël)

**Data source: the parquet files, not the database.** The full load into MariaDB takes hours: account patterns and exposure are computed directly from `data/versions-XX.parquet` (same reading as section 3).

**Account patterns** (`accounts.jsonl`, no model, on the parquet files):

| `kind` | Starting rule (to tune by looking at the data) |
|---|---|
| `declared_bot` | name in the list of official bots (section 9) or ending in "bot" → **benign, excluded from everything** |
| `bot_like` | ≥ 20 edits in 1 h, or very regular intervals (standard deviation of the intervals < 10% of their mean) |
| `throwaway` | active ≤ 7 days in total, ≥ 3 sensitive articles touched |
| `single_purpose` | ≥ 10 edits, all on ≤ 2 articles of the same theme |
| `normal` | the rest |

Add the **revert rate** (share of its edits reverted by another account) to `reasons`. Every account that is not normal must have `reasons` **a human can read**.

**Exposure** of a case:
- **time online**: from the date of the suspicious version to the date of the **first later version** where the suspicious content is gone (for a picture: the caption or the file changes; for text: the added words are no longer there). If the content is still there: `still_online: true`, duration up to today;
- **estimated readers**: sum of the views per day over the period (section 9), with the **title of the time**. `null` if the period is before July 2015, and it is an **upper bound** (views of the whole article): we always write it with "≈".

**Reliability** → `data/exchange/quality.json`:
```json
{"synthetic_campaign": {"planted": 13, "caught": 11},
 "manual_review": {"reviewed": 20, "correct": 17},
 "downgraded_by_two_model_rule": 42,
 "declared_bots_excluded": 398,
 "suspicious_accounts": 27,
 "notes": {"synthetic_campaign": "13 fake edits planted in a test copy, never shown publicly"}}
```
The test campaign is generated by `decision/quality.py` as `candidates.jsonl` lines with `"synthetic": true`. It goes through the same chain, and **it is filtered out of every public response**.

## 11. The site's API: response formats (Léopold → Eléa)

Eléa creates `web/mock/*.json` files in **exactly** these formats. **No public response contains `user`.**

```jsonc
// GET /api/stats
{"articles": 19742, "versions": 862076, "candidates": 0, "analysed": 0, "published": 0, "readers_exposed_est": 0}

// GET /api/cases            (published, sorted by readers_est then confidence)   ?since=7d for the live watch
[{"rev_id": 23498098, "page_id": 1150, "title": "Suomen sisällissota", "date": "2019-03-02",
  "signal_type": "image", "headline_en": "…", "summary_en": "…", "confidence": 0.8,
  "days_live": 412, "readers_est": 38000, "still_online": false, "image_thumb": "https://upload.wikimedia.org/…"}]

// GET /api/cases/{rev_id}   (evidence page)
{"rev_id": 23498098, "page_id": 1150, "title": "…", "date": "2019-03-02", "signal_type": "image",
 "headline_en": "…", "summary_en": "…", "confidence": 0.8,
 "added": "…", "removed": "…",
 "image": {"file": "…", "thumb_url": "…", "caption_old": "…", "caption_new": "…", "author": "…", "license": "CC BY-SA 4.0"},
 "investigator": {"model": "nemotron-3.5-super-vl", "report": "…", "signals": ["…"],
                  "image_findings": {"what_it_shows": "…", "caption_matches": false}},
 "decider": {"model": "gemini-…", "decision": "flag", "explanation": "…"},
 "exposure": {"live_from": "2019-03-02", "live_until": "2020-04-17", "days_live": 412, "readers_est": 38000, "still_online": false},
 "account": {"kind": "throwaway", "reasons": ["…"]},
 "links": {"version": "https://fi.wikipedia.org/?oldid=23498098",
           "diff": "https://fi.wikipedia.org/w/index.php?diff=prev&oldid=23498098"}}

// GET /api/quality          = the content of data/exchange/quality.json

// GET /api/articles
[{"page_id": 1150, "title": "Suomen sisällissota", "versions": 3357, "first_edit": "2003-08-26", "last_edit": "2026-09-12"}]

// GET /api/articles/{page_id}?as_of=2015-06-01      (cleaned text, no account name)
{"page_id": 1150, "title": "…", "rev_id": 14664523, "as_of": "2015-06-01", "saved_at": "2015-02-09T18:57:03Z", "text": "…"}

// GET /api/articles/{page_id}/timeline
[{"month": "2008-03", "edits": 12, "reverts": 2}]
```

`/api/articles` must not recompute a `GROUP BY` over 862,000 rows on every call: precompute it once at the end of the load, in a small table or a file.

## 12. The Lens (Eléa)

**Before building (2 minutes)**: check that a bookmark can act on Wikipedia. Create a bookmark whose address is:
```
javascript:(()=>{document.querySelectorAll('#mw-content-text img').forEach(i=>i.style.outline='4px solid red')})()
```
Open `https://fi.wikipedia.org/wiki/Suomen_sisällissota` and click the bookmark. If the pictures get a red outline, the method works. If not (page security), tell the team at once: plan B is a minimal browser extension loaded by hand in developer mode.

**Technical decision: the Lens does NOT call our server.** Wikipedia is on **HTTPS**, our VPS on **HTTP**: the browser **blocks** a call from an HTTPS page to an HTTP address ("mixed content").

**So**:
- `lens/build_bookmarklet.py` reads `analysis.jsonl` + `decisions.jsonl` (published cases of the **2-3 demo articles** only) and produces a small JSON of annotations;
- it **embeds it directly** in `lens/lens.js`, then generates `lens/bookmarklet.txt` (`javascript:(()=>{…})()`) to copy into a bookmark;
- on the Wikipedia page, the script finds:
  - **the pictures**, by their file name in the `src` attribute of the `<img>` elements;
  - **the passages**, by searching for the added text in the paragraphs (`document.querySelectorAll("#mw-content-text p")`);
- it outlines them (coloured outline) and shows a tooltip on hover: *"Caption changed 3 times since 2009 · online 412 days · ≈ 38,000 readers"*, with a link to the case page on our site (a plain link, allowed);
- keep the embedded JSON small (a few dozen annotations): a bookmark that is too long can be cut by the browser.

## 13. Deployment: VPS + CRACI (Léopold, Eléa)

**VPS (once, Léopold)**, as root:
```bash
curl -fsSL https://get.docker.com | sh            # official Docker install script
adduser --disabled-password deploy && usermod -aG docker deploy
ufw allow 22 && ufw allow 80 && ufw --force enable  # SSH + web only, never 3306
# paste the public deploy key into /home/deploy/.ssh/authorized_keys
```
Then, as `deploy`: create `~/timeproof/` with `.env` (real values, `APP_PORT=80`, `USE_MOCK=false`) and `data/`, download the 16 parquet files straight onto the VPS, then start the load (section 5).

**`docker-compose.yml`**:
- `db` service: `mariadb:lts`, variables `MARIADB_DATABASE` / `MARIADB_USER` / `MARIADB_PASSWORD` / `MARIADB_ROOT_PASSWORD` taken from `.env`, `command: --max-allowed-packet=256M`, persistent volume for `/var/lib/mysql`, volume `./db/schema.sql:/docker-entrypoint-initdb.d/01-schema.sql:ro`, healthcheck `healthcheck.sh --connect --innodb_initialized`, **no `ports:`**;
- `server` service: built from `server/` (`python:3.12-slim`, `WORKDIR /app`, `COPY . .`, `pip install fastapi uvicorn PyMySQL pyarrow httpx`), `env_file: .env`, `depends_on: db (service_healthy)`, `ports: "${APP_PORT}:8000"`, volumes `./web:/app/web:ro` and `./data:/data`, command `uvicorn main:app --host 0.0.0.0 --port 8000`.

**CRACI (Eléa, with Léopold)**:
1. platform.craci.com → create the organisation with the invitation code → Settings → Builds → install the GitHub app on the repository.
2. In the GitHub repository → Settings → Secrets → Actions: `VPS_HOST`, `VPS_USER` (`deploy`), `VPS_SSH_KEY` (private key).
3. `.github/workflows/deploy.yml`:
```yaml
name: deploy
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: craci
    steps:
      - uses: actions/checkout@v4
      - name: Check Python files compile
        run: for d in server analysis decision; do [ -d "$d" ] && python3 -m compileall -q "$d"; done; true
      - name: Ship to the VPS and restart
        env:
          VPS_HOST: ${{ secrets.VPS_HOST }}
          VPS_USER: ${{ secrets.VPS_USER }}
          VPS_SSH_KEY: ${{ secrets.VPS_SSH_KEY }}
        run: |
          mkdir -p ~/.ssh && printf '%s\n' "$VPS_SSH_KEY" > ~/.ssh/k && chmod 600 ~/.ssh/k
          ssh-keyscan -H "$VPS_HOST" >> ~/.ssh/known_hosts
          tar czf - --exclude=.git --exclude=data --exclude=.env . | ssh -i ~/.ssh/k "$VPS_USER@$VPS_HOST" "mkdir -p ~/timeproof && tar xzf - -C ~/timeproof"
          ssh -i ~/.ssh/k "$VPS_USER@$VPS_HOST" "cd ~/timeproof && docker compose up -d --build"
```
The deployment runs on the `Deploy` branch (not on `main`): see `.github/workflows/deploy.yml`. The live watch can be started by a second workflow with `on: schedule: - cron: "0 * * * *"`, which runs `server/watch.py` on the VPS through `ssh`.

## 14. Pitfalls already met

| Pitfall | Solution |
|---|---|
| Git Bash rewrites `/data/…` into a Windows path | Prefix with `MSYS_NO_PATHCONV=1` |
| The clock of some PCs is one hour ahead | Trust the Helsinki time of the phones |
| `TIMESTAMP ?` refuses a date alone | Write `'2015-06-01 00:00:00'` |
| Every version dated on the day of the load | `system_versioning_insert_history = 1` + `row_start`/`row_end` (section 5) |
| Error 429 from Wikimedia | Descriptive User-Agent (section 2) |
| Error 401 "Invalid JWT" with the Verda key | It only works at the Verda address, not at NVIDIA |
| A fixed typo counts as a whole paragraph | Compare word by word, in the changed paragraphs only |
| Pictures and references vanish during the analysis | Extract them **before** cleaning the wikitext |
| The model's answer has text around the JSON | Keep only from the first `{` to the last `}` |
| The title of an article changes over time | For the views, use the `title` of the version concerned |
| Lens blocked on Wikipedia | Data embedded in the bookmark, no network call (section 12) |

## 15. Exchange formats (JSONL)

The modules exchange **JSONL files** (one JSON object per line), kept in `data/exchange/`. The READMEs of
`analysis/` and `decision/` list the fields added since.

### 15.1 `candidates.jsonl` (written by `analysis/find_candidates.py`)
An edit worth investigating:
```json
{"rev_id": 23498098, "page_id": 1150, "title": "Suomen sisällissota", "timestamp": "2025-08-17T10:28:50Z",
 "kind": "image", "account_hash": "a3f9c2…", "user_is_new": true, "synthetic": false, "comment": "…",
 "added": "added words", "removed": "removed words",
 "image": {"change": "recaptioned", "file": "Jaakarit_vaasan_torilla.jpg",
           "caption_old": "…", "caption_new": "…", "thumb_url": "https://…"},
 "refs_removed": 0}
```
`kind` is one of: `"framing"`, `"image"`, `"sources"`, `"coordination"`. `image` is `null` when no picture is involved.

### 15.2 `analysis.jsonl` (written by `analysis/run_nemotron.py`)
The same line, plus Nemotron's report:
```json
{"rev_id": 23498098, "...": "...", "nemotron": {"suspicious": true, "signals": ["caption changed meaning"],
 "report": "3-6 sentences a human can check", "image_findings": {"what_it_shows": "…", "caption_matches": false}}}
```

### 15.3 `decisions.jsonl` (written by `decision/decide.py` and `decision/exposure.py`)
```json
{"rev_id": 23498098, "decision": "flag", "confidence": 0.8, "publish": true,
 "headline_en": "A 1918 photo caption changed meaning", "summary_en": "2-4 clear sentences",
 "exposure": {"live_from": "2019-03-02", "live_until": null, "days_live": 2450, "readers_est": 38000}}
```
- `decision`: `flag`, `dismiss` or `human_review`.
- **Rule**: `flag` only if Nemotron (`suspicious`) **and** Gemini agree, otherwise `human_review`.
- `readers_est` is `null` before July 2015.

### 15.4 `accounts.jsonl` (written by `decision/accounts.py`)
One account per line, computed **without a model** from the data files (author, date, anonymous, reverts):
```json
{"account_hash": "a3f9…", "kind": "bot_like", "declared_bot": false, "score": 0.82,
 "reasons": ["38 edits in 2 h at regular intervals", "edits 6 sensitive articles only", "71% of edits reverted"],
 "edits": 54, "articles": 6, "first_seen": "2024-03-02", "last_seen": "2024-03-09"}
```
- `kind`: `"declared_bot"` (official Wikipedia bot, **benign**), `"bot_like"`, `"throwaway"`, `"single_purpose"` (one theme only), `"normal"`.
- **No account name** in this file: we keep a fingerprint (`account_hash`).
