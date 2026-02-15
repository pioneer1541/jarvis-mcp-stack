#!/usr/bin/env bash
set -euo pipefail

FILE=~/ai-stack/mcp-tools/app.py
cp -a "$FILE" "${FILE}.bak.$(date +%Y%m%d-%H%M%S)"

python3 - <<'PY'
import io

path = "/home/pioneer1541/ai-stack/mcp-tools/app.py"
with open(path, "r", encoding="utf-8") as f:
    s = f.read()

old = """    # If legacy defaults are used but query is Chinese/event-like, still adjust
    try:
        if _mcp__has_zh(q):
            if str(language or "").strip().lower() in ("", "en"):
                lang_used = "zh-CN"
            if str(categories or "").strip().lower() in ("", "general"):
                cat_used = _mcp__auto_categories(q, "auto")
    except Exception:
        pass
"""

new = """    # If legacy defaults are used but query is Chinese, still adjust language only.
    # IMPORTANT: do NOT override categories when user explicitly provides it (e.g., 'general').
    try:
        if _mcp__has_zh(q):
            if str(language or "").strip().lower() in ("", "en"):
                lang_used = "zh-CN"
            cat_in = str(categories or "").strip().lower()
            if cat_in in ("", "auto"):
                cat_used = _mcp__auto_categories(q, "auto")
    except Exception:
        pass
"""

if old not in s:
    raise SystemExit("Patch failed: target block not found (file may differ).")

s2 = s.replace(old, new, 1)

with open(path, "w", encoding="utf-8") as f:
    f.write(s2)

print("OK: patch applied.")
PY

python3 -m py_compile ~/ai-stack/mcp-tools/app.py
echo "OK: syntax check passed."

docker compose -f ~/ai-stack/mcp-tools/docker-compose.yml up -d --build --force-recreate mcp-hello
echo "OK: mcp-hello recreated."
