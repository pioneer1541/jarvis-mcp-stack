#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import os
import shutil

APP = "app.py"
BAK = "app.py.bak.before_news_tail_strip_v3"

def _leading_spaces(line):
    i = 0
    while i < len(line) and line[i] == " ":
        i += 1
    return i

def main():
    if not os.path.exists(APP):
        raise SystemExit("Missing " + APP)

    if not os.path.exists(BAK):
        shutil.copy2(APP, BAK)

    with io.open(APP, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Find nested _clean_title inside _news__format_voice_miniflux
    start = None
    for i, ln in enumerate(lines):
        if ln.startswith("def _news__format_voice_miniflux("):
            # search forward for "    def _clean_title"
            for j in range(i + 1, min(i + 500, len(lines))):
                if lines[j].startswith("    def _clean_title("):
                    start = j
                    break
            break

    if start is None:
        # fallback: global search
        for i, ln in enumerate(lines):
            if ln.startswith("    def _clean_title("):
                start = i
                break

    if start is None:
        raise SystemExit("Cannot find nested '    def _clean_title('")

    # Determine end: first line after start with indent == 4 (and not blank) that is NOT part of _clean_title body
    end = None
    for k in range(start + 1, len(lines)):
        ln = lines[k]
        if ln.strip() == "":
            continue
        sp = _leading_spaces(ln)
        # body lines should be >= 8 spaces; when we return to 4 spaces we are out of nested function
        if sp == 4 and (not ln.startswith("    def _clean_title(")):
            end = k
            break

    if end is None:
        raise SystemExit("Cannot find end of nested _clean_title block")

    # Replace block with robust cleaner (EN + CN video tails)
    new_block = []
    new_block.append("    def _clean_title(s: str) -> str:\n")
    new_block.append("        t = (s or \"\").strip()\n")
    new_block.append("        if not t:\n")
    new_block.append("            return \"\"\n")
    new_block.append("        # Normalize whitespace\n")
    new_block.append("        try:\n")
    new_block.append("            t = re.sub(r\"\\s+\", \" \", t).strip()\n")
    new_block.append("        except Exception:\n")
    new_block.append("            t = (s or \"\").strip()\n")
    new_block.append("\n")
    new_block.append("        # Remove EN tail: -/–/— video, (video), [video]\n")
    new_block.append("        try:\n")
    new_block.append("            t = re.sub(r\"\\s*[\\-\\u2013\\u2014\\u2212]+\\s*video\\s*$\", \"\", t, flags=re.I).strip()\n")
    new_block.append("            t = re.sub(r\"\\s*[\\(\\[]\\s*video\\s*[\\)\\]]\\s*$\", \"\", t, flags=re.I).strip()\n")
    new_block.append("        except Exception:\n")
    new_block.append("            pass\n")
    new_block.append("\n")
    new_block.append("        # Remove CN tail: -/–/—/—— 视频, （视频）,【视频】,(视频)\n")
    new_block.append("        try:\n")
    new_block.append("            t = re.sub(r\"\\s*——\\s*视频\\s*$\", \"\", t).strip()\n")
    new_block.append("            t = re.sub(r\"\\s*[\\-\\u2013\\u2014\\u2212]+\\s*视频\\s*$\", \"\", t).strip()\n")
    new_block.append("            t = re.sub(r\"\\s*（\\s*视频\\s*）\\s*$\", \"\", t).strip()\n")
    new_block.append("            t = re.sub(r\"\\s*【\\s*视频\\s*】\\s*$\", \"\", t).strip()\n")
    new_block.append("            t = re.sub(r\"\\s*\\(\\s*视频\\s*\\)\\s*$\", \"\", t).strip()\n")
    new_block.append("        except Exception:\n")
    new_block.append("            pass\n")
    new_block.append("\n")
    new_block.append("        # Final trim\n")
    new_block.append("        return (t or \"\").strip()\n")
    new_block.append("\n")

    out = lines[:start] + new_block + lines[end:]

    with io.open(APP, "w", encoding="utf-8") as f:
        f.writelines(out)

    print("OK: replaced nested _clean_title block. backup:", BAK, "range:", start + 1, "-", end)

if __name__ == "__main__":
    main()
