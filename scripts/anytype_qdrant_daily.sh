#!/usr/bin/env bash
set -euo pipefail

echo "== Anytype->Qdrant sync start: $(date -Iseconds) =="

if ! docker exec -i mcp-hello sh -lc '[ -n "${ANYTYPE_API_KEY:-}" ]'; then
  echo "Skip Anytype sync: ANYTYPE_API_KEY is empty in mcp-hello container."
  echo "== Anytype->Qdrant sync end: $(date -Iseconds) =="
  exit 0
fi

docker exec -i mcp-hello python3 /app/scripts/anytype_qdrant_sync.py \
  --state-file /app/data/anytype_sync_state.json \
  --page-size 50 \
  --max-pages 40

echo "== Anytype->Qdrant sync end: $(date -Iseconds) =="
