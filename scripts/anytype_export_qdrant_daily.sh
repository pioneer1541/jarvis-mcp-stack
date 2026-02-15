#!/usr/bin/env bash
set -euo pipefail

echo "== Anytype Export->Qdrant sync start: $(date -Iseconds) =="

BASE_EXPORT_DIR="${ANYTYPE_EXPORT_DIR:-/mnt/nas/anytype_export}"
MODE="${ANYTYPE_EXPORT_MODE:-all}"
EXTS="${ANYTYPE_EXPORT_EXTS:-md,txt,pdf}"

EXPORT_DIR="$BASE_EXPORT_DIR"
if [[ "$MODE" == "processed_md" ]]; then
  SUBDIR="${ANYTYPE_EXPORT_PROCESSED_MD_SUBDIR:-processed_md}"
  EXPORT_DIR="${BASE_EXPORT_DIR%/}/${SUBDIR}"
  EXTS="${ANYTYPE_EXPORT_PROCESSED_MD_EXTS:-md,txt}"
elif [[ "$MODE" == "pdf_only" ]]; then
  EXTS="pdf"
fi

echo "[info] export_mode=${MODE} export_dir=${EXPORT_DIR} exts=${EXTS}"

if ! docker exec -i mcp-hello sh -lc "[ -d '$EXPORT_DIR' ]"; then
  echo "Skip export sync: export dir not found in container: $EXPORT_DIR"
  echo "== Anytype Export->Qdrant sync end: $(date -Iseconds) =="
  exit 0
fi

# If directory exists but empty, skip.
if docker exec -i mcp-hello sh -lc "find '$EXPORT_DIR' -maxdepth 2 -type f | head -n 1 | grep -q ."; then
  :
else
  echo "Skip export sync: export dir is empty: $EXPORT_DIR"
  echo "== Anytype Export->Qdrant sync end: $(date -Iseconds) =="
  exit 0
fi

docker exec -i mcp-hello python3 /app/scripts/anytype_export_qdrant_sync.py \
  --export-dir "$EXPORT_DIR" \
  --state-file /app/data/anytype_export_sync_state.json \
  --exts "$EXTS"

echo "== Anytype Export->Qdrant sync end: $(date -Iseconds) =="
