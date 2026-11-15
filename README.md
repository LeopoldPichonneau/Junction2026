# TimeProof

**TimeProof shows who is rewriting history on Wikipedia — when, how, and with the evidence — and only publishes what it can prove.**

Built in 48 hours at Junction 2026 by team ENLMe, for the challenge *Wikipedia Through Time* (MariaDB).

Live site: https://timeproof.srv2158940.hstgr.cloud

## What it does

Wikipedia is the world's memory, but history can be rewritten one edit at a time: a word, a photo caption, a
removed source. TimeProof loads the full edit history of the Finnish Wikipedia articles on the history of
Finland (862,076 revisions of 19,742 articles, 2003 to 1 October 2026) and looks for three signals: shifting
words, misleading pictures and removed sources.

- **Time machine.** Every revision is stored in MariaDB system-versioned tables with Wikipedia's real edit time,
  so one query shows any article as it stood on any day.
- **Two-model rule.** NVIDIA Nemotron investigates each candidate edit (it reads the text and looks at the
  picture). Gemini decides. A case is published only when both agree; otherwise a human decides.
- **Exposure.** For each case: how long the version stayed online, and an upper bound of how many readers saw it.
- **Evidence.** Each case shows the word-by-word diff, its chronology and a ready note for Wikipedia editors.
  For picture cases, Cloudinary keeps an archived copy and renders the before / after view.
- **TimeProof Lens.** A bookmark that outlines the cases on the real Wikipedia page.
- **Live watch.** Hermes Agent, on the same Hostinger VPS, checks Wikipedia's recent changes every 10 minutes
  and runs the human review desk on the team's private Discord channel. It orchestrates, it never judges.
- **Detection quality.** The site publishes how well it works: planted test edits caught, flags confirmed by a
  human re-read, cases held back when the models disagree.

## Ground rules

- No Wikipedia account is ever named: accounts appear only as anonymous codes.
- TimeProof never edits Wikipedia.
- Planted test edits are labelled as synthetic and never shown as real cases.
- Reader numbers are upper bounds (page views of the whole article), always shown with "≈".
- Pictures are shown with their author and license.

## Repository layout

| Folder | What it holds |
|---|---|
| [`server/`](server/) | FastAPI server and API, history loader, live watcher |
| [`db/`](db/) | MariaDB schema (system-versioned tables) |
| [`analysis/`](analysis/) | Candidate rules, picture fetching, Nemotron investigator, Cloudinary evidence |
| [`decision/`](decision/) | Gemini decider, two-model rule, exposure, account patterns, quality figures |
| [`web/`](web/) | The site: plain HTML, CSS and JavaScript, no build step |
| [`lens/`](lens/) | The TimeProof Lens bookmark and its builder |
| [`hermes/`](hermes/) | Hermes Agent jobs: live watch, review desk, hourly brief |
| [`docs/`](docs/) | Technical reference and the team's working notes from the hackathon (in French) |
| [`.github/workflows/`](.github/workflows/) | Deployment to the VPS on CRACI runners |

## Run it locally

Requirements: Docker with Docker Compose.

```bash
cp .env.example .env        # fill in the two database passwords
docker compose up --build   # site and API on http://localhost:8000
```

With `USE_MOCK=true` (the default in `.env.example`) no API key is needed: calls to the models return
simulated data in the right format. The data files are not in this repository; `docs/TECH.md` explains where
they come from and how to load them. Each folder has its own README with the commands to run.

## Built with

MariaDB (system-versioned tables) · NVIDIA Nemotron 3.5 Super VL · Gemini API · Hostinger VPS with Hermes
Agent · Cloudinary · CRACI (CI/CD and deployment) · FastAPI · plain HTML, CSS and JavaScript.

## Credits and licenses

- Code: MIT, see [`LICENSE`](LICENSE).
- The versioned `article` table follows the official example
  [mariadb-system-versioning-wikipedia](https://github.com/MariaDB/mariadb-system-versioning-wikipedia) (MIT).
- Data: [mariadb-wikipedia-datasets](https://github.com/MariaDB/mariadb-wikipedia-datasets).
  Wikipedia text is under CC BY-SA 4.0. Pictures come from Wikimedia Commons, each under its own license.

Team ENLMe: Léopold, Maël, Nathanaël, Eléa.
