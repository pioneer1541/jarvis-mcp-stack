#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import time

APP = "app.py"

def backup(path):
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = "{0}.bak.web_narrative_style_v3_{1}".format(path, ts)
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    with open(bak, "w", encoding="utf-8") as f:
        f.write(src)
    return bak

def replace_function(src, func_name, new_block):
    # Find "def func_name(" at column 0
    pat = re.compile(r"^def\s+" + re.escape(func_name) + r"\s*\(", re.MULTILINE)
    m = pat.search(src)
    if not m:
        raise RuntimeError("function not found: {0}".format(func_name))
    start = m.start()

    # Find the next top-level def after start
    m2 = re.compile(r"^def\s+\w+\s*\(", re.MULTILINE).search(src, m.end())
    end = m2.start() if m2 else len(src)

    return src[:start] + new_block + src[end:], (src[start:end], new_block)

def main():
    bak = backup(APP)

    with open(APP, "r", encoding="utf-8") as f:
        src = f.read()

    new_func = r'''def _web__render_narrative(query: str, items: list, lang: str) -> str:
    # Deterministic, low-hallucination, voice-friendly renderer.
    # Only uses title/url/snippet from results; no extra facts.
    # Env:
    #   WEB_SEARCH_MAX_SOURCES (default 2, max 3)
    #   WEB_SEARCH_INCLUDE_URLS (default false)
    #   WEB_SEARCH_SNIPPET_MAX (default 180, max 320)

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
        # unescape HTML entities
        try:
            import html as _html
            s = _html.unescape(s)
        except Exception:
            pass
        # strip HTML tags like <strong>
        s = re.sub(r"<[^>]+>", "", s)
        # normalize separators/bullets
        s = s.replace("·", " ")
        s = s.replace("…", "...")
        # collapse whitespace
        s = re.sub(r"\s+", " ", s).strip()
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
        return "我没找到特别靠谱的结果，你可以把关键词说得更具体一点再试一次。" if is_zh else "I couldn't find reliable results. Try a more specific query."

    def _title_brief(t):
        t = (t or "").strip()
        if not t:
            return "网页" if is_zh else "a page"
        # keep it short for TTS
        if len(t) > 48:
            t = t[:48].rstrip(" -—|") + "..."
        return t

    out = []
    p1 = picked[0]
    t1 = _title_brief(p1.get("title") or "")
    s1 = (p1.get("snippet") or "").strip()
    if not s1:
        s1 = "这条结果没有给摘要。" if is_zh else "This result did not include a snippet."

    if is_zh:
        if q:
            out.append("关于「{0}」，资料里一般这样描述：{1}（{2}）。".format(q, s1, t1))
        else:
            out.append("资料里一般这样描述：{0}（{1}）。".format(s1, t1))
    else:
        if q:
            out.append("About “{0}”, sources generally describe it like this: {1} ({2}).".format(q, s1, t1))
        else:
            out.append("Sources describe it like this: {0} ({1}).".format(s1, t1))

    if len(picked) >= 2:
        p2 = picked[1]
        t2 = _title_brief(p2.get("title") or "")
        s2 = (p2.get("snippet") or "").strip()
        if not s2:
            s2 = "这条结果没有给摘要。" if is_zh else "This result did not include a snippet."
        if is_zh:
            out.append("再补充一个角度：{0}（{1}）。".format(s2, t2))
        else:
            out.append("Another angle: {0} ({1}).".format(s2, t2))

    if include_urls:
        urls = []
        for p in picked:
            u = (p.get("url") or "").strip()
            if u:
                urls.append(u)
        if urls:
            out.append(("链接：" if is_zh else "Links: ") + ("；".join(urls) if is_zh else " ; ".join(urls)))

    return " ".join([x for x in out if x]).strip()


'''
    new_src, _ = replace_function(src, "_web__render_narrative", new_func)

    with open(APP, "w", encoding="utf-8") as f:
        f.write(new_src)

    print("OK patched:", APP)
    print("Backup:", bak)

if __name__ == "__main__":
    main()
