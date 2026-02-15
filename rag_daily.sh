#!/usr/bin/env bash
set -euo pipefail

echo "== RAG daily start: $(date -Iseconds) =="

./scripts/anytype_export_qdrant_daily.sh

docker exec -i mcp-hello python3 - <<'PY'
import app

def run_cmd(text):
    ret = app._route_request_obj(text=text, language="zh")
    if not isinstance(ret, dict):
        print(text + " => invalid response")
        return
    rt = str(ret.get("route_type") or "")
    final = str(ret.get("final") or "")
    print(text + " => route_type=" + rt)
    print(final)

run_cmd("同步数据源 nas")
run_cmd("预热数据源 nas")
PY

echo "== RAG daily end: $(date -Iseconds) =="
