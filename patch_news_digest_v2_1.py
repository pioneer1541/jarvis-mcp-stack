#!/usr/bin/env python3
import os
import sys
import re
from datetime import datetime

MARKER = "NEWS_DIGEST_V2_MARKER"


NEWS_BLOCK_RAW = r'''
# =========================
# __NEWS_MARKER__
# News digest (semi-structured retrieval): zh-first with fallback
# =========================
from urllib.parse import urlparse


def _news__is_zh_text(s: str) -> bool:
    if not s:
        return False
    for ch in s:
        o = ord(ch)
        if 0x4E00 <= o <= 0x9FFF:
            return True
    return False


def _news__get_domain(u: str) -> str:
    try:
        p = urlparse(u)
        return (p.netloc or "").lower()
    except Exception:
        return ""


def _news__get_path(u: str) -> str:
    try:
        p = urlparse(u)
        return (p.path or "")
    except Exception:
        return ""


def _news__match_source(u: str, rule: dict) -> bool:
    """
    rule:
      {"domain": "abc.net.au", "path_prefixes": ["/chinese/"]}  # optional path_prefixes
    """
    dom = _news__get_domain(u)
    if not dom:
        return False

    want_dom = (rule.get("domain") or "").lower()
    if want_dom and dom != want_dom:
        return False

    prefixes = rule.get("path_prefixes") or []
    if prefixes:
        path = _news__get_path(u)
        ok = False
        for pre in prefixes:
            if path.startswith(pre):
                ok = True
                break
        return ok
    return True


def _news__dedup_items(items: list) -> list:
    out = []
    seen = set()
    for it in items or []:
        u = (it.get("url") or "").strip()
        if not u:
            continue
        if u in seen:
            continue
        seen.add(u)
        out.append(it)
    return out


def _news__filter_by_sources(items: list, rules: list) -> list:
    if not rules:
        return items or []
    out = []
    for it in items or []:
        u = it.get("url") or ""
        ok = False
        for r in rules:
            if _news__match_source(u, r):
                ok = True
                break
        if ok:
            out.append(it)
    return out


def _news__rank_zh_first(items: list) -> list:
    def keyfn(it):
        title = it.get("title") or ""
        snippet = it.get("snippet") or it.get("content") or ""
        zh = _news__is_zh_text(title) or _news__is_zh_text(snippet)
        return (0 if zh else 1)
    return sorted(items or [], key=keyfn)


def _news__format_final(items: list, limit: int) -> str:
    n = 0
    lines = []
    for it in items or []:
        if n >= limit:
            break
        title = (it.get("title") or "").strip()
        url = (it.get("url") or "").strip()
        dom = (it.get("source") or _news__get_domain(url) or "").strip()
        snippet = (it.get("snippet") or it.get("content") or "").strip()

        if not title:
            continue

        n += 1
        lines.append("{idx}) {title}（{dom}）".format(idx=n, title=title, dom=dom if dom else ""))
        if snippet:
            s = snippet.replace("\n", " ").strip()
            if len(s) > 120:
                s = s[:120].rstrip() + "..."
            lines.append("   {s}".format(s=s))
    if not lines:
        return "暂无符合来源池的新闻结果。"
    return "\n".join(lines)


NEWS_SOURCE_POOLS = {
    "world": {
        "zh_rules": [
            {"domain": "www.thepaper.cn"},
            {"domain": "m.thepaper.cn"},
            {"domain": "news.ifeng.com"},
            {"domain": "www.caixin.com"},
            {"domain": "companies.caixin.com"},
            {"domain": "www.bbc.com", "path_prefixes": ["/zhongwen", "/zh/"]},
            {"domain": "www.dw.com", "path_prefixes": ["/zh", "/zh-hans"]},
        ],
        "en_rules": [
            {"domain": "www.reuters.com"},
            {"domain": "apnews.com"},
            {"domain": "www.bbc.com"},
            {"domain": "www.theguardian.com"},
            {"domain": "www.aljazeera.com"},
        ],
        "q_zh": "国际 要闻",
        "q_en": "world news top stories",
    },

    "cn_finance": {
        "zh_rules": [
            {"domain": "www.caixin.com"},
            {"domain": "companies.caixin.com"},
            {"domain": "www.yicai.com"},
        ],
        "en_rules": [
            {"domain": "www.reuters.com"},
        ],
        "q_zh": "中国 财经 要闻",
        "q_en": "China finance market Reuters",
    },

    "au_politics": {
        "zh_rules": [
            {"domain": "www.sbs.com.au", "path_prefixes": ["/language/chinese"]},
            {"domain": "www.abc.net.au", "path_prefixes": ["/chinese/"]},
        ],
        "en_rules": [
            {"domain": "www.abc.net.au"},
            {"domain": "www.sbs.com.au"},
            {"domain": "www.theguardian.com"},
            {"domain": "www.parliament.gov.au"},
            {"domain": "www.aec.gov.au"},
            {"domain": "www.pm.gov.au"},
        ],
        "q_zh": "澳洲 联邦 政治 要闻",
        "q_en": "Australian federal politics news",
    },

    "mel_life": {
        "zh_rules": [
            {"domain": "www.sbs.com.au", "path_prefixes": ["/language/chinese"]},
            {"domain": "www.abc.net.au", "path_prefixes": ["/chinese/"]},
        ],
        "en_rules": [
            {"domain": "www.abc.net.au"},
            {"domain": "www.9news.com.au"},
            {"domain": "www.melbourne.vic.gov.au"},
            {"domain": "www.vic.gov.au"},
            {"domain": "www.police.vic.gov.au"},
        ],
        "q_zh": "墨尔本 维州 民生 交通 警情 火警",
        "q_en": "Melbourne Victoria local news",
    },

    "tech_internet": {
        "zh_rules": [
            {"domain": "36kr.com"},
            {"domain": "www.huxiu.com"},
        ],
        "en_rules": [
            {"domain": "www.theverge.com"},
            {"domain": "techcrunch.com"},
            {"domain": "www.wired.com"},
            {"domain": "arstechnica.com"},
        ],
        "q_zh": "互联网 科技 要闻",
        "q_en": "tech industry news",
    },

    "tech_gadgets": {
        "zh_rules": [
            {"domain": "sspai.com"},
            {"domain": "www.ifanr.com"},
        ],
        "en_rules": [
            {"domain": "www.theverge.com"},
        ],
        "q_zh": "数码 新品 评测",
        "q_en": "new gadgets reviews",
    },

    "gaming": {
        "zh_rules": [
            {"domain": "www.gcores.com"},
            {"domain": "gcores.com"},
            {"domain": "www.ucg.cn"},
        ],
        "en_rules": [
            {"domain": "www.ign.com"},
            {"domain": "www.pcgamer.com"},
        ],
        "q_zh": "游戏 新闻 Steam 主机 更新",
        "q_en": "video game news IGN PC Gamer",
    },
}


def _news__parse_time_range(user_text: str) -> str:
    t = user_text or ""
    if ("今天" in t) or ("今日" in t) or ("本日" in t):
        return "day"
    if ("本周" in t) or ("一周" in t) or ("7天" in t) or ("最近" in t) or ("近" in t):
        return "week"
    if ("本月" in t) or ("一月" in t) or ("30天" in t) or ("一个月" in t):
        return "month"
    return "day"


def _news__parse_limit(user_text: str, default_n: int) -> int:
    t = user_text or ""
    m = re.search(r"(\d+)\s*(条|则|个)", t)
    if m:
        try:
            n = int(m.group(1))
            if n < 1:
                return default_n
            if n > 10:
                return 10
            return n
        except Exception:
            return default_n
    return default_n


def _news__pick_category(user_text: str) -> str:
    t = user_text or ""
    if ("中国" in t and ("财经" in t or "经济" in t or "A股" in t or "股市" in t)):
        return "cn_finance"
    if ("澳洲" in t or "澳大利亚" in t) and ("政治" in t or "议会" in t or "工党" in t or "反对党" in t):
        return "au_politics"
    if ("墨尔本" in t) or ("维州" in t) or ("Victoria" in t) or ("Melbourne" in t):
        return "mel_life"
    if ("数码" in t) or ("手机" in t) or ("相机" in t) or ("笔记本" in t) or ("耳机" in t) or ("评测" in t):
        return "tech_gadgets"
    if ("互联网" in t) or ("科技" in t) or ("AI" in t) or ("人工智能" in t) or ("大模型" in t):
        return "tech_internet"
    if ("游戏" in t) or ("Steam" in t) or ("主机" in t) or ("PS5" in t) or ("Switch" in t) or ("Xbox" in t):
        return "gaming"
    if ("世界" in t) or ("国际" in t) or ("环球" in t):
        return "world"
    return "world"


def _is_news_query(user_text: str) -> bool:
    t = (user_text or "").strip()
    if not t:
        return False
    keys = ["新闻", "要闻", "头条", "资讯", "news", "top stories"]
    for k in keys:
        if k.lower() in t.lower():
            return True
    cat_keys = ["世界新闻", "国际新闻", "中国财经", "澳洲政治", "墨尔本", "维州新闻", "科技新闻", "数码新闻", "游戏新闻"]
    for k in cat_keys:
        if k in t:
            return True
    return False


def news_digest(category: str = "world", time_range: str = "day", limit: int = 5) -> dict:
    cat = (category or "world").strip()
    if cat not in NEWS_SOURCE_POOLS:
        cat = "world"
    tr = (time_range or "day").strip()
    if tr not in ["day", "week", "month", "year"]:
        tr = "day"
    try:
        lim = int(limit)
    except Exception:
        lim = 5
    if lim < 1:
        lim = 5
    if lim > 10:
        lim = 10

    pool = NEWS_SOURCE_POOLS.get(cat) or {}
    zh_rules = pool.get("zh_rules") or []
    en_rules = pool.get("en_rules") or []
    q_zh = pool.get("q_zh") or ""
    q_en = pool.get("q_en") or ""

    items_all = []
    query_used = ""

    if q_zh and zh_rules:
        r1 = web_search(q_zh, k=12, time_range=tr, categories="news", language="zh-CN")
        items = r1.get("results") or []
        norm = []
        for it in items:
            norm.append({
                "title": it.get("title") or "",
                "url": it.get("url") or "",
                "snippet": it.get("content") or "",
                "source": _news__get_domain(it.get("url") or ""),
            })
        norm = _news__dedup_items(norm)
        norm = _news__filter_by_sources(norm, zh_rules)
        norm = _news__rank_zh_first(norm)
        items_all = norm
        query_used = q_zh

    if (not items_all) and q_en and en_rules:
        r2 = web_search(q_en, k=12, time_range=tr, categories="news", language="en")
        items = r2.get("results") or []
        norm = []
        for it in items:
            norm.append({
                "title": it.get("title") or "",
                "url": it.get("url") or "",
                "snippet": it.get("content") or "",
                "source": _news__get_domain(it.get("url") or ""),
            })
        norm = _news__dedup_items(norm)
        norm = _news__filter_by_sources(norm, en_rules)
        items_all = norm
        query_used = q_en

    if (not items_all) and tr == "day":
        tr2 = "week"
        if q_zh and zh_rules:
            r3 = web_search(q_zh, k=12, time_range=tr2, categories="news", language="zh-CN")
            items = r3.get("results") or []
            norm = []
            for it in items:
                norm.append({
                    "title": it.get("title") or "",
                    "url": it.get("url") or "",
                    "snippet": it.get("content") or "",
                    "source": _news__get_domain(it.get("url") or ""),
                })
            norm = _news__dedup_items(norm)
            norm = _news__filter_by_sources(norm, zh_rules)
            norm = _news__rank_zh_first(norm)
            items_all = norm
            query_used = q_zh
            tr = tr2

        if (not items_all) and q_en and en_rules:
            r4 = web_search(q_en, k=12, time_range=tr2, categories="news", language="en")
            items = r4.get("results") or []
            norm = []
            for it in items:
                norm.append({
                    "title": it.get("title") or "",
                    "url": it.get("url") or "",
                    "snippet": it.get("content") or "",
                    "source": _news__get_domain(it.get("url") or ""),
                })
            norm = _news__dedup_items(norm)
            norm = _news__filter_by_sources(norm, en_rules)
            items_all = norm
            query_used = q_en
            tr = tr2

    final = _news__format_final(items_all, lim)

    return {
        "ok": True,
        "category": cat,
        "time_range": tr,
        "limit": lim,
        "final": final,
        "items": items_all[:lim],
        "query_used": query_used,
    }
'''


def read_text(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


def write_text(p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)


def backup_file(p):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bp = p + ".bak.news_v2_1." + ts
    with open(p, "rb") as f:
        data = f.read()
    with open(bp, "wb") as f:
        f.write(data)
    return bp


def main():
    app_path = os.path.join(os.getcwd(), "app.py")
    if not os.path.exists(app_path):
        print("ERROR: app.py not found in cwd:", os.getcwd())
        sys.exit(2)

    s = read_text(app_path)
    if MARKER in s:
        print("OK: marker already present, nothing to do.")
        return

    bp = backup_file(app_path)
    print("Backup:", bp)

    news_block = NEWS_BLOCK_RAW.replace("__NEWS_MARKER__", MARKER)

    anchor = '@mcp.tool(description="(Tool) Open an URL and extract readable text")'
    pos = s.find(anchor)
    if pos < 0:
        print("ERROR: anchor not found for insertion:", anchor)
        sys.exit(3)

    s2 = s[:pos] + news_block + "\n\n" + s[pos:]

    # Patch _route_type: add semi_structured_news
    rt_pat = "return open_domain"
    rt_pos = s2.find(rt_pat)
    if rt_pos < 0:
        print("ERROR: cannot find 'return open_domain' in _route_type area")
        sys.exit(4)

    fn_start = s2.find("def _route_type(")
    if fn_start < 0:
        print("ERROR: cannot find def _route_type")
        sys.exit(5)

    fn_slice = s2[fn_start:rt_pos + len(rt_pat)]
    if "semi_structured_news" not in fn_slice:
        insert_snippet = (
            "\n    # News / digest requests (semi-structured retrieval)\n"
            "    if _is_news_query(text):\n"
            "        return \"semi_structured_news\"\n\n"
        )
        s2 = s2[:rt_pos] + insert_snippet + s2[rt_pos:]

    # Patch route_request: handle semi_structured_news
    rr_start = s2.find("def route_request(")
    if rr_start < 0:
        print("ERROR: cannot find def route_request")
        sys.exit(6)

    key_line = "route_type = _route_type(user_text)"
    kpos = s2.find(key_line, rr_start)
    if kpos < 0:
        print("ERROR: cannot find route_type assignment in route_request")
        sys.exit(7)

    line_end = s2.find("\n", kpos)
    if line_end < 0:
        print("ERROR: cannot find line end after route_type assignment")
        sys.exit(8)

    window = s2[kpos:line_end + 600]
    if "semi_structured_news" not in window:
        rr_insert = (
            "\n"
            "    # News digest (semi-structured)\n"
            "    if route_type == \"semi_structured_news\":\n"
            "        cat = _news__pick_category(user_text)\n"
            "        tr = _news__parse_time_range(user_text)\n"
            "        lim = _news__parse_limit(user_text, 5)\n"
            "        data = news_digest(category=cat, time_range=tr, limit=lim)\n"
            "        return {\n"
            "            \"ok\": True,\n"
            "            \"route_type\": \"semi_structured_news\",\n"
            "            \"final\": (data.get(\"final\") or \"\"),\n"
            "            \"data\": data,\n"
            "        }\n"
        )
        s2 = s2[:line_end + 1] + rr_insert + s2[line_end + 1:]

    write_text(app_path, s2)
    print("OK: patched app.py with news digest v2.1")


if __name__ == "__main__":
    main()
