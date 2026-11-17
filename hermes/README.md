# hermes/ — Hermes Agent on the VPS: live watch and human review

Hermes Agent (v0.23.1, Hostinger's Docker image, container `hermes-agent-pxve-hermes-agent-1`) runs next to
TimeProof on the same Hostinger VPS. **Hermes orchestrates, it never judges**: it starts the watcher on a
schedule and relays results. Candidates, the two-model rule and `publish` stay in `analysis/` and `decision/`.
Hermes never writes to Wikipedia and never posts in public.

```
Hermes scheduler (every 10 min, no model call)
  └─ scripts/timeproof_watch.py ──POST /api/internal/watch (token)──▶ TimeProof server
                                                                        └─ server/watch.py
       1. Wikipedia RecentChanges since the saved cursor (read-only)
       2. our 19,742 articles only → missing versions stored in MariaDB with their real time
       3. candidate filters of analysis/find_candidates.py
       4. analysis/run_nemotron.py (2 calls at once) → decision/decide.py (two-opinion rule)
       5. import → site: "Live" badge, "Last check" line, figures on the quality page
```

Hermes cannot reach MariaDB or our scripts directly (other container, other Docker network), so it goes
through the server's internal routes, protected by `INTERNAL_TOKEN`.

## Files

| Where | What |
|---|---|
| `server/watch.py` | one watcher run (runs in the `server` container) |
| `server/live.py` | `POST /api/internal/watch`, `GET /api/live`, review desk routes |
| `hermes/timeproof_watch.py` | the watch job; installed as `/opt/data/scripts/timeproof_watch.py` in the Hermes container |
| `hermes/timeproof_review.py` | the review desk job; installed as `/opt/data/scripts/timeproof_review.py` |
| `hermes/timeproof_brief.py` | figures for the hourly brief; installed as `/opt/data/scripts/timeproof_brief.py` |
| `data/exchange/live-candidates.jsonl`, `live-analysis.jsonl`, `live-decisions.jsonl` | same formats as the batch files, plus `"source": "live"` and `"detected_at"` on candidates |
| `data/exchange/live-runs.jsonl` | one line per run (counters, errors) |
| `data/logs/watch.log` | the watcher's log |
| tables `watch_state`, `human_decision` | both system-versioned: every check and every human verdict keeps its history |

## Stop, start, logs (on the VPS, user `deploy`)

```bash
H=hermes-agent-pxve-hermes-agent-1
docker exec -u hermes $H hermes cron list                    # the job and its next run
docker exec -u hermes $H hermes cron pause 44a77c7d4841     # stop the watch (job id from `cron list`)
docker exec -u hermes $H hermes cron resume 44a77c7d4841    # start it again
docker exec -u hermes $H hermes cron runs                    # what the scheduler ran

tail -f ~/timeproof/data/logs/watch.log                      # the watcher's log
curl -s https://$PUBLIC_HOST/api/live                        # last check and counters

cd ~/timeproof
docker compose exec -T server python watch.py                # one run by hand
docker compose exec -T server python watch.py --no-models    # store and filter only
```

A run that is still working makes the next trigger a no-op (database lock), so two runs never overlap.
After a crash the next run resumes from the saved cursor; a version already stored is never stored twice
(a page is always caught up "from its stored head").

## Human review desk (private Discord channel)

Hermes job `timeproof-review` (every 2 min, no model call) runs `timeproof_review.py`:

1. It reads the new messages of the private channel. `approve <rev_id> <reason>` or `reject <rev_id> <reason>`
   from a team member listed in `DISCORD_ALLOWED_USERS` is recorded in the versioned table `human_decision`
   (who, when, why) and acknowledged in the channel. Anything else is ignored.
2. While fewer than 3 dossiers wait for an answer (and at most `REVIEWS_PER_HOUR` per hour), it posts the next
   `human_review` case: live cases first, then the most exposed. A dossier holds facts only: article, date,
   the Finnish quote and its English translation, sources removed, what Nemotron saw, what Gemini decided, why
   they disagree, links to both Wikipedia versions, time online, and the anonymous account code.

A human verdict never publishes a `human_review` case: publication stays with the rule in `decision/`.
One extra gate: a **live** edit that the rule decided to publish stays off the site until a team member
approves its dossier (live text is untrusted and was read by the models minutes after it was written). Synthetic and mock
cases never leave the server. The English translation is one plain model call on the server, with no tools.

```bash
docker exec -u hermes $H hermes cron pause 075991dd5be6     # stop the review desk
docker exec -u hermes $H hermes cron resume 075991dd5be6    # start it again
```

## Hourly brief (the Hermes agent's own model)

Hermes job `timeproof-brief` (id `05dd4a971735`, every 60 min) is the one place where Hermes's model (Gemini,
`model.provider: gemini` in `/opt/data/config.yaml`) writes something: a 4 to 6 line situation brief posted in
the private channel. `timeproof_brief.py` gives it **numbers only** (the public counters of `GET /api/live`):
no Wikipedia text, no model text, no reviewer text, so an edit cannot steer the agent. It reports the health
of the watch, the figures and the dossiers waiting; it judges no case.

```bash
docker exec -u hermes $H hermes cron run 05dd4a971735       # one brief now
docker exec -u hermes $H hermes cron pause 05dd4a971735     # stop the briefs
```

## Mock mode

With `USE_MOCK=true`, `python watch.py` sends nothing: one realistic fake edit (the 1918 war renamed in a
prose paragraph), mocked models, files named `live-*-mock.jsonl`, and every database change rolled back.

## Settings

TimeProof `.env`: `INTERNAL_TOKEN`, `WATCH_FIRST_HOURS`, `WATCH_INTERVAL_MIN`, `REVIEWS_PER_HOUR`, and the
model keys (`VERDA_INFERENCE_KEY`, `GEMINI_API_KEY`, `GEMINI_MODEL`): without them candidates stay queued.
Hermes `.env` (`/opt/data/.env`): `TIMEPROOF_URL`, `TIMEPROOF_INTERNAL_TOKEN`, `DISCORD_BOT_TOKEN`,
`DISCORD_REVIEW_CHANNEL_ID`, `DISCORD_ALLOWED_USERS` (Discord user ids, comma-separated), `GEMINI_API_KEY`
(Hermes's own model, used by the hourly brief only).
