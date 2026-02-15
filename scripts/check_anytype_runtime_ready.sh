#!/usr/bin/env bash
set -euo pipefail

ok=1

check() {
  local name="$1"
  local cmd="$2"
  if eval "$cmd" >/dev/null 2>&1; then
    echo "[OK]   $name"
  else
    echo "[FAIL] $name"
    ok=0
  fi
}

echo "== Anytype RAG Runtime Precheck =="

check "mcp-hello running" "docker ps --format '{{.Names}}' | grep -qx 'mcp-hello'"
check "openai-mcp-gateway running" "docker ps --format '{{.Names}}' | grep -qx 'openai-mcp-gateway'"
check "any-sync-bundle running" "docker ps --format '{{.Names}}' | grep -qx 'any-sync-bundle'"
check "qdrant reachable" "curl -fsS http://127.0.0.1:6333/collections >/dev/null"
check "qdrant collection exists" "curl -fsS http://127.0.0.1:6333/collections/ha_memory_qwen3 >/dev/null"
check "ollama embed model available" "curl -fsS http://127.0.0.1:11434/api/tags | grep -q 'qwen3-embedding:0.6b'"
check "gateway invoke memory_search route" "curl -fsS http://127.0.0.1:19100/openapi.json | grep -q '/invoke/memory_search'"

# Offline export precheck (Anytype export dir -> Qdrant ingestion)
EXPORT_DIR="$(docker exec -i mcp-hello sh -lc 'printf %s "${ANYTYPE_EXPORT_DIR:-/mnt/nas/anytype_export}"')"
EXPORT_MODE=0
if [ -n "$EXPORT_DIR" ]; then
  EXPORT_MODE=1
fi

if docker exec -i mcp-hello sh -lc '[ -n "${ANYTYPE_API_KEY:-}" ]'; then
  echo "[OK]   ANYTYPE_API_KEY configured"
else
  if [ "$EXPORT_MODE" -eq 1 ]; then
    echo "[WARN] ANYTYPE_API_KEY not set (ignored in export mode)"
  else
    echo "[FAIL] ANYTYPE_API_KEY configured"
    ok=0
  fi
fi
if docker exec -i mcp-hello sh -lc "[ -d '$EXPORT_DIR' ]" >/dev/null 2>&1; then
  if docker exec -i mcp-hello sh -lc "find '$EXPORT_DIR' -maxdepth 2 -type f | head -n 1 | grep -q ." >/dev/null 2>&1; then
    echo "[OK]   Anytype export dir non-empty ($EXPORT_DIR)"
  else
    echo "[FAIL] Anytype export dir is empty ($EXPORT_DIR)"
    ok=0
  fi
else
  echo "[FAIL] Anytype export dir exists ($EXPORT_DIR)"
  ok=0
fi

ANY_BASE="$(docker exec -i mcp-hello sh -lc 'printf %s "${ANYTYPE_API_BASE:-}"')"
if [ -n "$ANY_BASE" ]; then
  code="$(docker exec -i mcp-hello python3 - <<'PY'
import os
import requests
base = os.environ.get("ANYTYPE_API_BASE", "").strip().rstrip("/")
if not base:
    print("000")
    raise SystemExit(0)
url = base + "/v1/auth/challenges"
try:
    r = requests.post(url, json={"app_name":"mcp-tools-precheck"}, timeout=4)
    print(str(getattr(r, "status_code", 0) or 0))
except Exception:
    print("000")
PY
)"
  if [ "$code" != "000" ] && [ -n "$code" ]; then
    echo "[OK]   Anytype API base reachable ($ANY_BASE, http=$code)"
  else
    if [ "$EXPORT_MODE" -eq 1 ]; then
      echo "[WARN] Anytype API base unreachable (ignored in export mode): ${ANY_BASE:-<empty>}"
    else
      echo "[FAIL] Anytype API base reachable (${ANY_BASE:-<empty>})"
      ok=0
    fi
  fi
else
  if [ "$EXPORT_MODE" -eq 1 ]; then
    echo "[WARN] Anytype API base unreachable (ignored in export mode): <empty>"
  else
    echo "[FAIL] Anytype API base reachable (<empty>)"
    ok=0
  fi
fi

if [ "$ok" -eq 1 ]; then
  echo "== PRECHECK PASSED =="
  exit 0
fi

echo "== PRECHECK FAILED =="
exit 1
