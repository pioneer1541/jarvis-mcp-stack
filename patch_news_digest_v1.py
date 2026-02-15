import io
import re

SRC = "app.py"

BEGIN = "# --- NEWS_DIGEST_V1 BEGIN ---"
END = "# --- NEWS_DIGEST_V1 END ---"

NEWS_BLOCK = r'''
# --- NEWS_DIGEST_V1 BEGIN ---
# Semi-structured retrieval: News digest via local SearXNG + domain allow-list.
# Goal: config-driven source pools; Chinese-first with minimal English fallback.

NEWS_SOURCES = {
    "world": {
        "zh": [
            "thepaper.cn",
            "caixin.com",
            "ifeng.com",
            "bbc.com/zhongwen",
            "bbc.com/zh",
            "dw.com/zh",
            "dw.com/zh-hans",
        ],
        "en": [
            "reuters.com",
            "apnews.com",
            "bbc.com",
            "theguardian.com",
            "aljazeera.com",
        ],
    },
    "cn_finance": {
        "zh": [
            "caixin.com",
            "yicai.com",
        ],
        "en": [
            "reuters.com",
        ],
    },
    "au_politics": {
        "zh": [
            "sbs.com.au/language/chinese",
            "abc.net.au/chinese",
        ],
        "en": [
            "abc.net.au",
            "sbs.com.au/news",
            "theguardian.com/au",
            "aph.gov.au",
            "aec.gov.au",
            "pm.gov.au",
            "minister.homeaffairs.gov.au",
            "homeaffairs.gov.au",
            "treasury.gov.au",
        ],
    },
    "mel_life": {
        "zh": [
            "sbs.com.au/language/chinese",
            "abc.net.au/chinese",
        ],
        "en": [
            "abc.net.au",
            "9news.com.au",
            "melbourne.vic.gov.au",
        ],
        "region_keywords": ["Melbourne", "Victoria", "VIC"],
    },
    "tech_internet": {
        "zh": [
            "36kr.com",
            "huxiu.com",
        ],
        "en": [
            "theverge.com",
            "techcrunch.com",
            "wired.com",
            "arstechnica.com",
        ],
    },
    "tech_gadgets": {
        "zh": [
            "sspai.com",
            "ifanr.com",
        ],
        "en": [
            "theverge.com",
        ],
    },
    "gaming": {
        "zh": [
            "gcores.com",
        ],
        "en": [
            "ign.com",
            "pcgamer.com",
        ],
    },
}

NEWS_QUERIES = {
    "world": ["国际 要闻", "全球 局势", "联合国", "中东", "俄乌", "欧盟", "美国 政策"],
    "cn_finance": ["中国 财经", "A股", "央行", "人民币", "地产", "通胀", "监管"],
    "au_politics": ["Australia politics", "Federal parliament", "budget", "immigration", "housing policy"],
    "mel_life": ["Melbourne update", "Victoria news", "traffic", "train disruption", "police", "fire", "storm"],
    "tech_internet": ["互联网 科技", "AI 大模型", "开源", "隐私 监管", "云计算", "芯片"],
    "tech_gadgets": ["数码 新品", "手机 发布", "评测 上手", "相机", "耳机", "笔记本"],
    "gaming": ["游戏 新闻", "Steam", "主机", "任天堂", "PlayStation", "Xbox", "更新 补丁 DLC"],
}


def _news__is_query(text: str) -> bool:
    t = str(text or "")
    tl = t.lower()
    keys = ["新闻", "要闻", "热点", "快讯", "头条", "发生了什么", "怎么回事", "最新消息", "news", "breaking"]
    for k in keys:
        if k in t or k in tl:
            return True
    cats = ["世界", "国际", "中国", "财经", "金融", "澳洲", "澳大利亚", "政治", "墨尔本", "维州", "本地", "民生", "互联网", "科技", "数码", "产品", "游戏", "电竞"]
    for k in cats:
        if k in t:
            return True
    return False


def _news__category_from_text(text: str) -> str:
    t = str(text or "")
    tl = t.lower()

    if ("墨尔本" in t) or ("维州" in t) or ("melbourne" in tl) or ("victoria" in tl):
        if ("民生" in t) or ("本地" in t) or ("交通" in t) or ("警" in t) or ("灾" in t) or ("life" in tl) or ("local" in tl):
            return "mel_life"
        if ("政治" in t) or ("parliament" in tl) or ("election" in tl) or ("budget" in tl):
            return "au_politics"
        return "mel_life"

    if ("澳洲" in t) or ("澳大利亚" in t) or ("australia" in tl) or ("australian" in tl):
        if ("政治" in t) or ("parliament" in tl) or ("election" in tl) or ("pm" in tl) or ("prime minister" in tl) or ("budget" in tl):
            return "au_politics"
        if ("本地" in t) or ("民生" in t):
            return "mel_life"
        return "au_politics"

    if ("中国" in t) and (("财经" in t) or ("金融" in t) or ("股" in t) or ("债" in t) or ("人民币" in t)):
        return "cn_finance"
    if ("财经" in t) or ("金融" in t) or ("a股" in tl) or ("csi" in tl) or ("hang seng" in tl):
        return "cn_finance"

    if ("互联网" in t) or ("云" in t) or ("ai" in tl) or ("openai" in tl) or ("privacy" in tl) or ("监管" in t):
        return "tech_internet"
    if ("数码" in t) or ("手机" in t) or ("相机" in t) or ("耳机" in t) or ("笔记本" in t) or ("评测" in t) or ("新品" in t):
        return "tech_gadgets"
    if ("游戏" in t) or ("电竞" in t) or ("steam" in tl) or ("ps5" in tl) or ("xbox" in tl) or ("switch" in tl):
        return "gaming"

    if ("世界" in t) or ("国际" in t) or ("global" in tl) or ("world" in tl):
        return "world"

    return "world"


def _news__time_range_from_text(text: str) -> str:
    t = str(text or "")
    tl = t.lower()
    if ("本周" in t) or ("这一周" in t) or ("过去一周" in t) or ("week" in tl):
        return "week"
    if ("本月" in t) or ("过去一个月" in t) or ("month" in tl):
        return "month"
    return "day"


def _news__site_filter(domains):
    ds = []
    for d in domains or []:
        dd = str(d or "").strip()
        if dd:
            ds.append(dd)
    if not ds:
        return ""
    parts = []
    for d in ds[:10]:
        parts.append("site:" + d)
    if len(parts) == 1:
        return parts[0]
    return "(" + " OR ".join(parts) + ")"


def _news__pick_results(results, allow_domains):
    out = []
    seen = set()
    allow = []
    for d in allow_domains or []:
        allow.append(str(d or "").strip())
    for it in results or []:
        if not isinstance(it, dict):
            continue
        url = str(it.get("url") or "").strip()
        title = str(it.get("title") or "").strip()
        sn = str(it.get("snippet") or "").strip()
        if (not url) or (not title):
            continue
        ok_domain = False
        for d in allow:
            if d and (d in url):
                ok_domain = True
                break
        if not ok_domain and allow:
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append({"title": title, "url": url, "snippet": sn})
        if len(out) >= 12:
            break
    return out


def _news__summarise_item(snippet, fallback_title):
    s = str(snippet or "").strip()
    if len(s) >= 30:
        s = re.sub(r"\\s+", " ", s).strip()
        return s[:160]
    t = str(fallback_title or "").strip()
    if t:
        return t[:80]
    return "（摘要缺失）"


def _news__source_from_url(url):
    u = str(url or "").strip()
    if not u:
        return ""
    try:
        x = re.sub(r"^https?://", "", u).strip()
        x = x.split("/")[0].strip()
        return x
    except Exception:
        return ""


def _news__build_query(category, lang, user_text):
    c = str(category or "").strip()
    if not c:
        c = "world"
    base = str(user_text or "").strip()
    if base:
        if len(base) > 120:
            base = base[:120]
        return base

    qs = NEWS_QUERIES.get(c) or []
    if not qs:
        qs = ["news"]
    return str(qs[0])


def _news__search_one(category, lang, time_range, user_text):
    c = str(category or "").strip()
    lg = str(lang or "").strip()
    tr = str(time_range or "").strip()
    base_url = str(os.getenv("SEARXNG_URL", "http://192.168.1.162:8081")).strip()

    src = NEWS_SOURCES.get(c) or {}
    domains = src.get(lg) or []
    q = _news__build_query(c, lg, user_text)
    sf = _news__site_filter(domains)

    query = q
    if sf:
        query = q + " " + sf

    r = web_search(query=query, k=10, categories="news", language=("zh-CN" if lg == "zh" else "en"), time_range=tr)
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error"), "message": r.get("message"), "query": query}
    picked = _news__pick_results(r.get("results") or [], domains)
    return {"ok": True, "query": query, "picked": picked}


def _news__format_digest(items, limit):
    it = items or []
    try:
        lim = int(limit)
    except Exception:
        lim = 5
    if lim < 1:
        lim = 1
    if lim > 10:
        lim = 10
    if (not isinstance(it, list)) or (len(it) == 0):
        return "暂无符合来源池的新闻结果。"

    out = []
    idx = 1
    for x in it[:lim]:
        if not isinstance(x, dict):
            continue
        title = str(x.get("title") or "").strip()
        url = str(x.get("url") or "").strip()
        src = str(x.get("source") or "").strip()
        summ = str(x.get("summary") or "").strip()
        if not src:
            src = _news__source_from_url(url)
        if not summ:
            summ = _news__summarise_item(x.get("snippet"), title)
        line = str(idx) + ") " + title
        if src:
            line = line + "（" + src + "）"
        out.append(line)
        out.append("   " + summ)
        idx += 1
    return "\\n".join(out).strip()


@mcp.tool(description="News digest via local SearXNG + curated source pools. Chinese-first; minimal English fallback.")
def news_digest(category: str = "world", limit: int = 5, time_range: str = "day", prefer_lang: str = "zh", user_text: str = "") -> dict:
    c = str(category or "").strip()
    if not c:
        c = "world"
    if c not in NEWS_SOURCES:
        c = "world"

    tr = str(time_range or "").strip()
    if tr not in ("day", "week", "month", "year"):
        tr = "day"

    pl = str(prefer_lang or "").strip().lower()
    if pl not in ("zh", "en"):
        pl = "zh"

    # 1) Chinese-first search
    items = []
    r1 = _news__search_one(category=c, lang=("zh" if pl == "zh" else "en"), time_range=tr, user_text=user_text)
    if r1.get("ok"):
        for it in r1.get("picked") or []:
            if not isinstance(it, dict):
                continue
            url = str(it.get("url") or "").strip()
            title = str(it.get("title") or "").strip()
            snippet = str(it.get("snippet") or "").strip()
            items.append({
                "title": title,
                "url": url,
                "snippet": snippet,
                "source": _news__source_from_url(url),
                "summary": _news__summarise_item(snippet, title),
                "lang": ("zh" if pl == "zh" else "en"),
            })

    # 2) Minimal English fallback if needed
    if len(items) < 4:
        r2 = _news__search_one(category=c, lang=("en" if pl == "zh" else "zh"), time_range=tr, user_text=user_text)
        if r2.get("ok"):
            for it in r2.get("picked") or []:
                if not isinstance(it, dict):
                    continue
                url = str(it.get("url") or "").strip()
                title = str(it.get("title") or "").strip()
                snippet = str(it.get("snippet") or "").strip()
                items.append({
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                    "source": _news__source_from_url(url),
                    "summary": _news__summarise_item(snippet, title),
                    "lang": ("en" if pl == "zh" else "zh"),
                })

    # 3) Light post-filter for Melbourne local
    if c == "mel_life":
        src = NEWS_SOURCES.get(c) or {}
        rk = (src.get("region_keywords") or [])
        keep = []
        for x in items:
            txt = (str(x.get("title") or "") + " " + str(x.get("summary") or "")).lower()
            ok = False
            for kw in rk:
                if str(kw or "").lower() in txt:
                    ok = True
                    break
            if ok:
                keep.append(x)
        if len(keep) >= 2:
            items = keep

    final = _news__format_digest(items, limit)
    return {
        "ok": True,
        "category": c,
        "time_range": tr,
        "limit": limit,
        "final": final,
        "items": items[:12],
        "q1": (r1.get("query") if isinstance(r1, dict) else ""),
    }

# --- NEWS_DIGEST_V1 END ---
'''

def _read(path):
    with io.open(path, "r", encoding="utf-8") as f:
        return f.read()

def _write(path, s):
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(s)

def main():
    s = _read(SRC)
    if BEGIN in s and END in s:
        print("already_patched")
        return

    m = re.search(r"\n@mcp\\.tool\\(description=\"\\(Router\\)", s)
    if not m:
        raise RuntimeError("cannot_find_route_request_decorator_anchor")

    insert_at = m.start()
    s2 = s[:insert_at] + "\n\n" + NEWS_BLOCK.strip() + "\n\n" + s[insert_at:]

    m2 = re.search(r"def\\s+route_request\\(.*?\\):([\\s\\S]*?)\\n\\s*return\\s+\\{\"ok\":\\s*True,\\s*\"route_type\":\\s*\"open_domain\"", s2)
    if not m2:
        raise RuntimeError("cannot_find_route_request_open_domain_return")
    body = m2.group(1)

    if "semi_structured_news" not in body:
        inject = r'''\n\n    # news digest (semi-structured retrieval)\n    if _news__is_query(user_text):\n        cat = _news__category_from_text(user_text)\n        tr = _news__time_range_from_text(user_text)\n        rrn = news_digest(category=cat, limit=5, time_range=tr)\n        if rrn.get(\"ok\") and str(rrn.get(\"final\") or \"\").strip():\n            return {\"ok\": True, \"route_type\": \"semi_structured_news\", \"final\": rrn.get(\"final\"), \"data\": rrn}\n        return {\"ok\": True, \"route_type\": \"semi_structured_news\", \"final\": \"新闻检索失败或暂无结果。\", \"data\": rrn}\n'''
        s2 = re.sub(
            r"(def\\s+route_request\\(.*?\\):[\\s\\S]*?)\\n(\\s*)return\\s+\\{\"ok\":\\s*True,\\s*\"route_type\":\\s*\"open_domain\"",
            r"\\1" + inject + r"\\n\\2return {\"ok\": True, \"route_type\": \"open_domain\"",
            s2,
            count=1
        )

    _write(SRC, s2)
    print("patched_ok")

if __name__ == "__main__":
    main()
