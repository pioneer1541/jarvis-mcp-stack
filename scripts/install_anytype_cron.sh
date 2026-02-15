#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CRON_JOB="0 * * * * cd ${ROOT_DIR} && ./scripts/anytype_export_qdrant_daily.sh >> ${ROOT_DIR}/logs/rag_daily.log 2>&1"

TMP_FILE="$(mktemp)"
trap 'rm -f "$TMP_FILE"' EXIT

crontab -l 2>/dev/null | grep -v "anytype_qdrant_daily.sh" | grep -v "anytype_export_qdrant_daily.sh" > "$TMP_FILE" || true
echo "$CRON_JOB" >> "$TMP_FILE"
crontab "$TMP_FILE"

echo "Installed cron job:"
echo "$CRON_JOB"
