#!/usr/bin/env python3
# Patch: ensure "import os" exists at top-level imports (fix container crash: os not defined).
# No f-strings.

import sys

def main():
    path = "app.py"
    try:
        with open(path, "r", encoding="utf-8") as f:
            s = f.read()
    except Exception as e:
        print("ERROR: cannot read app.py:", str(e))
        return 2

    lines = s.splitlines(True)

    # detect existing os import
    has_os = False
    for ln in lines:
        t = ln.strip()
        if t == "import os" or t.startswith("import os,") or t.startswith("import os "):
            has_os = True
            break
        if t.startswith("from os import "):
            has_os = True
            break

    if has_os:
        print("OK: app.py already has import os (no change).")
        return 0

    # find first top-level import line
    insert_at = None
    for i, ln in enumerate(lines):
        if ln.startswith("import ") or ln.startswith("from "):
            insert_at = i
            break

    # if no import block found, insert at file start
    if insert_at is None:
        insert_at = 0

    patch_lines = ["import os\n"]
    # keep a blank line separation if needed
    if insert_at > 0 and (lines[insert_at - 1].strip() != ""):
        patch_lines = ["\n", "import os\n"]
    else:
        # if we inserted at very top and next line is not blank, add blank line after
        if insert_at == 0 and len(lines) > 0 and lines[0].strip() != "":
            patch_lines = ["import os\n", "\n"]

    new_lines = lines[:insert_at] + patch_lines + lines[insert_at:]
    out = "".join(new_lines)

    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(out)
    except Exception as e:
        print("ERROR: cannot write app.py:", str(e))
        return 3

    print("OK: patched app.py (added import os).")
    return 0

if __name__ == "__main__":
    sys.exit(main())
