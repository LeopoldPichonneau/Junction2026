# Nemotron prompt log (investigator)

Required for the NVIDIA prize: how we improved Nemotron's answers. Only facts read from the
code or measured on real edits are written here. Lines marked **TODO** are still to fill; "not recorded" means nobody noted why at the time.

## v1: Friday's starting point (`docs/TECH.md`, section 7)

- Prompt: generic investigator instructions plus the JSON answer schema. It does not explain
  the input fields and does not ask for quotes.
- Input: the prompt and the whole `candidates.jsonl` line in **one user message** (ids, account
  hash, thumbnail URL, author and license included).
- Call: `max_tokens` 1500, timeout 180 s.
- Parsing: text between the first `{` and the last `}`.
- Observed on Friday (notes in `docs/TECH.md`; these answers were not saved): Nemotron
  understood Finnish, spotted "civil war" → "war of liberation" and explained the reframing,
  described a photo and caught a fake caption. 1.3 s for text, 2.3 s with an image.

## v2: Saturday (`analysis/run_nemotron.py`)

| # | Change | Reason |
|---|---|---|
| 1 | Instructions in a **system** message, the edit alone in the user message | Not recorded |
| 2 | The prompt explains the input: `added` / `removed` are changed words with passages joined by ` … `, `image` has the old and new captions, `refs_removed` counts removed `<ref>` | Not recorded |
| 3 | The report must **quote the exact Finnish words with an English translation** | So a human can check the claim against the edit (stated in the prompt) |
| 4 | Only 8 fields are sent (`title`, `timestamp`, `kind`, `user_is_new`, `comment`, `added`, `removed`, `refs_removed`) plus `image.change/file/caption_old/caption_new` | "The account hash and ids would only add noise" (code comment) |
| 5 | `max_tokens` 1500 → 2000 | Not recorded |
| 6 | JSON parsing retries from each `{` until one parses | The model may write reasoning, possibly with braces, before the JSON (code comment) |
| 7 | Timeout 180 → 90 → 300 s | 20–220 s per call measured under load on Saturday (code comment) |
| 8 | `clean_report` keeps only the expected keys and types | Not recorded |

## Results with v2 on real edits

From `data/exchange/analysis.jsonl`, 14/11 around 14:10 Helsinki (8 edits, all on article 1150,
model `nemotron-3.5-super-vl`, 60–112 s per call):

| rev_id | Kind | Suspicious | What the answer shows |
|---|---|---|---|
| 24234965 | framing (12/09/2026) | **yes** | Quotes "Sisällissota" ("Civil War") → "eli Vapaussota" ("i.e. the War of Liberation") and the reframing of the actors as "hallituksen" / "kapinan aloittaneet", each with a translation |
| 462549 | recaptioned image | no | Describes the photo (people working a field with hoes); caption matches |
| 463331 | recaptioned image | no | Quotes the number change 80 000 → 75 000 prisoners; photo of a crowded field, caption matches |
| 464668 | recaptioned image | no | Caption expanded; photo matches |
| 464719 | recaptioned image | no | Death toll "yli 11000" → "11 000–13 000"; prison camp photo, caption matches |
| 466136 | recaptioned image | no | Spelling fix "Limingalainen" → "Liminkalainen" |
| 466477 | recaptioned image | no | "Länkipohjalla" → "Länkipohjassa", same meaning |
| 466483 | recaptioned image | no | Grammatical rewording of the mobilization sentence |

Change 3 is followed in all 8 answers: each report quotes the Finnish words with a translation.

## v3: Saturday afternoon, after the first batch and two false alarms

Batch of 14/11 around 15:00 Helsinki: 75 edits sent, 50 answered, 25 failed
(14 × HTTP 500 from the server, 7 empty answers, 4 answers cut in the middle of the JSON).
Reading the 3 "suspicious" answers against the raw wikitext showed 2 false alarms caused by
our pipeline, not by the model.

| # | Change | Reason (measured) |
|---|---|---|
| 9 | `max_tokens` 2000 → 6000 | 11 of 75 answers were empty or cut: the model spends tokens reasoning before the JSON |
| 10 | 3 attempts with 10 / 20 / 30 s pauses; stop only after 10 failures in a row | HTTP 500 errors came in bursts; with 4 parallel calls, 3 failures in a row stopped the batch too early |
| 11 | The image sent is the **version of the file online on the day of the edit**, or no image if none existed yet (`fetch_images.py`, `version_timestamp`) | rev 510902 (Mikael Agricola, 2005): Nemotron said the caption "drawing by Albert Edelfelt" did not match a page of musical notation. Today's `Agricola.jpg` was uploaded in 2010 and shows a score by the composer **Alexander** Agricola: in 2005 the name pointed to another picture. Nemotron was right about the image it saw; we sent the wrong one |
| 12 | Only text shown under the picture (`thumb`, `frame`, `pienoiskuva`…) counts as a caption (`find_candidates.py`) | rev 703143 (Mannerheim, 2006): the "caption" "Lauri Kristian Relander" was the hover text of an infobox copied from Relander's article, not a visible caption. A clumsy copy, not manipulation |

After changes 11 and 12, `analysis.jsonl` keeps only answers whose evidence is unchanged (39 of 69):
10 edits are no longer candidates (including 703143) and 20 were sent with today's picture
instead of the one of the day, so they are sent again. Rows 464719 and 466136 of the table above
are among those 20.

## v1 vs v2 on the same edits

**TODO**: run once the main batch is over (the server is shared):

```bash
python analysis/compare_prompts.py --rev-id 24234965 --rev-id 463331 --rev-id 466136
python analysis/compare_prompts.py --show
```

Limit of this comparison: `compare_prompts.py` sends v1 through the v2 call path (system message,
2000 tokens, robust parsing). It tests changes 2, 3 and 4, not 1, 5 and 6.

| rev_id | v1 suspicious | v2 suspicious | Difference seen |
|---|---|---|---|
| | | | |
