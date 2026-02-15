#!/usr/bin/env python3
import os
import re
import shutil
from datetime import datetime

APP = "app.py"

def _read(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()

def _write(p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)

def _backup():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = "app.py.bak.news_p1p3_nonlocal_{0}".format(ts)
    shutil.copy2(APP, bak)
    return bak

def main():
    if not os.path.exists(APP):
        raise SystemExit("app.py not found")

    src = _read(APP)
    bak = _backup()

    # Limit patch to news_digest function block
    m0 = re.search(r'(?m)^def\s+news_digest\s*\(', src)
    if not m0:
        raise SystemExit("def news_digest not found")
    start = m0.start()
    m1 = re.search(r'(?m)^def\s+news_digest_legacy_fn_1\s*\(|(?m)^def\s+_news__norm_host\s*\(', src[m0.end():])
    end = (m0.end() + m1.start()) if m1 else len(src)

    block = src[start:end]

    # Find def _pick(...) inside news_digest and insert nonlocal line after it
    mp = re.search(r'(?m)^(?P<ind>[ \t]*)def\s+_pick\s*\([^\)]*\)\s*:\s*$', block)
    if not mp:
        raise SystemExit("def _pick(...) not found inside news_digest block")

    # Determine indentation for inside _pick body (one level deeper)
    ind_def = mp.group("ind")
    ind_body = ind_def + "    "

    # If already has nonlocal, do nothing
    after_def_pos = mp.end()
    lookahead = block[after_def_pos: after_def_pos + 300]
    if re.search(r'(?m)^\s*nonlocal\s+dropped_whitelist\b', lookahead):
        print("OK: nonlocal already present; no change.")
        print("Backup:", bak)
        return

    nonlocal_line = ind_body + "nonlocal dropped_blacklist, dropped_whitelist, dropped_anchor, dropped_intlban, relax_used\n"

    # Insert after def line + newline
    line_end = block.find("\n", mp.end())
    if line_end < 0:
        raise SystemExit("unexpected: no newline after def _pick line")

    block2 = block[:line_end+1] + nonlocal_line + block[line_end+1:]

    out = src[:start] + block2 + src[end:]
    _write(APP, out)

    print("OK: inserted nonlocal counters into _pick (news_digest).")
    print("Backup:", bak)

if __name__ == "__main__":
    main()
