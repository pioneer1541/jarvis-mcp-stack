#!/usr/bin/env python3
import re
import sys
import shutil
import datetime
from pathlib import Path

APP = Path("app.py")

def backup_file(p: Path) -> Path:
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = p.with_name(p.name + ".bak.news_v2_4_fix_syntax." + ts)
    shutil.copy2(str(p), str(bak))
    return bak

def main() -> int:
    if not APP.exists():
        print("ERROR: app.py not found.", file=sys.stderr)
        return 2

    s = APP.read_text(encoding="utf-8")
    changed = False

    # 1) Fix: decorator and def on same line -> split line
    s2 = re.sub(r"\)def\s+news_digest", ")\ndef news_digest", s)
    if s2 != s:
        s = s2
        changed = True

    # 2) Fix: put cfg assignment on new line if it was jammed after colon
    pat = re.compile(r'(def\s+news_digest\s*\([^)]*\)\s*(?:->\s*dict\s*)?:)\s*cfg\s*=\s*_news__cfg\(\)')
    s3 = pat.sub(r'\1\n    cfg = _news__cfg()', s)
    if s3 != s:
        s = s3
        changed = True

    if not changed:
        print("No change: nothing to fix.")
        return 0

    bak = backup_file(APP)
    APP.write_text(s, encoding="utf-8")
    print("Fixed syntax. Backup:", str(bak))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
