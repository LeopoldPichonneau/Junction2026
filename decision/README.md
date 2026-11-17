# decision/ — Decision & evidence (Nathanaël)

All scripts run **from the repository root**, with Python 3.12 and `pip install pyarrow httpx`.
They read `.env` at the root. With `USE_MOCK=true` (the default if `.env` does not exist), no key is needed and the
outputs go to `*.mock.jsonl` files, so they never pass as real data.
**For the real files the others expect, set `USE_MOCK=false` in `.env`** (+ `GEMINI_API_KEY`, `GEMINI_MODEL`),
and have the 16 `data/versions-XX.parquet` files (a single one only covers 281 articles).

| Order | Command | Reads | Writes (in `data/exchange/`) |
|---|---|---|---|
| 1 | `python decision/accounts.py` | `data/versions-*.parquet` | `accounts.jsonl` (format: `docs/TECH.md`, section 15.4) + `accounts_summary.json` → **to give to Maël** |
| 2 | `python decision/decide.py` | `analysis.jsonl` (Maël) | `decisions.jsonl` (format: section 15.3) |
| 3 | `python decision/exposure.py` (can run **before** Nemotron: it takes `candidates.jsonl` if `analysis.jsonl` does not exist yet) | the cases, parquet, page views API | `exposure.jsonl` (kept from one run to the next: only new cases are computed); after `decide.py`: `python decision/exposure.py --merge-only` adds `exposure` to `decisions.jsonl` |
| 4 | `python decision/quality.py campaign` | `candidates.jsonl` (real photos from different articles) | `synthetic_candidates.jsonl` (10 texts + 3 misleading captions) → **to give to Maël** |
| 5 | `python decision/quality.py review-sheet` | `decisions.jsonl` | `data/manual_review.csv` (20 cases to re-read by hand) |
| 6 | `python decision/quality.py report` | everything above | `quality.json` (served as it is by the API) |

To try it without waiting for Maël: `python decision/decide.py --input decision/sample/analysis.sample.jsonl`
(10 hand-written lines, `rev_id` 1 to 10, marked `sample`). Any input other than `analysis.jsonl` writes to
`decisions.test.jsonl`, never to the file Léopold imports, and a `sample` line is never published.

**Two-model rule (in the code)**: `flag` only if Nemotron says `suspicious: true` **and** Gemini says `flag`;
`dismiss` if both say no; otherwise `human_review` (disagreement, missing opinion, odd answer).
`publish` is only possible for a `flag`, and never for the `synthetic` campaign.
Non-suspicious cases get `dismiss` by rule (`decided_by: "rule"`), except a sample (5%) sent to Gemini
to measure disagreements. A network error writes nothing: running again resumes where it stopped.

**Fields added to format 15.3** (to report to Léopold for the import): `page_id`, `title`, `kind`, `synthetic`,
`signal_type`, `explanation`, `decided_by`, `decider_model`, `prompt_version`, `nemotron_suspicious`,
`gemini_decision`, `disagreement`, and in `exposure`: `still_online`, `readers_partial`, `ended_by`, `tracked_by`, `titles`.
`tracked_by: "revert only"` = our parser does not see the change (e.g. a picture in an infobox): only a revert
ends the case, the duration and the readers may be overestimated. **Do not put such a case forward in the demo.**

**End of a case (exposure)**: the first later version that goes back to the earlier text (same `sha1`), or where the
suspicious content is gone (caption/file for a picture, number of `<ref>` back for sources, less than half of the
introduced words for text), judged from the suspicious version itself. Otherwise "still online" until 1 Oct 2026
(end of the data). Readers are an **upper bound** (views of the whole article), counted with the title of each
period, `null` before July 2015.

**Test campaign**: `synthetic: true` is the only label. `decide.py` removes it before calling Gemini;
Maël must do the same before Nemotron, otherwise the test grades itself.

To be filled in by the team, never invented: `data/manual_review.csv`.
