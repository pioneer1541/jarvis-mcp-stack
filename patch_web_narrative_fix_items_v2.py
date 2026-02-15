#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import re

APP = "app.py"

PAT = re.compile(r"^\s*final\s*=\s*_web__render_narrative\s*\(\s*q\s*,\s*items\s*,\s*lang\s*\)\s*$")

def backup(path):
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = "{0}.bak.web_narrative_fix_items_v2_{1}".format(path, ts)
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    with open(bak, "w", encoding="utf-8") as f:
        f.write(src)
    return bak

def main():
    bak = backup(APP)

    with open(APP, "r", encoding="utf-8") as f:
        lines = f.read().splitlines(True)

    out = []
    replaced = 0

    for ln in lines:
        if PAT.match(ln.strip("\n")):
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
            replaced += 1
        else:
            out.append(ln)

    with open(APP, "w", encoding="utf-8") as f:
        f.writelines(out)

    print("OK patched:", APP)
    print("Backup:", bak)
    print("Replaced lines:", replaced)

if __name__ == "__main__":
    main()
