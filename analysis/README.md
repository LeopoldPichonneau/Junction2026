# analysis/ — Analysis (Maël)

Find the suspicious edits in the history of Finnish Wikipedia, fetch the pictures involved, then have Nemotron
investigate them. Everything runs **from the repository root**, with Python 3.12 and
`python -m pip install pyarrow httpx`. The scripts read `.env` at the root (Verda key, address, User-Agent).

## The commands, in order

| Order | Command | Reads | Writes (in `data/exchange/`) | Duration (file 01) |
|---|---|---|---|---|
| 1 | `python analysis/find_candidates.py data/versions-01.parquet` | parquet | `candidates.jsonl` (format: `docs/TECH.md`, section 15.1) | ≈ 4-5 min |
| 2 | `python analysis/fetch_images.py` | `candidates.jsonl` | `images.jsonl` + fills `thumb_url`, `author`, `license` in `candidates.jsonl` | ≈ 1 min |
| 3 | `python analysis/run_nemotron.py --limit 10` | `candidates.jsonl` | `analysis.jsonl` (format: section 15.2) | 1-3 s per case |
| 4 | `python analysis/insights.py data/versions-01.parquet` | `analysis.jsonl` + parquet | `insights.json` (time online by how closely the article is watched, repeat accounts, new accounts, bots set aside) + `case-durations.jsonl` (one suspicious case per line) | ≈ 3-5 min |
| 5 | `python analysis/term_timeline.py data/versions-01.parquet` | parquet | `term-timeline.json`: month by month, the names of the 1918 war (neutral / White side / Red side) in article 1150 and in all articles | ≈ 1 min |
| 6 | `python analysis/still_online.py data/versions-01.parquet` | parquet | `still-online.json`: the partisan terms still present in the latest version of each article, with their sentence and since when (list **to re-read**, many uses are legitimate: book titles, quotations) | ≈ 1 min |
| 7 | `python analysis/cloudinary_cards.py --archive` (Cloudinary keys in `.env`) | `candidates.jsonl`, `decisions.jsonl`, `images.jsonl`, `data/versions-*.parquet` | `cloudinary.jsonl`: for each published picture case, the picture of the time (and, if it was replaced, the one before) sent to Cloudinary with its evidence as metadata (`rev_id`, article, date, side, caption, author, license) and its `phash` fingerprint. The shared settings are in the `timeproof-evidence` preset | 1 min |
| 7b | `python analysis/cloudinary_cards.py --compare` (no file sent: the cloud name is enough) | `analysis/demo_cases.json`, `candidates.jsonl`, `decisions.jsonl`, `cloudinary.jsonl` | one line per archived picture case that has a picture before and a picture after: `before_url` / `after_url` (both sides of the slider, at the same size and framing, with the caption of the time), `archived_url`, `author`, `license` | < 1 min |
| 8 | `python analysis/english_titles.py data/versions-*.parquet` | the parquet files | `titles-en.jsonl`: the English title of each article that has an equivalent on English Wikipedia (Wikipedia's interlanguage links, never machine translation). Used to search for an article in English in the Time machine | 10 min |
| — | `python analysis/check_nemotron.py` | `.env` | nothing: says whether the Nemotron server answers | < 10 min |

- Several files at once: `python analysis/find_candidates.py data/versions-01.parquet data/versions-02.parquet …`
- A single article to test: `--page-id 1150` (steps 1 and 2), `--rev-id 24234965` (step 3).
- **The files in `data/` are never in Git**: everyone regenerates them with these commands (or receives them through Discord).

## Mock mode

With `USE_MOCK=true` in `.env`, no request is sent: `fetch_images.py` writes `images-mock.jsonl` without touching
`candidates.jsonl`, and `run_nemotron.py` writes `analysis-mock.jsonl`. Fake data never mixes with real data.

## What each step does

**1. `find_candidates.py`** compares each version of an article with the previous one.
- It ignores: the creation of the article, reverts (same `sha1` as an earlier version), edits that change nothing,
  minor edits and declared bots (name ending in "bot"). They still serve as the "previous version" for the next
  comparison.
- `kind` (one line per `rev_id`, the strongest signal wins): `image` if a caption changes or a picture is
  replaced → `sources` if the number of `<ref>` goes down → `framing` if the watched words of 1918 change
  (vapaussota, sisällissota, kansalaissota, luokkasota, punakapina, veljessota, all inflected forms) → `image` for a
  picture added or removed. `image` and `refs_removed` are filled whenever they exist, whatever the `kind`.
- Captions: split at `|` outside `[[links]]`, display options set aside (`thumb`, `pienoiskuva`, `250px`…),
  changes of punctuation, capitals or spaces ignored. Only the text **shown under the picture** counts
  (with `thumb`, `frame`, `pienoiskuva`…): without these options it is only a hover text.
- `added` / `removed`: the changed words, paragraph by paragraph, passages separated by " … ", cut at 1,500 characters.
- `account_hash` = `sha256(user)[:16]`, same formula as `decision/`. Account names and IP addresses are also removed
  from the `comment` field.
- `user_is_new` = the edit happens less than 7 days after the first edit of this account **in the input files**
  (not the real creation date of the account). Always `false` for an IP or a temporary account.
- Not done yet: coordination (the same text pushed by several accounts on several articles).

**2. `fetch_images.py`** asks the Wikipedia API (batches of 50, User-Agent from `.env`) for the thumbnail (800 px), the
author and the license of each picture. Files already in `images.jsonl` are not asked again. If the author is missing
(common for old public-domain photos), the "Credit" field is used.
The same file name can show a different picture today than at the time (new version, or a local file deleted then
replaced by a Commons file of the same name): all versions are kept, and each candidate gets the thumbnail of
**the version online on the day of the edit** (`image.version_timestamp`). If there was none yet, `thumb_url`,
`author` and `license` are `null`: neither the site nor Nemotron may show today's picture.

**3. `run_nemotron.py`** sends each candidate to Nemotron (text + thumbnail if there is one). Order: changed
captions, replaced pictures, sources, framing, added/removed pictures; article 1150 first in each group.
`--limit` is required (no mass launch by mistake), 2 calls at once by default, 4 at most (shared server). Each answer
is written as soon as it arrives; on restart, the `rev_id`s already present are skipped. The script stops after
10 failures in a row. The thumbnails are downloaded by the script and sent **inside the message**: when the server
fetched them itself from Wikimedia, half of the calls with a picture failed (`NEMOTRON_IMAGE_AS_DATA=false` in `.env`
to go back to links). Current instructions: v4 (obvious vandalism is not "suspicious"). `synthetic`, `account_hash`
and the ids are not sent to the model.

## Fields added to the formats (to report to Léopold for the import)

- `candidates.jsonl`, in `image`: `author`, `license`, `version_timestamp` (filled by step 2; the site needs them).
- `analysis.jsonl`, in `nemotron`: `model` (`model` column of the `analysis` table) and `seconds` (duration of the call).
- New file `images.jsonl`: `file`, `found`, `thumb_url`, `versions` (date + thumbnail of each version),
  `description_url` (Commons page), `author`, `credit`, `license`, `license_url`.
- Known limit: for a `replaced` picture, only the **new** file is kept (`file`).

## Status on Saturday 14 Nov, 13:30 (Helsinki time)

- Steps 1 and 2 done on file 01: 5,658 candidates (3,661 image, 1,519 sources, 478 framing), 1,872 pictures
  found out of 2,312 (the others were deleted from Wikipedia); 3,103 candidates have the thumbnail of the time.
- Step 3 ready and tested in mock mode, not yet run for real. **The Nemotron server is very slow**: around 14:15,
  1 call took 219 s, then 22 to 27 s per call (against 1-2 s on Friday). It is not down, it is busy: the scripts now
  wait up to 5 min. At this pace, ≈ 2 to 3 cases per minute with 2 calls at once: the cases must be chosen with care
  (`--limit`, priority order), not all sent.
- Without a key or with a wrong key, the server answers "404 page not found" at once: this is **not** the sign of an
  outage, only of a missing key. Our settings are identical to the official configuration (address, model, key).
- One real case spotted (not yet investigated by Nemotron): rev 24234965 of 12 Sept 2026, article 1150, "Sisällissota"
  replaced by "Vapaussota" in several places, including the first sentence; undone by the next edit.
- Backup planned but not used (no key): `NEMOTRON_PROVIDER=nvidia` + `NVIDIA_API_KEY` in `.env`
  (address and model from `docs/TECH.md`, section 2, limited to 35 calls/min).
- On Windows without a time zone database, `to_pylist()` on a `timestamp` column with a time zone crashes
  ("zoneinfo module or pytz package must be installed"): `find_candidates.py` converts the dates to UTC without a zone.
