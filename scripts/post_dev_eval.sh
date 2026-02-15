#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

echo "[post-dev-eval] rebuild and start container"
docker compose up -d --build --force-recreate mcp-hello > /tmp/post_dev_eval_docker.log 2>&1 || {
  cat /tmp/post_dev_eval_docker.log
  exit 1
}

echo "[post-dev-eval] sync tests/evaluation into container"
docker cp tests/. mcp-hello:/app/tests
docker cp evaluation/. mcp-hello:/app/evaluation

echo "[post-dev-eval] python compile"
docker exec -i mcp-hello python -m py_compile /app/app.py

echo "[post-dev-eval] unit tests"
docker exec -i mcp-hello python -m unittest discover -s /app/tests -p "test_*.py"

echo "[post-dev-eval] policy eval"
set +e
docker exec -i mcp-hello sh -lc "cd /app && python evaluation/run_post_dev_eval.py --cases /app/evaluation/cases.json --criteria /app/evaluation/criteria.json --report /app/evaluation/latest_report.json"
EVAL_EXIT=$?
set -e
docker cp mcp-hello:/app/evaluation/latest_report.json evaluation/latest_report.json

echo "[post-dev-eval] source stability eval"
set +e
docker exec -i mcp-hello sh -lc "cd /app && python evaluation/run_source_stability_check.py --criteria /app/evaluation/source_stability_criteria.json --report /app/evaluation/source_stability_report.json --loops 2"
STAB_EXIT=$?
set -e
docker cp mcp-hello:/app/evaluation/source_stability_report.json evaluation/source_stability_report.json

echo "[post-dev-eval] done"
if [ "$EVAL_EXIT" -ne 0 ] || [ "$STAB_EXIT" -ne 0 ]; then
  exit 1
fi
exit 0
