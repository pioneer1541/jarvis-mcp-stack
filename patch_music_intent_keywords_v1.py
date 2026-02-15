#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import os
import shutil
import sys
from datetime import datetime

APP = "app.py"
TAG = "music_intent_keywords_v1"

NEEDLE_PARTS = [
    "'音量'", "'静音'", "'取消静音'", "'mute'", "'unmute'",
    "'pause'", "'resume'", "'play'", "'stop'", "'next'", "'previous'"
]

ADD_TOKENS = ["'播放'", "'我想听'", "'我想要听'", "'来一首'", "'放一首'", "'来点'"]

def main():
    if not os.path.exists(APP):
        print("ERROR: app.py not found")
        sys.exit(2)

    with io.open(APP, "r", encoding="utf-8") as f:
        lines = f.read().splitlines(True)

    idx = -1
    for i, ln in enumerate(lines):
        hit = True
        for p in NEEDLE_PARTS:
            if p not in ln:
                hit = False
                break
        if hit:
            idx = i
            break

    if idx < 0:
        print("ERROR: cannot find the music keywords list line.")
        print("Hint: run: grep -nE \"音量|静音|取消静音|previous\" app.py")
        sys.exit(3)

    ln = lines[idx]

    # if already contains tokens, do nothing
    already = True
    for t in ADD_TOKENS:
        if t not in ln:
            already = False
            break
    if already:
        print("OK: keywords already patched. Nothing to do.")
        return

    # Insert new tokens right after the opening '[' if exists, else append before closing ']'
    if "[" in ln and "]" in ln:
        left = ln.split("[", 1)[0] + "["
        body = ln.split("[", 1)[1].rsplit("]", 1)[0]
        right = "]" + ln.rsplit("]", 1)[1]
        items = [x.strip() for x in body.split(",") if x.strip()]
        sset = set(items)
        for t in ADD_TOKENS:
            if t not in sset:
                items.insert(0, t)  # put them in front to boost match
                sset.add(t)
        new_ln = left + " " + ", ".join(items) + " " + right
    else:
        # fallback: just append tokens if we cannot parse brackets
        new_ln = ln
        for t in ADD_TOKENS:
            if t not in new_ln:
                new_ln = new_ln.rstrip("\n") + ", " + t + "\n"

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = APP + ".bak." + TAG + "." + ts
    shutil.copy2(APP, bak)

    lines[idx] = new_ln
    with io.open(APP, "w", encoding="utf-8", newline="") as f:
        f.write("".join(lines))

    print("OK: patched app.py")
    print("Backup:", bak)
    print("Patched line number:", idx + 1)

if __name__ == "__main__":
    main()
