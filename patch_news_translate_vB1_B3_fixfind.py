#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import os
import sys

TARGET = "app.py"

NEW_FUNC = [
    "def _news__format_voice_miniflux(items: list, limit: int = 5) -> str:\n",
    "    \"\"\"Voice-friendly news lines for HA TTS.\n",
    "    Rules:\n",
    "    - Titles only (no source/time/URL)\n",
    "    - Clamp very long titles to reduce TTS pain\n",
    "    \"\"\"\n",
    "    try:\n",
    "        lim = int(limit)\n",
    "    except Exception:\n",
    "        lim = 5\n",
    "    if lim < 1:\n",
    "        lim = 1\n",
    "    if lim > 10:\n",
    "        lim = 10\n",
    "\n",
    "    it = items or []\n",
    "    if (not isinstance(it, list)) or (len(it) == 0):\n",
    "        return \"\"\n",
    "\n",
    "    out = []\n",
    "    idx = 1\n",
    "    for x in it:\n",
    "        if idx > lim:\n",
    "            break\n",
    "        if not isinstance(x, dict):\n",
    "            continue\n",
    "        title = str(x.get(\"title\") or \"\").strip()\n",
    "        if not title:\n",
    "            continue\n",
    "        if len(title) > 120:\n",
    "            title = title[:120].rstrip() + \"…\"\n",
    "        out.append(str(idx) + \") \" + title)\n",
    "        idx += 1\n",
    "\n",
    "    return \"\\n\".join(out).strip()\n",
    "\n",
]

def _leading_spaces(s):
    i = 0
    while i < len(s) and s[i] == " ":
        i += 1
    return i

def replace_top_level_func(src_lines, func_name, new_block_lines):
    # find "def func_name" at top-level
    start = None
    for i, ln in enumerate(src_lines):
        if ln.startswith("def " + func_name + "(") or ln.startswith("def " + func_name + " "):
            # allow weird spacing; but keep it simple
            start = i
            break
        if ln.startswith("def " + func_name + "(") is False and ln.startswith("def " + func_name) is True:
            start = i
            break
        if ln.startswith("def " + func_name + "(") is False and ln.startswith("def " + func_name + "(") is False:
            # continue
            pass

    if start is None:
        return None, "Cannot find def {0} in file.".format(func_name)

    # determine end: next top-level "def " or "import " at col 0 (excluding decorators not expected here)
    end = None
    for j in range(start + 1, len(src_lines)):
        ln = src_lines[j]
        if ln.startswith("def ") and _leading_spaces(ln) == 0:
            end = j
            break
        if ln.startswith("import ") and _leading_spaces(ln) == 0:
            end = j
            break
        if ln.startswith("from ") and _leading_spaces(ln) == 0:
            end = j
            break
    if end is None:
        end = len(src_lines)

    out = src_lines[:start] + new_block_lines + src_lines[end:]
    return out, None

def main():
    if not os.path.exists(TARGET):
        print("ERROR: {0} not found".format(TARGET))
        sys.exit(2)

    with io.open(TARGET, "r", encoding="utf-8") as f:
        lines = f.readlines()

    new_lines, err = replace_top_level_func(lines, "_news__format_voice_miniflux", NEW_FUNC)
    if err:
        print("ERROR:", err)
        sys.exit(3)

    bak = TARGET + ".bak.before_vB1_B3_fixfind"
    if not os.path.exists(bak):
        with io.open(bak, "w", encoding="utf-8") as f:
            f.writelines(lines)

    with io.open(TARGET, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    print("OK: patched _news__format_voice_miniflux; backup:", bak)

if __name__ == "__main__":
    main()
