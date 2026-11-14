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
| `hermes/timeproof_watch.py` | the Hermes job; installed as `/opt/data/scripts/timeproof_watch.py` in the Hermes container |
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
curl -s https://timeproof.srv2158940.hstgr.cloud/api/live    # last check and counters

cd ~/timeproof
docker compose exec -T server python watch.py                # one run by hand
docker compose exec -T server python watch.py --no-models    # store and filter only
```

A run that is still working makes the next trigger a no-op (database lock), so two runs never overlap.
After a crash the next run resumes from the saved cursor; a version already stored is never stored twice
(a page is always caught up "from its stored head").

## Mock mode

With `USE_MOCK=true`, `python watch.py` sends nothing: one realistic fake edit (the 1918 war renamed in a
prose paragraph), mocked models, files named `live-*-mock.jsonl`, and every database change rolled back.

## Settings

TimeProof `.env`: `INTERNAL_TOKEN`, `WATCH_FIRST_HOURS`, `WATCH_INTERVAL_MIN`, `REVIEWS_PER_HOUR`, and the
model keys (`VERDA_INFERENCE_KEY`, `GEMINI_API_KEY`, `GEMINI_MODEL`): without them candidates stay queued.
Hermes `.env` (`/opt/data/.env`): `TIMEPROOF_URL`, `TIMEPROOF_INTERNAL_TOKEN`.
