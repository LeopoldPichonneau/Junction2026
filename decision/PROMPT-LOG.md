# Prompt log (required by the NVIDIA submission: "how you improved its outputs")

One entry per prompt change, for the investigator (Nemotron, `analysis/`) and the decider (Gemini, `decision/decide.py`).
Measure each version on the same labelled set: the synthetic campaign (`data/exchange/synthetic_candidates.jsonl`)
plus the hand-checked cases (`data/manual_review.csv`). Only write numbers you actually measured.

| Date & time | Model | Version | What changed | Why (what went wrong before) | Result on the same set |
|---|---|---|---|---|---|
| | Nemotron | v1 | Starting prompt from docs/TECH.md §7 | — | |
| 14/11 13:03 | Gemini (gemini-3.8-flash) | v1 | Starting prompt from docs/TECH.md §8 | — | 3 hand-written sample cases (rev 1-3): 3 × flag, as expected; correct Finnish reading. But the public texts accuse editors (see below). |
| 14/11 13:15 | Gemini (gemini-3.8-flash) | v2 | Writing rules for the published fields: quote old/new wording with translation, no judgement of intent, cautious and attributed wording, banned words in headlines, `publish` only if checkable | v1 wrote "falsely", "fabricates historical context", "a common tactic to erode consensus facts": accusations our public site must not make | *to fill after rerunning the same 3 cases:* `python decision/decide.py --input decision/sample/analysis.sample.jsonl --limit 3 --output data/exchange/decisions.test.v2.jsonl` |

## Examples worth quoting in the submission

Sample case 2 (a photo caption changed from "Väkeä torilla 1918" / "People in the market square" to
"Punavankeja vankileirillä 1918" / "Red prisoners in a prison camp"):

- **v1 headline**: "Market crowd photo falsely relabeled as civil war prison camp"
- **v1 summary (extract)**: "This recaptioning fabricates historical context without changing the underlying media file."
- **v2**: *to paste after the rerun*

Sample case 3 (three references removed):

- **v1 explanation (extract)**: "Stripping references from sensitive historical casualty data … is a common tactic to erode consensus facts."
- **v2**: *to paste after the rerun*
