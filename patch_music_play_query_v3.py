#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import os
import sys
import shutil
from datetime import datetime

APP = "app.py"
TAG = "music_play_query_v3"

MARK = "# MA_PLAY_QUERY_V1 (replaced by V2): prefer Music Assistant play_media"
def main():
    if not os.path.exists(APP):
        print("ERROR: app.py not found in current dir")
        sys.exit(2)

    with io.open(APP, "r", encoding="utf-8") as f:
        lines = f.read().splitlines(True)

    # find marker line
    idx = -1
    for i, ln in enumerate(lines):
        if MARK in ln:
            idx = i
            break
    if idx < 0:
        print("ERROR: cannot find marker line. Grep this string in app.py:")
        print(MARK)
        sys.exit(3)

    # find the next "if (" line after marker
    j = idx + 1
    while j < len(lines) and not lines[j].lstrip().startswith("if "):
        j += 1
    if j >= len(lines):
        print("ERROR: cannot find if-line after marker")
        sys.exit(4)

    indent = lines[j][:len(lines[j]) - len(lines[j].lstrip())]
    old = lines[j]

    new_cond = (
        indent
        + "if ('播放' in t0) or ('我想听' in t0) or ('我想要听' in t0) or ('来一首' in t0) or ('放一首' in t0) or ('来点' in t0) or (t0.strip().startswith('play')):\n"
    )

    if old == new_cond:
        print("OK: already patched (condition matches). Nothing to do.")
        return

    # backup
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = APP + ".bak." + TAG + "." + ts
    shutil.copy2(APP, bak)

    lines[j] = new_cond

    with io.open(APP, "w", encoding="utf-8", newline="") as f:
        f.write("".join(lines))

    print("OK: patched app.py")
    print("Backup:", bak)
    print("Replaced line:\nOLD: " + old.strip() + "\nNEW: " + new_cond.strip())

if __name__ == "__main__":
    main()
