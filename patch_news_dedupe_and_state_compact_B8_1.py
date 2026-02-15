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
    bak = path + ".bak.B8_1." + ts
    shutil.copy2(path, bak)
    return bak


def _find_top_level_def_block(src, func_name):
    """
    Robustly find a top-level function block, supporting:
      - def / async def
      - multiline signatures
      - return type annotations
    Returns (start_idx, end_idx) over src string; or (None, None).
    """
    lines = src.splitlines(True)

    # find def line index
    pat = re.compile(r"^\s*(async\s+def|def)\s+" + re.escape(func_name) + r"\s*\(", re.M)
    m = pat.search(src)
    if not m:
        return (None, None)

    # compute line number from char index
    start_char = m.start()
    upto = src[:start_char]
    start_line = upto.count("\n")

    # indent of def line
    def_line = lines[start_line]
    indent = len(def_line) - len(def_line.lstrip(" "))

    # walk forward to find the end of this def block
    i = start_line + 1
    n = len(lines)
    while i < n:
        ln = lines[i]
        if ln.strip() == "":
            i += 1
            continue

        cur_indent = len(ln) - len(ln.lstrip(" "))

        # A new top-level thing starts (same or less indent)
        if cur_indent <= indent:
            s = ln.lstrip(" ")
            if s.startswith("def ") or s.startswith("async def ") or s.startswith("class ") or s.startswith("@"):
                break
        i += 1

    # slice by char offsets
    start_idx = sum(len(x) for x in lines[:start_line])
    end_idx = sum(len(x) for x in lines[:i])
    return (start_idx, end_idx)


def _ensure_helper_route_compact(src):
    if "def _route__maybe_compact_return(" in src:
        return src

    helper = r'''
def _route__maybe_compact_return(ret: dict) -> dict:
    """
    If ROUTE_RETURN_DATA=0, return only {ok, route_type, final}.
    Default is returning full payload.
    """
    try:
        v = str(os.environ.get("ROUTE_RETURN_DATA") or "1").strip().lower()
        if v in ["0", "false", "no", "off"]:
            return {
                "ok": bool(ret.get("ok")),
                "route_type": ret.get("route_type"),
                "final": ret.get("final"),
            }
    except Exception:
        pass
    return ret
'''.lstrip("\n")

    # Insert after imports (best-effort): after first "import os" occurrence
    pos = src.find("import os")
    if pos >= 0:
        # insert after the line containing import os
        line_end = src.find("\n", pos)
        if line_end >= 0:
            insert_at = line_end + 1
            return src[:insert_at] + "\n" + helper + "\n" + src[insert_at:]

    # fallback: prepend
    return helper + "\n" + src


def _patch_structured_state_returns(src):
    """
    Wrap structured_state return dicts with _route__maybe_compact_return(...)
    so ROUTE_RETURN_DATA=0 really takes effect.
    """
    # Match patterns like:
    # return {"ok": True, "route_type": "structured_state", ...}
    # Keep it minimal and safe.
    pat = re.compile(r'return\s+(\{[^\n]*"route_type"\s*:\s*"structured_state"[^\n]*\})')

    def repl(m):
        return "return _route__maybe_compact_return(" + m.group(1) + ")"

    new_src, n = pat.subn(repl, src)
    return new_src, n


def _ensure_news_dedupe_helper(src):
    if "def _news__dedupe_items_for_voice(" in src:
        return src

    helper = r'''
def _news__dedupe_items_for_voice(items: list) -> list:
    """
    Dedupe near-duplicate news items for voice.
    - Prefer non-video items over video items when titles are the same after normalization.
    - Normalize: remove punctuation/quotes, strip 'video/视频', collapse spaces.
    """
    try:
        if not isinstance(items, list) or len(items) == 0:
            return items

        def _is_video(x: dict) -> bool:
            try:
                t = str(x.get("title_voice") or x.get("title") or "").lower()
                u = str(x.get("url") or "").lower()
                if "video" in t or "视频" in (x.get("title_voice") or ""):
                    return True
                if "/video/" in u:
                    return True
            except Exception:
                pass
            return False

        def _norm(s: str) -> str:
            s = (s or "").strip().lower()
            # drop common video tokens
            s = s.replace("— video", " ").replace("– video", " ").replace("- video", " ")
            s = s.replace("video", " ").replace("视频", " ")
            # remove quotes/brackets and punctuation
            s = re.sub(r"[\u2018\u2019\u201c\u201d\"'“”‘’\(\)\[\]\{\}]", " ", s)
            s = re.sub(r"[^\w\u4e00-\u9fff]+", " ", s)
            s = re.sub(r"\s+", " ", s).strip()
            return s

        seen = {}
        out = []
        for x in items:
            if not isinstance(x, dict):
                continue
            title = str(x.get("title_voice") or x.get("title") or "").strip()
            if not title:
                continue
            k = _norm(title)
            if not k:
                out.append(x)
                continue

            if k not in seen:
                seen[k] = len(out)
                out.append(x)
                continue

            # already have one: prefer non-video
            j = seen[k]
            try:
                old = out[j]
                if _is_video(old) and (not _is_video(x)):
                    out[j] = x
            except Exception:
                pass

        return out
    except Exception:
        return items
'''.lstrip("\n")

    # Insert near news helpers: after the first occurrence of "_news__"
    anchor = src.find("def _news__")
    if anchor >= 0:
        return src[:anchor] + helper + "\n" + src[anchor:]
    return helper + "\n" + src


def _patch_news_formatter_to_dedupe(src):
    """
    Try patch common formatter functions to dedupe before formatting.
    We patch whichever exists:
      - _news__format_voice_miniflux
      - _news__format_voice
    """
    candidates = ["_news__format_voice_miniflux", "_news__format_voice"]
    for fn in candidates:
        a, b = _find_top_level_def_block(src, fn)
        if a is None:
            continue
        block = src[a:b]

        # If already applied, skip
        if "_news__dedupe_items_for_voice(" in block:
            return src, 0

        # Heuristic: after line containing "it = items" or "it = items or []"
        lines = block.splitlines(True)
        out_lines = []
        inserted = False
        for ln in lines:
            out_lines.append(ln)
            if (not inserted) and re.search(r"\bit\s*=\s*items\b", ln) or re.search(r"\bit\s*=\s*items\s+or\s+\[\]", ln):
                out_lines.append("    it = _news__dedupe_items_for_voice(it)\n")
                inserted = True

        if not inserted:
            # fallback: insert near start of try block
            out2 = []
            done2 = False
            for ln in lines:
                out2.append(ln)
                if (not done2) and ln.strip().startswith("try:"):
                    out2.append("        items = _news__dedupe_items_for_voice(items)\n")
                    done2 = True
            out_lines = out2
            inserted = done2

        if inserted:
            new_block = "".join(out_lines)
            return src[:a] + new_block + src[b:], 1

    return src, 0


def main():
    path = "app.py"
    if not os.path.exists(path):
        raise RuntimeError("app.py not found in current directory")

    src = _read_text(path)
    bak = _backup(path)

    changed = 0

    # 1) route compact helper + structured_state compact
    src = _ensure_helper_route_compact(src)
    src2, n2 = _patch_structured_state_returns(src)
    src = src2
    changed += n2

    # 2) news dedupe helper + patch formatter
    src = _ensure_news_dedupe_helper(src)
    src3, n3 = _patch_news_formatter_to_dedupe(src)
    src = src3
    changed += n3

    if changed == 0:
        print("No changes applied. Backup at:", bak)
        print("Hint: verify formatter function name and structured_state return pattern.")
        return

    _write_text(path, src)
    print("OK: applied", changed, "patches. backup:", bak)


if __name__ == "__main__":
    main()
