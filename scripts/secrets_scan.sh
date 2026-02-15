#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "== Secret Scan =="

# Scan tracked files only, excluding secrets/ and data/ and common lockfiles.
FILES="$(git ls-files 2>/dev/null | grep -vE '^(\\./)?(secrets/|data/|logs/|\\.venv/)' | grep -vE '(^|\\./)scripts/secrets_scan\\.sh$' | grep -vE '[.]example$' || true)"
if [[ -z "${FILES}" ]]; then
  # Fallback: scan the working tree (still exclude secrets/ and heavy dirs).
  if command -v rg >/dev/null 2>&1; then
    FILES="$(rg --files -S . | grep -vE '^(\\./)?(\\.git/|secrets/|data/|logs/|\\.venv/)' | grep -vE '(^|\\./)scripts/secrets_scan\\.sh$' | grep -vE '[.]sha256[.]' | grep -vE '[.]example$' || true)"
  else
    FILES="$(find . -type f -maxdepth 6 | sed 's|^\\./||' | grep -vE '^(\\.git/|secrets/|data/|logs/|\\.venv/)' | grep -vE '(^|\\./)scripts/secrets_scan\\.sh$' | grep -vE '[.]sha256[.]' | grep -vE '[.]example$' || true)"
  fi
  if [[ -z "${FILES}" ]]; then
    echo "[warn] no files found to scan; skipping"
    exit 0
  fi
  echo "[info] git index empty/unavailable; scanning working tree files instead"
fi

PATTERN='(eyJhbGciOi|AIzaSy|BSA[0-9A-Za-z_\\-]{10,}|BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|xox[baprs]-[0-9A-Za-z-]+)'

HIT=0
while IFS= read -r f; do
  case "$f" in
    scripts/secrets_scan.sh|./scripts/secrets_scan.sh) continue ;;
  esac
  [[ -f "$f" ]] || continue
  # Flag only if a token appears to be inlined (not a ${VAR...} reference).
  if rg -n -P "MINIFLUX_API_TOKEN=(?!\\$\\{MINIFLUX_API_TOKEN)" "$f" >/dev/null 2>&1; then
    echo "[hit] $f: MINIFLUX_API_TOKEN appears inlined"
    HIT=1
  fi
  if rg -n -P "ANYTYPE_API_KEY=(?!\\$\\{ANYTYPE_API_KEY)" "$f" >/dev/null 2>&1; then
    echo "[hit] $f: ANYTYPE_API_KEY appears inlined"
    HIT=1
  fi
  if rg -n "$PATTERN" "$f" >/dev/null 2>&1; then
    echo "[hit] $f: matches high-risk token pattern"
    HIT=1
  fi
done <<< "${FILES}"

if [[ "$HIT" -ne 0 ]]; then
  echo "[FAIL] potential secrets detected in tracked files"
  exit 2
fi

echo "[OK] no obvious secrets detected in tracked files"
