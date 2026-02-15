#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import os
import re
import shutil

APP = "app.py"
BAK = "app.py.bak.before_news_tail_strip_v2"

def read_text(p):
    with io.open(p, "r", encoding="utf-8") as f:
        return f.read()

def write_text(p, s):
    with io.open(p, "w", encoding="utf-8") as f:
        f.write(s)

def main():
    if not os.path.exists(APP):
        raise SystemExit("Missing " + APP)

    if not os.path.exists(BAK):
        shutil.copy2(APP, BAK)

    s = read_text(APP)

    # Locate _news__format_voice_miniflux and its inner _clean_title
    # We patch by inserting chinese-tail removals after the existing english video-tail removals.
    # Idempotent: only insert if not already present.
    if "def _news__format_voice_miniflux(" not in s:
        raise SystemExit("Cannot find _news__format_voice_miniflux")

    # If already patched, exit
    if "视频\\s*$" in s and "_clean_title" in s and "——\\s*视频" in s:
        print("OK: looks already patched for chinese video tail; no change.")
        return

    lines = s.splitlines(True)
    out = []
    in_func = False
    in_clean = False
    inserted = False

    for ln in lines:
        # enter function
        if ln.startswith("def _news__format_voice_miniflux("):
            in_func = True
            in_clean = False

        # leave function when next top-level def
        if in_func and (ln.startswith("def ") and (not ln.startswith("def _news__format_voice_miniflux("))):
            in_func = False
            in_clean = False

        if in_func and ("def _clean_title" in ln):
            in_clean = True

        # leave _clean_title when indentation drops back (helpful heuristic)
        if in_clean:
            # if we see a blank line followed by 4 spaces + something not indented to 8+,
            # we keep scanning; but we patch when we see the english video-tail line.
            pass

        out.append(ln)

        if in_func and in_clean and (not inserted):
            # Find the english "- video" removal line in _clean_title
            # Example line we inserted earlier:
            # t = re.sub(r"\s*[\-–—]\s*video\s*$", "", t, flags=re.I).strip()
            if re.search(r"re\.sub\(r\"\\s*\[\\\-.*video\\s*\$\"," , ln) or ("video\\s*$" in ln and "re.sub" in ln and "flags=re.I" in ln):
                # insert chinese tail removals right after this line
                indent = re.match(r"^(\s*)", ln).group(1)
                block = []
                block.append(indent + "t = re.sub(r\"\\s*[\\-\\u2013\\u2014\\u2212]\\s*视频\\s*$\", \"\", t).strip()\n")
                block.append(indent + "t = re.sub(r\"\\s*——\\s*视频\\s*$\", \"\", t).strip()\n")
                block.append(indent + "t = re.sub(r\"\\s*[（(]\\s*视频\\s*[)）]\\s*$\", \"\", t).strip()\n")
                block.append(indent + "t = re.sub(r\"\\s*【\\s*视频\\s*】\\s*$\", \"\", t).strip()\n")
                out.extend(block)
                inserted = True

    if not inserted:
        raise SystemExit("Cannot find insertion point inside _clean_title (english video-tail line not found).")

    s2 = "".join(out)
    write_text(APP, s2)
    print("OK: patched _clean_title() to strip chinese video tails. backup:", BAK)

if __name__ == "__main__":
    main()
