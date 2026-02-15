#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import shutil
import datetime

MARKER = "PATCH_NEWS_HOT_V1"

HOT_FUNC = r'''
# PATCH_NEWS_HOT_V1
def news_hot(limit: int = 10,
             time_range: str = "24h",
             prefer_lang: str = "en",
             user_text: str = "",
             **kwargs) -> dict:
    """Miniflux 热门新闻（跨所有分类聚合，默认最近24小时，取前 N 条，标题+摘要）。
    说明：
    - 不做翻译（按 Miniflux 原始语言输出）
    - 只做去重 + 简要摘要截断
    """
    base_url = os.environ.get("MINIFLUX_BASE_URL") or "http://192.168.1.162:19091"
    token = os.environ.get("MINIFLUX_API_TOKEN") or ""
    if not token.strip():
        return {"ok": False, "error": "MINIFLUX_API_TOKEN is not set", "items": [], "final": "Miniflux API Token 未配置（MINIFLUX_API_TOKEN）。"}

    def _mf_req(path: str, params: dict = None) -> dict:
        url = base_url.rstrip("/") + path
        headers = {"X-Auth-Token": token}
        try:
            r = requests.get(url, headers=headers, params=(params or {}), timeout=8)
            if int(getattr(r, "status_code", 0) or 0) >= 400:
                return {"ok": False, "status": int(r.status_code), "text": (r.text or "")[:500]}
            return {"ok": True, "data": r.json()}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _strip_html(s: str) -> str:
        if not s:
            return ""
        try:
            s2 = re.sub(r"<[^>]+>", " ", s)
            s2 = html.unescape(s2)
            s2 = re.sub(r"\s+", " ", s2).strip()
            return s2
        except Exception:
            return (s or "").strip()

    import time as _time
    after_ts = int(_time.time()) - 24 * 3600

    try:
        lim_int = int(limit)
    except Exception:
        lim_int = 10
    if lim_int < 1:
        lim_int = 1
    if lim_int > 10:
        lim_int = 10

    try:
        sn_lim = int(os.environ.get("NEWS_SNIPPET_CHARS") or "220")
    except Exception:
        sn_lim = 220
    if sn_lim < 80:
        sn_lim = 80
    if sn_lim > 600:
        sn_lim = 600

    fetch_lim = lim_int * 10
    if fetch_lim < 40:
        fetch_lim = 40
    if fetch_lim > 120:
        fetch_lim = 120

    # 优先尝试 /v1/entries（单次请求更快）；失败则回退到按分类聚合
    params = {"order": "published_at", "direction": "desc", "limit": fetch_lim, "after": after_ts}
    ent = _mf_req("/v1/entries", params=params)

    entries = []
    if ent.get("ok"):
        payload = ent.get("data") or {}
        entries = payload.get("entries") or []
    else:
        cats = _mf_req("/v1/categories")
        if cats.get("ok"):
            categories = cats.get("data") or []
            for c in categories:
                try:
                    cid = c.get("id")
                    if cid is None:
                        continue
                    e2 = _mf_req("/v1/categories/{0}/entries".format(cid), params={"order": "published_at", "direction": "desc", "limit": 10, "after": after_ts})
                    if not e2.get("ok"):
                        continue
                    payload2 = e2.get("data") or {}
                    es = payload2.get("entries") or []
                    if es:
                        entries.extend(es)
                except Exception:
                    continue

    if not entries:
        return {"ok": True, "items": [], "final": "暂无符合最近24小时的条目。"}

    # 组装 items（标题 + 摘要）
    items = []
    drop_video = (os.environ.get("NEWS_DROP_VIDEO") or "1").strip().lower()
    for e in entries:
        try:
            title = (e.get("title") or "").strip()
            url = (e.get("url") or "").strip() or (e.get("comments_url") or "").strip()
            if drop_video not in ("0", "false", "no", "off"):
                if _news__is_video_entry(title, url):
                    continue
            feed = e.get("feed") or {}
            src = (feed.get("title") or "").strip()
            content_plain = _strip_html((e.get("content") or "").strip())
            snippet = content_plain
            if len(snippet) > sn_lim:
                snippet = snippet[:sn_lim].rstrip() + "..."
            items.append({"title": title, "url": url, "source": src, "snippet": snippet, "content_plain": content_plain})
        except Exception:
            continue

    # 去重 + 截断到 N 条
    try:
        items = _news__dedupe_items_for_voice(items)
    except Exception:
        pass
    if len(items) > lim_int:
        items = items[:lim_int]

    # 拼 final（标题 + 摘要）
    lines = []
    i = 0
    for it in items:
        i += 1
        t = (it.get("title") or "").strip()
        sn = (it.get("snippet") or "").strip()
        if sn:
            lines.append("{0}) {1}\n   {2}".format(i, t, sn))
        else:
            lines.append("{0}) {1}".format(i, t))

    final = "\n".join(lines).strip()
    return {"ok": True, "items": items, "final": final, "final_voice": final}
'''.lstrip("\n")

def die(msg: str, code: int = 1):
    print("ERROR:", msg)
    sys.exit(code)

def main():
    path = os.path.join(os.getcwd(), "app.py")
    if not os.path.exists(path):
        die("app.py not found in current directory")

    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    if MARKER in src:
        print("SKIP: already patched ({0})".format(MARKER))
        return

    # 1) backup
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = "app.py.bak.hot_news_v1.{0}".format(ts)
    shutil.copyfile(path, bak)
    print("OK: backup ->", bak)

    # 2) insert news_hot before news_digest
    idx = src.find("def news_digest(")
    if idx < 0:
        die("cannot find def news_digest(")

    src = src[:idx] + HOT_FUNC + "\n\n" + src[idx:]
    print("OK: inserted news_hot() before news_digest()")

    # 3) patch _news__category_from_text: add hot detection
    anchor = "def _news__category_from_text(text: str) -> str:"
    i2 = src.find(anchor)
    if i2 >= 0:
        block = src[i2:i2+1200]
        if 'return "hot"' not in block:
            tl_line = "    tl = t.lower()"
            j = src.find(tl_line, i2)
            if j >= 0:
                line_end = src.find("\n", j)
                ins = '\n\n    # hot / trending\n    if ("热门" in t) or ("热搜" in t) or ("头条" in t) or ("热点" in t) or ("trending" in tl) or ("hot news" in tl):\n        return "hot"\n'
                src = src[:line_end] + ins + src[line_end:]
                print("OK: patched _news__category_from_text() for hot keywords")
            else:
                print("WARN: cannot find 'tl = t.lower()' in _news__category_from_text()")
        else:
            print("SKIP: _news__category_from_text() already has hot")
    else:
        print("WARN: cannot find _news__category_from_text()")

    # 4) patch route news branch: if cat == "hot" -> news_hot(limit=10)
    lines = src.splitlines(True)
    out = []
    replaced = False
    for ln in lines:
        if (not replaced) and ln.lstrip().startswith("rrn = news_digest(") and ("user_text=user_text" in ln):
            indent = ln[:len(ln) - len(ln.lstrip())]
            out.append(indent + 'if cat == "hot":\n')
            out.append(indent + '    rrn = news_hot(limit=10, time_range=tr, prefer_lang=prefer_lang, user_text=user_text)\n')
            out.append(indent + "else:\n")
            out.append(indent + "    " + ln.lstrip())
            replaced = True
        else:
            out.append(ln)

    src2 = "".join(out)
    if replaced:
        src = src2
        print("OK: patched route_request news branch to support hot")
    else:
        print("WARN: could not find rrn = news_digest(...) line to patch")

    with open(path, "w", encoding="utf-8") as f:
        f.write(src)

    print("OK: patched app.py")

if __name__ == "__main__":
    main()
