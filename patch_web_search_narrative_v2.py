#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import time

APP = "app.py"

def backup(path):
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = "{0}.bak.web_narrative_v2_{1}".format(path, ts)
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    with open(bak, "w", encoding="utf-8") as f:
        f.write(src)
    return bak, src

def find_def_block(lines, name):
    pat = re.compile(r"^def\s+" + re.escape(name) + r"\s*\(")
    s = None
    for i, ln in enumerate(lines):
        if pat.match(ln):
            s = i
            break
    if s is None:
        return None
    e = len(lines)
    for j in range(s + 1, len(lines)):
        if lines[j].startswith("def ") and re.match(r"^def\s+\w", lines[j]):
            e = j
            break
    return (s, e)

def insert_after_def(lines, name, insert_text):
    blk = find_def_block(lines, name)
    if not blk:
        raise RuntimeError("def block not found: {0}".format(name))
    s, e = blk
    ins = insert_text.splitlines(True)
    lines[e:e] = ins
    return lines

def ensure_renderer(lines, src_text):
    if "_web__render_narrative(" in src_text:
        return lines, False

    helper = r'''

def _web__render_narrative(query: str, items: list, lang: str) -> str:
    """
    Deterministic, low-hallucination, voice-friendly renderer.
    Only uses title/url/snippet from results; no extra facts.
    Env:
      - WEB_SEARCH_MAX_SOURCES (default 2, max 3)
      - WEB_SEARCH_INCLUDE_URLS (default false)
      - WEB_SEARCH_SNIPPET_MAX (default 180, max 320)
    """
    q = (query or "").strip()

    try:
        max_sources = int(os.getenv("WEB_SEARCH_MAX_SOURCES", "2"))
    except Exception:
        max_sources = 2
    if max_sources < 1:
        max_sources = 1
    if max_sources > 3:
        max_sources = 3

    include_urls = str(os.getenv("WEB_SEARCH_INCLUDE_URLS", "false")).strip().lower() in ["1", "true", "yes", "y", "on"]

    try:
        snip_max = int(os.getenv("WEB_SEARCH_SNIPPET_MAX", "180"))
    except Exception:
        snip_max = 180
    if snip_max < 80:
        snip_max = 80
    if snip_max > 320:
        snip_max = 320

    def _clean(s: str) -> str:
        s = str(s or "")
        try:
            import html as _html
            s = _html.unescape(s)
        except Exception:
            pass
        s = re.sub(r"\s+", " ", s).strip()
        s = s.replace("…", "...")
        return s

    def _pick(it):
        if not isinstance(it, dict):
            return None
        title = _clean(it.get("title") or "")
        url = _clean(it.get("url") or "")
        sn = _clean(it.get("snippet") or it.get("content") or "")
        if not title and not url and not sn:
            return None
        if sn and len(sn) > snip_max:
            sn = sn[:snip_max].rstrip(" ,;:，。") + "..."
        return {"title": title, "url": url, "snippet": sn}

    picked = []
    for it in (items or []):
        p = _pick(it)
        if p:
            picked.append(p)
        if len(picked) >= max_sources:
            break

    is_zh = str(lang or "").lower().startswith("zh")
    if not picked:
        return "我没有查到可靠的结果。你可以把关键词说得更具体一点再试一次。" if is_zh else "I couldn't find reliable results. Try a more specific query."

    out = []
    p1 = picked[0]
    t1 = p1.get("title") or ("网页来源" if is_zh else "a source")
    s1 = p1.get("snippet") or ("该来源未提供摘要。" if is_zh else "No snippet provided.")
    if is_zh:
        if q:
            out.append("我查到关于「{0}」主要是这样说的：{1}（来自：{2}）".format(q, s1, t1))
        else:
            out.append("我查到的要点是：{0}（来自：{1}）".format(s1, t1))
    else:
        if q:
            out.append("Here's what I found about “{0}”: {1} (From: {2})".format(q, s1, t1))
        else:
            out.append("What I found: {0} (From: {1})".format(s1, t1))

    if len(picked) >= 2:
        p2 = picked[1]
        t2 = p2.get("title") or ("另一个来源" if is_zh else "another source")
        s2 = p2.get("snippet") or ("该来源未提供摘要。" if is_zh else "No snippet provided.")
        out.append(("另外一个来源补充：" if is_zh else "Another source adds: ") + s2 + ("（来自：{0}）".format(t2) if is_zh else " (From: {0})".format(t2)))

    if include_urls:
        urls = []
        for p in picked:
            u = p.get("url") or ""
            if u:
                urls.append(u)
        if urls:
            out.append(("链接：" if is_zh else "Links: ") + ("；".join(urls) if is_zh else " ; ".join(urls)))

    return " ".join([x for x in out if x]).strip()
'''
    # insert after _web__strip_search_prefix for stable placement
    lines = insert_after_def(lines, "_web__strip_search_prefix", helper)
    return lines, True

def force_route_use_renderer(lines):
    blk = find_def_block(lines, "_route_request_impl")
    if not blk:
        raise RuntimeError("def block not found: _route_request_impl")
    s, e = blk
    block = lines[s:e]

    # Find the web-search branch by the unique route_type string
    # Insert 'final = _web__render_narrative(q, items, lang)' right before the ret dict line.
    changed = False
    for i in range(len(block)):
        if 'route_type": "semi_structured_web"' in block[i]:
            # ensure we are in the web branch, not elsewhere (still safe)
            # check if previous few lines already call renderer
            prev = "".join(block[max(0, i-6):i])
            if "_web__render_narrative(" in prev:
                break
            indent = re.match(r"^(\s*)", block[i]).group(1)
            block.insert(i, indent + "final = _web__render_narrative(q, items, lang)\n")
            changed = True
            break

    lines[s:e] = block
    return lines, changed

def main():
    bak, src = backup(APP)
    lines = src.splitlines(True)

    lines, c1 = ensure_renderer(lines, src)
    lines, c2 = force_route_use_renderer(lines)

    with open(APP, "w", encoding="utf-8") as f:
        f.writelines(lines)

    print("OK patched:", APP)
    print("Backup:", bak)
    print("Inserted renderer:", bool(c1))
    print("Forced route renderer:", bool(c2))

if __name__ == "__main__":
    main()
