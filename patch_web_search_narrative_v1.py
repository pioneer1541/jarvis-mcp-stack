#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import re

APP = "app.py"

def backup(path):
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = "{0}.bak.web_narrative_{1}".format(path, ts)
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    with open(bak, "w", encoding="utf-8") as f:
        f.write(src)
    return bak, src

def find_def_block(lines, name):
    pat = re.compile(r"^def\s+" + re.escape(name) + r"\s*\(")
    start = None
    for i, ln in enumerate(lines):
        if pat.match(ln):
            start = i
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("def ") and re.match(r"^def\s+\w", lines[j]):
            end = j
            break
    return (start, end)

def insert_after_def(lines, name, insert_text):
    blk = find_def_block(lines, name)
    if not blk:
        raise RuntimeError("def block not found: {0}".format(name))
    s, e = blk
    ins = insert_text.splitlines(True)
    lines[e:e] = ins
    return lines

def patch_route_web_branch(lines):
    blk = find_def_block(lines, "_route_request_impl")
    if not blk:
        raise RuntimeError("def block not found: _route_request_impl")
    s, e = blk
    block = lines[s:e]

    # locate web search branch we previously inserted by marker comment
    marker = "Semi-structured retrieval: web search"
    mpos = None
    for i, ln in enumerate(block):
        if marker in ln:
            mpos = i
            break
    if mpos is None:
        raise RuntimeError("web search marker not found in _route_request_impl")

    # within branch find items=... and final=... lines
    items_i = None
    final_i = None
    ret_i = None
    for i in range(mpos, min(len(block), mpos + 220)):
        if block[i].strip() == 'items = data.get("results") or []':
            items_i = i
        if "final = " in block[i] and ("out_lines" in block[i] or "\\n\".join(out_lines" in block[i]):
            final_i = i
        if block[i].lstrip().startswith("ret = {") and ret_i is None:
            ret_i = i
            # ret is after final. break later if we already saw items
        if (items_i is not None) and (final_i is not None) and (ret_i is not None) and (ret_i > final_i):
            break

    if items_i is None or ret_i is None:
        raise RuntimeError("cannot locate items/ret lines in web branch")

    # If already patched to narrative:
    look = "".join(block[items_i:ret_i])
    if "_web__render_narrative(" in look:
        return lines, False

    # Replace from items_i up to (but excluding) ret_i with narrative renderer
    indent = re.match(r"^(\s*)", block[items_i]).group(1)
    new_mid = []
    new_mid.append(indent + 'items = data.get("results") or []\n')
    new_mid.append(indent + "final = _web__render_narrative(q, items, lang)\n")
    new_mid.append(indent + "ret = {\"ok\": True, \"route_type\": \"semi_structured_web\", \"final\": final}\n")
    new_mid.append(indent + "if _route_return_data:\n")
    new_mid.append(indent + "    ret[\"data\"] = data\n")
    new_mid.append(indent + "return ret\n")

    # We must also remove the old block that already had ret/return, so:
    # Find the first 'ret = {' after items_i, and replace up to its 'return ret'
    # But safer: replace items_i .. ret_i-1 with our mid, and then skip the old ret block by
    # deleting the old ret..return lines if they exist immediately after ret_i.
    block[items_i:ret_i] = new_mid

    # Now, after insertion, there might be a duplicate old ret block still present (immediately after).
    # Remove a duplicated chunk starting at the next line that begins with 'ret = {' until 'return ret'.
    # Search forward a small window.
    start_dup = None
    end_dup = None
    for i in range(items_i + len(new_mid), min(len(block), items_i + len(new_mid) + 60)):
        if block[i].lstrip().startswith("ret = {"):
            start_dup = i
            break
    if start_dup is not None:
        for j in range(start_dup, min(len(block), start_dup + 80)):
            if block[j].strip() == "return ret":
                end_dup = j + 1
                break
    if start_dup is not None and end_dup is not None:
        del block[start_dup:end_dup]

    lines[s:e] = block
    return lines, True

def main():
    bak, src = backup(APP)
    lines = src.splitlines(True)

    # insert helper after _web__strip_search_prefix (idempotent)
    if "_web__render_narrative(" not in src:
        helper = r'''

def _web__render_narrative(query: str, items: list, lang: str) -> str:
    """
    Deterministic, low-hallucination voice-friendly renderer.
    - Only uses (title/url/snippet) from search results; no extra knowledge.
    - Cleans and truncates snippet; composes natural sentences.
    Env:
      - WEB_SEARCH_MAX_SOURCES (default 2)
      - WEB_SEARCH_INCLUDE_URLS (default false)
      - WEB_SEARCH_SNIPPET_MAX (default 180)
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
        # avoid reading too much punctuation
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

    if not picked:
        if str(lang or "").lower().startswith("zh"):
            return "我没有查到可靠的结果。你可以换个更具体的关键词再试一次。"
        return "I couldn't find reliable results. Try a more specific query."

    is_zh = str(lang or "").lower().startswith("zh")
    out = []

    # Compose 1-2 sentences; always attribute to source title to stay grounded.
    p1 = picked[0]
    t1 = p1.get("title") or "网页来源"
    s1 = p1.get("snippet") or ""
    if is_zh:
        if q:
            out.append("我查到关于「{0}」主要是这样说的：{1}（来源：{2}）".format(q, s1 or "该来源未提供摘要。", t1))
        else:
            out.append("我查到的要点是：{0}（来源：{1}）".format(s1 or "该来源未提供摘要。", t1))
    else:
        if q:
            out.append("Here's what I found about “{0}”: {1} (Source: {2})".format(q, s1 or "No snippet provided.", t1))
        else:
            out.append("What I found: {0} (Source: {1})".format(s1 or "No snippet provided.", t1))

    if len(picked) >= 2:
        p2 = picked[1]
        t2 = p2.get("title") or "another source"
        s2 = p2.get("snippet") or ""
        if is_zh:
            out.append("另外一个来源补充：{0}（来源：{1}）".format(s2 or "该来源未提供摘要。", t2))
        else:
            out.append("Another source adds: {0} (Source: {1})".format(s2 or "No snippet provided.", t2))

    if include_urls:
        # keep URLs at the end; useful for UI logs but can be annoying for voice
        urls = []
        for p in picked:
            u = p.get("url") or ""
            if u:
                urls.append(u)
        if urls:
            if is_zh:
                out.append("链接：" + "；".join(urls))
            else:
                out.append("Links: " + " ; ".join(urls))

    return " ".join([x for x in out if x]).strip()
'''
        lines = insert_after_def(lines, "_web__strip_search_prefix", helper)

    # patch route branch to use narrative renderer
    lines, changed = patch_route_web_branch(lines)

    with open(APP, "w", encoding="utf-8") as f:
        f.writelines(lines)

    print("OK patched:", APP)
    print("Backup:", bak)
    print("Changed route branch:", bool(changed))

if __name__ == "__main__":
    main()
