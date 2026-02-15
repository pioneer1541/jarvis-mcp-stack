#!/usr/bin/env bash
set -euo pipefail

ANYTYPE_BIN="${ANYTYPE_BIN:-/home/pioneer1541/.local/bin/anytype-cli}"
LISTEN_ADDR="${ANYTYPE_LISTEN_ADDR:-0.0.0.0:31012}"
STATE_PATH="${ANYTYPE_STATE_PATH:-/home/pioneer1541/.anytype-cli}"
LOG_FILE="${ANYTYPE_LOG_FILE:-/home/pioneer1541/.anytype-cli/serve.log}"
NETWORK_CONFIG="${ANYTYPE_NETWORK_CONFIG:-/mnt/ai_data/anytype-sync/data/client-config.yml}"

if [ ! -x "$ANYTYPE_BIN" ]; then
  echo "anytype-cli not found at: $ANYTYPE_BIN"
  echo "Please install anytype-cli first."
  exit 2
fi

mkdir -p "$STATE_PATH"

# Ensure serve is running first. auth login requires a running local server.
pkill -f "$ANYTYPE_BIN serve" || true

nohup "$ANYTYPE_BIN" serve \
  --listen-address "$LISTEN_ADDR" \
  > "$LOG_FILE" 2>&1 < /dev/null &

PORT="${LISTEN_ADDR##*:}"
READY=0
for _ in $(seq 1 20); do
  if ss -lntp | grep -q ":${PORT}\\b"; then
    READY=1
    break
  fi
  sleep 0.5
done
if [ "$READY" -ne 1 ]; then
  echo "Anytype Local API did not start. Check log: $LOG_FILE"
  tail -n 80 "$LOG_FILE" || true
  if grep -q "No stored account key found" "$LOG_FILE" 2>/dev/null; then
    echo "Hint: No stored account key found. Export ANYTYPE_ACCOUNT_KEY and rerun this script."
  fi
  exit 1
fi

# Login stores account key locally for subsequent starts.
if [ -n "${ANYTYPE_ACCOUNT_KEY:-}" ]; then
  login_args=(
    auth login
    --account-key "$ANYTYPE_ACCOUNT_KEY"
    --path "$STATE_PATH"
    --listen-address "$LISTEN_ADDR"
  )
  if [ -f "$NETWORK_CONFIG" ]; then
    login_args+=(--network-config "$NETWORK_CONFIG")
  fi
  "$ANYTYPE_BIN" "${login_args[@]}"
else
  echo "ANYTYPE_ACCOUNT_KEY is empty; skip login and use existing local auth state."
fi

echo "Anytype Local API started on $LISTEN_ADDR"
echo "Log: $LOG_FILE"
