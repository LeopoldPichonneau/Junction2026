# Prompt log (required by the NVIDIA submission: "how you improved its outputs")

One entry per prompt change, for the investigator (Nemotron, `analysis/`) and the decider (Gemini, `decision/decide.py`).
Measure each version on the same labelled set: the synthetic campaign (`data/exchange/synthetic_candidates.jsonl`)
plus the hand-checked cases (`data/manual_review.csv`). Only write numbers you actually measured.

| Date & time | Model | Version | What changed | Why (what went wrong before) | Result on the same set |
|---|---|---|---|---|---|
| | Nemotron | v1 | Starting prompt from docs/TECH.md §7 | — | |
| | Gemini | v1 | Starting prompt from docs/TECH.md §8 (`PROMPT_VERSION = "v1"` in decide.py) | — | |

## Examples worth quoting in the submission

<!-- Paste one before/after pair: the case, the v1 answer, the v2 answer, and why v2 is better. -->
