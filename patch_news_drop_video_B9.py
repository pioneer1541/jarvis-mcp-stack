#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import os
import re
import shutil
import sys
from datetime import datetime

APP = "app.py"


def _read(p):
    with io.open(p, "r", encoding="utf-8") as f:
        return f.read()


def _write(p, s):
    with io.open(p, "w", encoding="utf-8") as f:
        f.write(s)


def _backup(p):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = "{0}.bak.before_news_B9_{1}".format(p, ts)
    shutil.copy2(p, bak)
    return bak


def _has_def(src, name):
    pat = r"(?m)^[ \t]*def[ \t]+{0}[ \t]*\(".format(re.escape(name))
    return re.search(pat, src) is not None


def _insert_helper_before_news_digest(src):
    # Insert helper right before news_digest() definition
    m = re.search(r"(?m)^[ \t]*def[ \t]+news_digest[ \t]*\(", src)
    if not m:
        raise RuntimeError("Cannot find news_digest()")

    helper = (
        "\n\n"
        "def _news__is_video_entry(title: str, url: str) -> bool:\n"
        "    \"\"\"Return True if this entry is a video-type news item.\"\"\"\n"
        "    try:\n"
        "        t = (title or \"\").strip().lower()\n"
        "        u = (url or \"\").strip().lower()\n"
        "        if \"/video/\" in u:\n"
        "            return True\n"
        "        # common title suffix patterns\n"
        "        if \" - video\" in t or \" – video\" in t or \" — video\" in t:\n"
        "            return True\n"
        "        if t.endswith(\"video\") and len(t) <= 140:\n"
        "            return True\n"
        "        return False\n"
        "    except Exception:\n"
        "        return False\n"
    )

    return src[:m.start()] + helper + src[m.start():]


def _patch_news_digest_skip_video(src):
    # Find the specific place in news_digest where we build all_items from entries
    # and inject the video-skip guard right after title/url are read.
    target = (
        "            title = (e.get(\"title\") or \"\").strip()\n"
        "            url = (e.get(\"url\") or \"\").strip() or (e.get(\"comments_url\") or \"\").strip()\n"
    )

    if target not in src:
        raise RuntimeError("Cannot find insertion point for title/url in news_digest()")

    inject = (
        "            title = (e.get(\"title\") or \"\").strip()\n"
        "            url = (e.get(\"url\") or \"\").strip() or (e.get(\"comments_url\") or \"\").strip()\n"
        "            drop_video = (os.environ.get(\"NEWS_DROP_VIDEO\") or \"1\").strip().lower()\n"
        "            if drop_video not in (\"0\", \"false\", \"no\", \"off\"):\n"
        "                if _news__is_video_entry(title, url):\n"
        "                    continue\n"
    )

    return src.replace(target, inject, 1)


def main():
    if not os.path.exists(APP):
        raise RuntimeError("Cannot find {0}".format(APP))

    src = _read(APP)
    bak = _backup(APP)

    if not _has_def(src, "_news__is_video_entry"):
        src = _insert_helper_before_news_digest(src)

    src = _patch_news_digest_skip_video(src)

    _write(APP, src)
    print("OK: drop video news entries. backup:", bak)


if __name__ == "__main__":
    main()
