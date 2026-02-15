#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import shutil
from datetime import datetime

APP_PATH = os.path.join(os.path.dirname(__file__), "app.py")

def die(msg: str, code: int = 1):
    print("ERROR:", msg)
    raise SystemExit(code)

def main():
    if not os.path.exists(APP_PATH):
        die("app.py not found at: " + APP_PATH)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = APP_PATH + ".bak.force_this_year." + ts
    shutil.copy2(APP_PATH, bak)
    print("OK: backup ->", bak)

    with open(APP_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Find the holiday branch in _route_request_impl:
    #   if _is_holiday_query(user_text):
    #       ... (year extraction)
    #       rr = holiday_vic(y)
    #
    # Replace everything between that "if" and the "rr = holiday_vic(...)" line (inclusive)
    # with "now=_now_local(); y=now.year; rr=holiday_vic(y)".
    start_idx = -1
    rr_idx = -1

    for i, line in enumerate(lines):
        if "if _is_holiday_query(user_text):" in line:
            start_idx = i
            break

    if start_idx < 0:
        die("Could not find: if _is_holiday_query(user_text):")

    # locate rr = holiday_vic(...) after start
    for j in range(start_idx + 1, min(len(lines), start_idx + 120)):
        if "rr = holiday_vic(" in lines[j]:
            rr_idx = j
            break

    if rr_idx < 0:
        die("Could not find: rr = holiday_vic(y) after holiday branch start")

    indent = lines[start_idx].split("if _is_holiday_query(user_text):")[0]

    new_block = []
    new_block.append(indent + "    now = _now_local()\n")
    new_block.append(indent + "    try:\n")
    new_block.append(indent + "        y = int(getattr(now, \"year\"))\n")
    new_block.append(indent + "    except Exception:\n")
    new_block.append(indent + "        y = int(datetime.now().year)\n")
    new_block.append(indent + "    # Force current year only (ignore any year mentioned in user_text)\n")
    new_block.append(indent + "    rr = holiday_vic(y)\n")

    # Replace lines from start_idx+1 .. rr_idx (inclusive)
    before = lines[: start_idx + 1]
    after = lines[rr_idx + 1 :]

    lines2 = before + new_block + after

    with open(APP_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines2)

    print("OK: patched app.py")
    print("NOTE: Holiday year is now forced to current year only.")

if __name__ == "__main__":
    main()
