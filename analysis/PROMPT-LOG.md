# Nemotron prompt log (investigator)

Required for the NVIDIA prize: how we improved Nemotron's answers. Only facts read from the
code or measured on real edits are written here. Lines marked **TODO** are still to fill.

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
| 1 | Instructions in a **system** message, the edit alone in the user message | **TODO** |
| 2 | The prompt explains the input: `added` / `removed` are changed words with passages joined by ` … `, `image` has the old and new captions, `refs_removed` counts removed `<ref>` | **TODO** |
| 3 | The report must **quote the exact Finnish words with an English translation** | So a human can check the claim against the edit (stated in the prompt) |
| 4 | Only 8 fields are sent (`title`, `timestamp`, `kind`, `user_is_new`, `comment`, `added`, `removed`, `refs_removed`) plus `image.change/file/caption_old/caption_new` | "The account hash and ids would only add noise" (code comment) |
| 5 | `max_tokens` 1500 → 2000 | **TODO** |
| 6 | JSON parsing retries from each `{` until one parses | The model may write reasoning, possibly with braces, before the JSON (code comment) |
| 7 | Timeout 180 → 90 → 300 s | 20–220 s per call measured under load on Saturday (code comment) |
| 8 | `clean_report` keeps only the expected keys and types | **TODO** |

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
