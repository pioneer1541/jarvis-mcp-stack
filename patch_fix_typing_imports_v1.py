#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import time

APP = "app.py"
NEEDED = ["Tuple", "Optional", "Dict", "Any"]

def backup(path):
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = "{0}.bak.fix_typing_{1}".format(path, ts)
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    with open(bak, "w", encoding="utf-8") as f:
        f.write(src)
    return bak, src

def main():
    bak, src = backup(APP)
    lines = src.splitlines(True)

    need_add = []
    for name in NEEDED:
        used = re.search(r"\b" + re.escape(name) + r"\b", src) is not None
        imported = re.search(
            r"^(from\s+typing\s+import\s+.*\b" + re.escape(name) + r"\b|import\s+typing\b)",
            src,
            flags=re.MULTILINE,
        ) is not None
        if used and (not imported):
            need_add.append(name)

    if not need_add:
        print("No missing typing imports detected. Backup:", bak)
        return

    out = []
    patched = False
    for line in lines:
        if (not patched) and line.startswith("from typing import "):
            existing = line.strip().split("import", 1)[1]
            for n in need_add:
                if re.search(r"\b" + re.escape(n) + r"\b", existing) is None:
                    line = line.rstrip("\n") + ", {0}\n".format(n)
            patched = True
        out.append(line)

    if not patched:
        insert_at = 0
        for i, line in enumerate(out[:200]):
            if line.startswith("import ") or line.startswith("from "):
                insert_at = i + 1
        out.insert(insert_at, "from typing import {0}\n".format(", ".join(need_add)))

    with open(APP, "w", encoding="utf-8") as f:
        f.write("".join(out))

    print("OK patched typing imports:", ", ".join(need_add))
    print("Backup:", bak)

if __name__ == "__main__":
    main()
