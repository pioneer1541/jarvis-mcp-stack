#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import os
import re
import shutil
import time


def _read_text(path):
    with io.open(path, "r", encoding="utf-8") as f:
        return f.read()


def _write_text(path, s):
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(s)


def _backup(path):
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = path + ".bak.B8_2." + ts
    shutil.copy2(path, bak)
    return bak


def _find_def_block(src, func_name):
    """
    Find a function block (def/async def) by indentation scanning.
    Returns (start_idx, end_idx) in src; or (None, None).
    """
    lines = src.splitlines(True)
    pat = re.compile(r"^\s*(async\s+def|def)\s+" + re.escape(func_name) + r"\s*\(", re.M)
    m = pat.search(src)
    if not m:
        return (None, None)

    start_char = m.start()
    start_line = src[:start_char].count("\n")
    def_line = lines[start_line]
    indent = len(def_line) - len(def_line.lstrip(" "))

    i = start_line + 1
    n = len(lines)
    while i < n:
        ln = lines[i]
        if ln.strip() == "":
            i += 1
            continue
        cur_indent = len(ln) - len(ln.lstrip(" "))
        if cur_indent <= indent:
            s = ln.lstrip(" ")
            if s.startswith("def ") or s.startswith("async def ") or s.startswith("class ") or s.startswith("@"):
                break
        i += 1

    start_idx = sum(len(x) for x in lines[:start_line])
    end_idx = sum(len(x) for x in lines[:i])
    return (start_idx, end_idx)


def main():
    path = "app.py"
    if not os.path.exists(path):
        raise RuntimeError("app.py not found")

    src = _read_text(path)
    bak = _backup(path)

    a, b = _find_def_block(src, "_news__dedupe_items_for_voice")
    if a is None:
        raise RuntimeError("Cannot find _news__dedupe_items_for_voice()")

    new_func = r'''
def _news__dedupe_items_for_voice(items: list) -> list:
    """
    Dedupe near-duplicate news items for voice.

    Strategy (strong -> weak):
      1) URL canonical key:
         - remove scheme/host/query
         - remove '/video/' segment
      2) Normalized title key (remove punctuation, remove video tokens, collapse spaces)

    Preference:
      - Prefer non-video item over video item when duplicates detected.
    """
    try:
        if not isinstance(items, list) or len(items) == 0:
            return items

        def _is_video(x: dict) -> bool:
            try:
                t = str(x.get("title") or "").lower()
                tv = str(x.get("title_voice") or "").lower()
                u = str(x.get("url") or "").lower()
                if "/video/" in u:
                    return True
                if "– video" in t or "— video" in t or "- video" in t:
                    return True
                if "video" in t or "video" in tv or "视频" in (x.get("title_voice") or ""):
                    return True
            except Exception:
                pass
            return False

        def _canon_url(u: str) -> str:
            u = (u or "").strip()
            if not u:
                return ""
            u = u.split("#", 1)[0]
            u = u.split("?", 1)[0]
            # drop scheme
            u = re.sub(r"^https?://", "", u, flags=re.I)
            # drop host (keep path)
            p = u.find("/")
            if p >= 0:
                u = u[p:]
            # remove /video/ segment (guardian etc.)
            u = u.replace("/video/", "/")
            u = u.rstrip("/")
            return u

        def _norm_title(s: str) -> str:
            s = (s or "").strip().lower()
            s = s.replace("— video", " ").replace("– video", " ").replace("- video", " ")
            s = s.replace("video", " ").replace("视频", " ")
            s = re.sub(r"[\u2018\u2019\u201c\u201d\"'“”‘’\(\)\[\]\{\}]", " ", s)
            s = re.sub(r"[^\w\u4e00-\u9fff]+", " ", s)
            s = re.sub(r"\s+", " ", s).strip()
            return s

        out = []
        seen = {}  # key -> index in out

        for x in items:
            if not isinstance(x, dict):
                continue

            url_key = _canon_url(str(x.get("url") or ""))
            title_key = _norm_title(str(x.get("title_voice") or x.get("title") or ""))

            # build candidate keys (url first, then title)
            keys = []
            if url_key:
                keys.append("u:" + url_key)
            if title_key:
                keys.append("t:" + title_key)

            hit_idx = None
            for k in keys:
                if k in seen:
                    hit_idx = seen[k]
                    break

            if hit_idx is None:
                seen_keys = keys[:] if keys else []
                out.append(x)
                idx = len(out) - 1
                for k in seen_keys:
                    seen[k] = idx
                continue

            # duplicate: prefer non-video
            try:
                old = out[hit_idx]
                if _is_video(old) and (not _is_video(x)):
                    out[hit_idx] = x
            except Exception:
                pass

        return out
    except Exception:
        return items
'''.lstrip("\n")

    src2 = src[:a] + new_func + "\n" + src[b:]
    _write_text(path, src2)
    print("OK: patched _news__dedupe_items_for_voice. backup:", bak)


if __name__ == "__main__":
    main()
