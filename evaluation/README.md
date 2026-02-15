# Post-Development Evaluation

## Goals
- Keep route behavior stable (`route_accuracy`).
- Keep answer quality useful (`helpful_rate`).
- Keep finance fallback producing numeric evidence (`finance_evidence_rate`).

## Run
- One command:
  - `make post-dev-eval`
- Phase-complete flow (runs container tests + HA-style daily100 eval_runner):
  - `make phase-eval`
- Direct script:
  - `./scripts/post_dev_eval.sh`
  - This script rebuilds `mcp-hello`, runs tests/eval in container, and copies `evaluation/latest_report.json` back.

## Automatic Trigger
- Install git hook once:
  - `make install-hooks`
- After that, every `git push` runs the phase-eval automatically.
  - Set `SKIP_PHASE_EVAL=1` to bypass for a specific push.

## Files
- `evaluation/criteria.json`: pass thresholds.
- `evaluation/cases.json`: route/helpful/finance datasets.
- `evaluation/run_post_dev_eval.py`: evaluator and report generator.
- `evaluation/latest_report.json`: latest run output.
 - `evaluation/eval_runner.py`: daily100 runner via gateway (`answer_question` or `ha_assist_context`).
 - `scripts/phase_eval.sh`: fixed phase-complete flow script.

## Anytype -> Qdrant Sync
- Required env for `mcp-hello`:
  - `ANYTYPE_API_BASE` (example: `http://192.168.1.162:31009`)
  - `ANYTYPE_API_KEY`
  - `ANYTYPE_SPACE_ID` (optional)
  - `OLLAMA_BASE_URL`
  - `EMBED_MODEL=qwen3-embedding:0.6b`
  - `QDRANT_URL`
  - `QDRANT_COLLECTION=ha_memory_qwen3`
  - `QDRANT_VECTOR_SIZE=1024`
- First full sync:
  - `docker exec -it mcp-hello python3 /app/scripts/anytype_qdrant_sync.py --state-file /app/data/anytype_sync_state.json --full-reindex`
- Incremental sync:
  - `./scripts/anytype_qdrant_daily.sh`
- Install hourly cron:
  - `./scripts/install_anytype_cron.sh`

## Policy For New Features
When adding a new feature/route, update both:
1. `evaluation/cases.json`
- Add at least 8 new `route_cases` for the new route.
- Add at least 10 new `helpful_cases` covering success and edge phrasings.
- If feature has numeric outputs, add at least 5 cases into `finance_cases`-like bucket (or create a new bucket in script and criteria).

2. `evaluation/criteria.json`
- Add/update threshold for the new bucket.
- Keep old thresholds unless intentionally changed with rationale in PR/commit note.

## Result Rule
A run is `ok=true` only if all gates pass.
