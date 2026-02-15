#!/usr/bin/env python3
import os
import re
from datetime import datetime

APP_PATH = "app.py"

def _backup_file(path: str) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = path + ".bak.news_miniflux_v1." + ts
    with open(path, "rb") as fsrc:
        data = fsrc.read()
    with open(bak, "wb") as fdst:
        fdst.write(data)
    return bak

def _find_news_digest_block(lines):
    def_idx = None
    for i, ln in enumerate(lines):
        if re.match(r"^def\s+news_digest\s*\(", ln):
            def_idx = i
            break
    if def_idx is None:
        return None

    start = def_idx
    j = def_idx - 1
    while j >= 0:
        if lines[j].startswith("@") and not lines[j].startswith("@@"):
            start = j
            j -= 1
            continue
        break

    end = len(lines)
    for k in range(def_idx + 1, len(lines)):
        ln = lines[k]
        if re.match(r"^(def\s+\w+\s*\(|@mcp\.tool\b)", ln):
            end = k
            break
    return (start, end, def_idx)

def main():
    if not os.path.exists(APP_PATH):
        raise SystemExit("ERROR: cannot find app.py in current directory")

    with open(APP_PATH, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    blk = _find_news_digest_block(lines)
    if blk is None:
        raise SystemExit("ERROR: cannot find top-level def news_digest(...) in app.py")

    start, end, _ = blk

    new_block = r'''
@mcp.tool(
    name="news_digest",
    description="(Tool) News digest via Miniflux (RSS). Reads entries from the last 24 hours. Category-driven; default 5 items."
)
def news_digest(category: str = "world",
               limit: int = 5,
               time_range: str = "24h",
               prefer_lang: str = "zh",
               user_text: str = "",
               **kwargs) -> dict:
    """
    Miniflux-backed news digest.

    - Source of truth: Miniflux (RSS aggregator)
    - Window: last 24 hours (fixed)
    - Category mapping: Miniflux Categories (title contains key like 'world', 'world（世界新闻）', etc.)
    """

    base_url = os.environ.get("MINIFLUX_BASE_URL") or "http://192.168.1.162:19091"
    token = os.environ.get("MINIFLUX_API_TOKEN") or ""
    if not token.strip():
        return {
            "ok": False,
            "error": "MINIFLUX_API_TOKEN is not set",
            "category": category,
            "time_range": "24h",
            "limit": limit,
            "items": [],
            "final": "Miniflux API Token 未配置（MINIFLUX_API_TOKEN）。"
        }

    def _mf_req(path: str, params: dict | None = None) -> dict:
        url = base_url.rstrip("/") + path
        headers = {"X-Auth-Token": token}
        try:
            r = requests.get(url, headers=headers, params=(params or {}), timeout=12)
            if r.status_code >= 400:
                return {"ok": False, "status": r.status_code, "text": (r.text or "")[:500]}
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

    def _to_local_time(iso_str: str) -> str:
        if not iso_str:
            return ""
        try:
            dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
            tzname = os.environ.get("TZ") or "Australia/Melbourne"
            dt2 = dt.astimezone(ZoneInfo(tzname))
            return dt2.strftime("%Y-%m-%d %H:%M")
        except Exception:
            return iso_str

    cats = _mf_req("/v1/categories")
    if not cats.get("ok"):
        return {
            "ok": False,
            "error": "failed to fetch miniflux categories",
            "detail": cats,
            "category": category,
            "time_range": "24h",
            "limit": limit,
            "items": [],
            "final": "Miniflux categories 拉取失败。"
        }

    categories = cats.get("data") or []
    key = (category or "").strip()

    aliases_map = {
        "world": ["world（世界新闻）", "世界新闻", "国际"],
        "cn_finance": ["cn_finance（中国财经）", "中国财经", "财经", "中国经济"],
        "au_politics": ["au_politics（澳洲政治新闻）", "澳洲政治", "澳大利亚政治", "Australian politics"],
        "mel_life": ["mel_life（墨尔本民生）", "墨尔本民生", "维州民生", "Victoria"],
        "tech_internet": ["tech_internet（互联网科技）", "互联网科技", "科技", "Tech"],
        "tech_gadgets": ["tech_gadgets（数码产品）", "数码产品", "评测", "Gadgets"],
        "gaming": ["gaming（电子游戏）", "电子游戏", "游戏", "Gaming"],
    }

    def _match_cat_id(k: str):
        if not k:
            return None
        for c in categories:
            try:
                title = (c.get("title") or "").strip()
                if title == k:
                    return int(c.get("id"))
            except Exception:
                continue
        for c in categories:
            try:
                title = (c.get("title") or "").strip()
                if title.startswith(k) or (k in title):
                    return int(c.get("id"))
            except Exception:
                continue
        for al in (aliases_map.get(k) or []):
            for c in categories:
                try:
                    title = (c.get("title") or "").strip()
                    if (al in title) or title == al:
                        return int(c.get("id"))
                except Exception:
                    continue
        return None

    cat_id = _match_cat_id(key)
    if cat_id is None:
        return {
            "ok": True,
            "category": key,
            "time_range": "24h",
            "limit": limit,
            "items": [],
            "final": "Miniflux 中找不到对应分类：{0}".format(key),
            "query_used": "miniflux categories title match"
        }

    import time
    after_ts = int(time.time()) - 24 * 3600
    params = {
        "order": "published_at",
        "direction": "desc",
        "limit": int(limit) if int(limit) > 0 else 5,
        "after": after_ts,
    }

    ent = _mf_req("/v1/categories/{0}/entries".format(cat_id), params=params)
    if not ent.get("ok"):
        return {
            "ok": False,
            "error": "failed to fetch entries",
            "detail": ent,
            "category": key,
            "time_range": "24h",
            "limit": limit,
            "items": [],
            "final": "Miniflux entries 拉取失败。"
        }

    payload = ent.get("data") or {}
    entries = payload.get("entries") or []
    out_items = []
    for e in entries:
        try:
            title = (e.get("title") or "").strip()
            url = (e.get("url") or "").strip() or (e.get("comments_url") or "").strip()
            published_at = _to_local_time((e.get("published_at") or "").strip())
            feed = e.get("feed") or {}
            src = (feed.get("title") or "").strip()
            snippet = _strip_html((e.get("content") or "").strip())
            if len(snippet) > 160:
                snippet = snippet[:160].rstrip() + "..."
            out_items.append({
                "title": title,
                "url": url,
                "published_at": published_at,
                "source": src,
                "snippet": snippet,
            })
        except Exception:
            continue

    if not out_items:
        return {
            "ok": True,
            "category": key,
            "time_range": "24h",
            "limit": limit,
            "items": [],
            "final": "暂无符合最近24小时的条目。",
            "query_used": "miniflux category_id={0} after={1}".format(cat_id, after_ts),
        }

    lines = []
    for i, it in enumerate(out_items, 1):
        t = it.get("title") or ""
        u = it.get("url") or ""
        src = it.get("source") or ""
        pa = it.get("published_at") or ""
        sn = it.get("snippet") or ""
        lines.append("{0}) {1}".format(i, t))
        meta = []
        if src:
            meta.append(src)
        if pa:
            meta.append(pa)
        if meta:
            lines.append("   [{0}]".format(" | ".join(meta)))
        if sn:
            lines.append("   {0}".format(sn))
        if u:
            lines.append("   {0}".format(u))

    return {
        "ok": True,
        "category": key,
        "time_range": "24h",
        "limit": int(limit) if int(limit) > 0 else 5,
        "items": out_items,
        "final": "\n".join(lines),
        "query_used": "miniflux category_id={0} after={1}".format(cat_id, after_ts),
    }
'''.lstrip("\n")

    bak = _backup_file(APP_PATH)
    new_lines = lines[:start] + [new_block] + lines[end:]
    with open(APP_PATH, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    print("OK: replaced news_digest with Miniflux version")
    print("Backup:", bak)
    print("Replaced range: {0}:{1}".format(start, end))

if __name__ == "__main__":
    main()
