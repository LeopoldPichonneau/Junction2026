# TimeProof — textes du formulaire de soumission

> Page *Project Submission* sur hackjunction.app. Remplir, puis **Save Draft**.

## Project Name

```
TimeProof
```

## Punchline

```
TimeProof shows who is rewriting history on Wikipedia — when, how, and with the evidence — and only publishes what it can prove.
```

## Description

```markdown
## The problem
Wikipedia is the world's memory: students, journalists and now AI models rely on it. But history can be rewritten one edit at a time: a word, a photo caption, a removed source. Nobody can re-read 862,076 versions of 19,742 articles. Existing tools catch vandalism, not narrative drift.

## What TimeProof does
We load the full edit history of Finnish Wikipedia's *History of Finland* articles (2003–2026) into MariaDB system-versioned tables, with Wikipedia's real edit times, so any article can be read as it stood on any date.

We look for three signals: framing drift (e.g. how the 1918 war is named), misleading images (a photo swapped or its caption changed — NVIDIA Nemotron *looks at the image* and checks it against the caption), and removed sources. Account patterns (bot-like rhythm, short-lived or single-topic accounts) are profiled without naming anyone.

For each case we compute an **exposure score**: how long the misleading version stayed online, and roughly how many readers saw it.

## Proof, not accusations
- Nemotron investigates; Gemini decides and writes a plain-English summary.
- A case is flagged only if both models agree; otherwise a human reviews it.
- Only approved cases reach the public dashboard, with links to the exact Wikipedia versions. No account is named publicly.
- Our own verdicts are versioned in MariaDB, so they are auditable too.

## Built with
MariaDB (system-versioned tables), NVIDIA Nemotron 3.5 Super VL, Gemini API, Hostinger VPS, CRACI (CI/CD and deployment). Data: MariaDB's Finnish Wikipedia datasets (CC BY-SA 4.0).
```

## Challenge Picker

- Wikipedia Through Time. (MariaDB)

## Tech Challenge Participation

- Best Use of Nemotron (NVIDIA)
- Best Use of Gemini API (Google DeepMind)
- Best use of CRACI

## Project Demo · Source Code · Video · Other Link · Presentation

Vides pour l'instant. À remplir dimanche : URL du site, dépôt public, vidéo ≤ 2 min.
