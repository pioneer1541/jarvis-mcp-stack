#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import os
import re
import sys


def _read_text(p):
    with io.open(p, "r", encoding="utf-8") as f:
        return f.read()


def _write_text(p, s):
    with io.open(p, "w", encoding="utf-8") as f:
        f.write(s)


def _already_patched(src):
    return "HOLIDAY_THIS_YEAR_FORCE_V1" in src


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "app.py"
    if not os.path.exists(path):
        print("ERROR: file not found: " + str(path))
        sys.exit(2)

    src = _read_text(path)

    if _already_patched(src):
        print("OK: already patched")
        return

    # Find the line: rr = holiday_vic(y)
    # Insert "this year" override just before it.
    lines = src.splitlines(True)

    idx = -1
    for i, ln in enumerate(lines):
        if "rr = holiday_vic(y)" in ln:
            idx = i
            break

    if idx < 0:
        print("ERROR: cannot find target line: rr = holiday_vic(y)")
        sys.exit(3)

    # Determine indentation from the target line
    m = re.match(r"^(\s*)rr\s*=\s*holiday_vic\(y\)\s*", lines[idx])
    indent = ""
    if m:
        indent = m.group(1)

    insert_block = []
    insert_block.append(indent + "# HOLIDAY_THIS_YEAR_FORCE_V1 BEGIN\n")
    insert_block.append(indent + "t = str(user_text or \"\")\n")
    insert_block.append(indent + "if (\"今年\" in t) or (\"this year\" in t.lower()):\n")
    insert_block.append(indent + "    try:\n")
    insert_block.append(indent + "        y = int(getattr(now, \"year\"))\n")
    insert_block.append(indent + "    except Exception:\n")
    insert_block.append(indent + "        pass\n")
    insert_block.append(indent + "# HOLIDAY_THIS_YEAR_FORCE_V1 END\n")

    lines = lines[:idx] + insert_block + lines[idx:]
    out = "".join(lines)

    _write_text(path, out)
    print("OK: patched " + str(path))


if __name__ == "__main__":
    main()

