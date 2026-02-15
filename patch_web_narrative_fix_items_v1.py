#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import re

APP = "app.py"
TARGET = "final = _web__render_narrative(q, items, lang)\n"

def backup(path):
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = "{0}.bak.web_narrative_fix_items_{1}".format(path, ts)
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    with open(bak, "w", encoding="utf-8") as f:
        f.write(src)
    return bak, src

def main():
    bak, src = backup(APP)
    lines = src.splitlines(True)

    n = 0
    out = []
    for ln in lines:
        if ln == TARGET:
            indent = re.match(r"^(\s*)", ln).group(1)
            out.append(indent + "_items = None\n")
            out.append(indent + "try:\n")
            out.append(indent + "    _items = items\n")
            out.append(indent + "except Exception:\n")
            out.append(indent + "    d = locals().get(\"data\")\n")
            out.append(indent + "    if isinstance(d, dict):\n")
            out.append(indent + "        _items = d.get(\"results\") or []\n")
            out.append(indent + "    else:\n")
            out.append(indent + "        _items = []\n")
            out.append(indent + "final = _web__render_narrative(q, _items or [], lang)\n")
            n += 1
        else:
            out.append(ln)

    with open(APP, "w", encoding="utf-8") as f:
        f.writelines(out)

    print("OK patched:", APP)
    print("Backup:", bak)
    print("Replaced lines:", n)

if __name__ == "__main__":
    main()
