#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "${SKIP_PHASE_EVAL:-}" == "1" ]]; then
  echo "[phase-eval] SKIP_PHASE_EVAL=1 set, skipping."
  exit 0
fi

PY="./.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "[phase-eval] ERROR: missing venv python at $PY" >&2
  echo "[phase-eval] Create it with: python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt" >&2
  exit 2
fi

echo "[phase-eval] 1) container tests + policy eval"
./scripts/post_dev_eval.sh

echo "[phase-eval] 2) rebuild/restart gateway + report host"
docker compose up -d --build --force-recreate openai-mcp-gateway eval-report > /tmp/phase_eval_docker.log 2>&1 || {
  cat /tmp/phase_eval_docker.log
  exit 1
}

echo "[phase-eval] 3) HA-style daily100 eval_runner (answer via ha_assist_context)"
DATASET="${EVAL_DATASET:-evaluation/daily100_report.example.json}"
$PY evaluation/eval_runner.py \
  --invoke ha_assist_context \
  --dataset "$DATASET" \
  --timeout-sec 25 \
  --out-json evaluation/daily100_eval_latest.json \
  --out-html evaluation/daily100_eval_latest.html \
  --fail-on-gates

HOST_IP="$(ip -4 -o addr show scope global | awk '{print $4}' | cut -d/ -f1 | head -n1)"
if [[ -z "$HOST_IP" ]]; then
  HOST_IP="127.0.0.1"
fi
echo "[phase-eval] report:"
echo "  http://$HOST_IP:19110/daily100_eval_latest.html"
