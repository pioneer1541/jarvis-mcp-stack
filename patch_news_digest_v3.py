#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sys
import shutil
from datetime import datetime

MARK_BEGIN = "NEWS_DIGEST_V3_BEGIN"
MARK_END = "NEWS_DIGEST_V3_END"

def _read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def _write_text(path, s):
    with open(path, "w", encoding="utf-8") as f:
        f.write(s)

def _backup(path):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = path + ".bak.news_v3." + ts
    shutil.copy2(path, bak)
    return bak

def _find_router_decorator_idx(lines):
    # Stable anchor in your file:
    # @mcp.tool(description="(Router) Route a user request to a specific tool category")
    pat = re.compile(r'^@mcp\.tool\(description="\(Router\)')
    for i, line in enumerate(lines):
        if pat.match(line):
            return i
    return None

def _find_route_request_block(lines):
    # Find: def route_request(
    def_idx = None
    for i, line in enumerate(lines):
        if re.match(r"^def\s+route_request\s*\(", line):
            def_idx = i
            break
    if def_idx is None:
        return None, None

    # block ends at next top-level def or decorator
    end_idx = None
    for j in range(def_idx + 1, len(lines)):
        if re.match(r"^(def\s+|@mcp\.tool)", lines[j]):
            end_idx = j
            break
    if end_idx is None:
        end_idx = len(lines)
    return def_idx, end_idx

def _build_news_block():
    # IMPORTANT: do NOT use .format on this block; it contains { } dict literals.
    return (
        "\n"
        "# ===============================\n"
        "# " + MARK_BEGIN + "\n"
        "# Semi-structured news digest (Chinese-first source pools + authoritative English fallback)\n"
        "# ===============================\n"
        "from urllib.parse import urlparse\n"
        "\n"
        "def _news__norm_host(host: str) -> str:\n"
        "    h = (host or \"\").lower().split(\":\", 1)[0]\n"
        "    for pfx in (\"www.\", \"m.\", \"amp.\"):\n"
        "        if h.startswith(pfx):\n"
        "            h = h[len(pfx):]\n"
        "    return h\n"
        "\n"
        "def _news__match_source(url: str, rules: list) -> bool:\n"
        "    try:\n"
        "        u = urlparse(url)\n"
        "    except Exception:\n"
        "        return False\n"
        "    host = _news__norm_host(u.netloc)\n"
        "    path = u.path or \"/\"\n"
        "    for r in (rules or []):\n"
        "        dom = _news__norm_host(r.get(\"domain\") or \"\")\n"
        "        if not dom:\n"
        "            continue\n"
        "        wildcard = bool(r.get(\"wildcard\"))\n"
        "        if wildcard:\n"
        "            if host == dom or host.endswith(\".\" + dom):\n"
        "                pass\n"
        "            else:\n"
        "                continue\n"
        "        else:\n"
        "            if host != dom:\n"
        "                continue\n"
        "        pfxs = r.get(\"path_prefixes\") or []\n"
        "        if pfxs:\n"
        "            ok = False\n"
        "            for pfx in pfxs:\n"
        "                if path.startswith(pfx):\n"
        "                    ok = True\n"
        "                    break\n"
        "            if not ok:\n"
        "                continue\n"
        "        return True\n"
        "    return False\n"
        "\n"
        "def _news__extract_limit(text: str, default: int = 5) -> int:\n"
        "    t = text or \"\"\n"
        "    m = re.search(r\"(\\d{1,2})\\s*(条|則|则|个|篇)\", t)\n"
        "    if not m:\n"
        "        m = re.search(r\"top\\s*(\\d{1,2})\", t, flags=re.I)\n"
        "    if not m:\n"
        "        return default\n"
        "    try:\n"
        "        n = int(m.group(1))\n"
        "    except Exception:\n"
        "        return default\n"
        "    if n < 1:\n"
        "        return 1\n"
        "    if n > 10:\n"
        "        return 10\n"
        "    return n\n"
        "\n"
        "def _news__time_range_from_text(text: str) -> str:\n"
        "    t = text or \"\"\n"
        "    if any(x in t for x in [\"本周\", \"一周\", \"近一周\", \"最近一周\", \"week\"]):\n"
        "        return \"week\"\n"
        "    return \"day\"\n"
        "\n"
        "def _news_category_from_text(text: str) -> str:\n"
        "    t = (text or \"\").lower()\n"
        "    if (\"墨尔本\" in t) or (\"melbourne\" in t) or (\"维州\" in t) or (\"victoria\" in t) or (\"本地\" in t and \"新闻\" in t):\n"
        "        return \"mel_life\"\n"
        "    if (\"澳洲\" in t or \"澳大利亚\" in t or \"australia\" in t) and (\"政治\" in t or \"议会\" in t or \"工党\" in t or \"自由党\" in t):\n"
        "        return \"au_politics\"\n"
        "    if (\"财经\" in t) or (\"股市\" in t) or (\"a股\" in t) or (\"经济\" in t and \"中国\" in t):\n"
        "        return \"cn_finance\"\n"
        "    if (\"数码\" in t) or (\"手机\" in t) or (\"相机\" in t) or (\"电脑\" in t) or (\"评测\" in t) or (\"新品\" in t):\n"
        "        return \"tech_gadgets\"\n"
        "    if (\"互联网\" in t) or (\"ai\" in t) or (\"人工智能\" in t) or (\"开源\" in t) or (\"科技\" in t):\n"
        "        return \"tech_internet\"\n"
        "    if (\"游戏\" in t) or (\"steam\" in t) or (\"ps5\" in t) or (\"xbox\" in t) or (\"switch\" in t):\n"
        "        return \"gaming\"\n"
        "    if (\"世界\" in t) or (\"国际\" in t) or (\"world\" in t):\n"
        "        return \"world\"\n"
        "    if \"新闻\" in t or \"要闻\" in t:\n"
        "        return \"world\"\n"
        "    return \"world\"\n"
        "\n"
        "def _is_news_query(text: str) -> bool:\n"
        "    t = text or \"\"\n"
        "    if any(k in t for k in [\"新闻\", \"要闻\", \"资讯\", \"headline\", \"headlines\"]):\n"
        "        return True\n"
        "    if any(k in t for k in [\"世界\", \"国际\", \"澳洲政治\", \"中国财经\", \"墨尔本\", \"维州\", \"互联网科技\", \"数码\", \"游戏新闻\"]):\n"
        "        return True\n"
        "    return False\n"
        "\n"
        "def _news__cfg() -> dict:\n"
        "    # Each source rule: {domain, wildcard?, path_prefixes?}\n"
        "    return {\n"
        "        \"world\": {\n"
        "            \"terms\": [\"国际\", \"要闻\"],\n"
        "            \"zh\": [\n"
        "                {\"domain\": \"thepaper.cn\", \"wildcard\": True},\n"
        "                {\"domain\": \"caixin.com\", \"wildcard\": True},\n"
        "                {\"domain\": \"ifeng.com\", \"wildcard\": True},\n"
        "                {\"domain\": \"bbc.com\", \"wildcard\": True, \"path_prefixes\": [\"/zhongwen\", \"/zh\"]},\n"
        "                {\"domain\": \"dw.com\", \"wildcard\": True, \"path_prefixes\": [\"/zh\", \"/zh-hans\"]},\n"
        "            ],\n"
        "            \"en\": [\n"
        "                {\"domain\": \"reuters.com\", \"wildcard\": True},\n"
        "                {\"domain\": \"apnews.com\", \"wildcard\": True},\n"
        "                {\"domain\": \"bbc.com\", \"wildcard\": True},\n"
        "                {\"domain\": \"theguardian.com\", \"wildcard\": True},\n"
        "                {\"domain\": \"aljazeera.com\", \"wildcard\": True},\n"
        "            ],\n"
        "        },\n"
        "        \"cn_finance\": {\n"
        "            \"terms\": [\"中国\", \"财经\", \"要闻\"],\n"
        "            \"zh\": [\n"
        "                {\"domain\": \"caixin.com\", \"wildcard\": True},\n"
        "                {\"domain\": \"yicai.com\", \"wildcard\": True},\n"
        "            ],\n"
        "            \"en\": [\n"
        "                {\"domain\": \"reuters.com\", \"wildcard\": True},\n"
        "            ],\n"
        "        },\n"
        "        \"au_politics\": {\n"
        "            \"terms\": [\"澳洲\", \"联邦\", \"政治\"],\n"
        "            \"zh\": [\n"
        "                {\"domain\": \"sbs.com.au\", \"wildcard\": True, \"path_prefixes\": [\"/language/chinese\"]},\n"
        "                {\"domain\": \"abc.net.au\", \"wildcard\": True, \"path_prefixes\": [\"/chinese\"]},\n"
        "            ],\n"
        "            \"en\": [\n"
        "                {\"domain\": \"abc.net.au\", \"wildcard\": True},\n"
        "                {\"domain\": \"sbs.com.au\", \"wildcard\": True},\n"
        "                {\"domain\": \"theguardian.com\", \"wildcard\": True},\n"
        "                {\"domain\": \"aph.gov.au\", \"wildcard\": True},\n"
        "                {\"domain\": \"parliament.gov.au\", \"wildcard\": True},\n"
        "                {\"domain\": \"aec.gov.au\", \"wildcard\": True},\n"
        "            ],\n"
        "        },\n"
        "        \"mel_life\": {\n"
        "            \"terms\": [\"墨尔本\", \"维州\", \"民生\"],\n"
        "            \"zh\": [\n"
        "                {\"domain\": \"sbs.com.au\", \"wildcard\": True, \"path_prefixes\": [\"/language/chinese\"]},\n"
        "                {\"domain\": \"abc.net.au\", \"wildcard\": True, \"path_prefixes\": [\"/chinese\"]},\n"
        "            ],\n"
        "            \"en\": [\n"
        "                {\"domain\": \"abc.net.au\", \"wildcard\": True},\n"
        "                {\"domain\": \"9news.com.au\", \"wildcard\": True},\n"
        "                {\"domain\": \"melbourne.vic.gov.au\", \"wildcard\": True},\n"
        "            ],\n"
        "        },\n"
        "        \"tech_internet\": {\n"
        "            \"terms\": [\"互联网\", \"科技\", \"AI\"],\n"
        "            \"zh\": [\n"
        "                {\"domain\": \"36kr.com\", \"wildcard\": True},\n"
        "                {\"domain\": \"huxiu.com\", \"wildcard\": True},\n"
        "            ],\n"
        "            \"en\": [\n"
        "                {\"domain\": \"theverge.com\", \"wildcard\": True},\n"
        "                {\"domain\": \"techcrunch.com\", \"wildcard\": True},\n"
        "                {\"domain\": \"wired.com\", \"wildcard\": True},\n"
        "                {\"domain\": \"arstechnica.com\", \"wildcard\": True},\n"
        "            ],\n"
        "        },\n"
        "        \"tech_gadgets\": {\n"
        "            \"terms\": [\"数码\", \"新品\", \"评测\"],\n"
        "            \"zh\": [\n"
        "                {\"domain\": \"sspai.com\", \"wildcard\": True},\n"
        "                {\"domain\": \"ifanr.com\", \"wildcard\": True},\n"
        "            ],\n"
        "            \"en\": [\n"
        "                {\"domain\": \"theverge.com\", \"wildcard\": True},\n"
        "            ],\n"
        "        },\n"
        "        \"gaming\": {\n"
        "            \"terms\": [\"游戏\", \"新闻\", \"Steam\"],\n"
        "            \"zh\": [\n"
        "                {\"domain\": \"gcores.com\", \"wildcard\": True},\n"
        "                {\"domain\": \"ucg.cn\", \"wildcard\": True},\n"
        "            ],\n"
        "            \"en\": [\n"
        "                {\"domain\": \"ign.com\", \"wildcard\": True},\n"
        "                {\"domain\": \"pcgamer.com\", \"wildcard\": True},\n"
        "            ],\n"
        "        },\n"
        "    }\n"
        "\n"
        "def _news__build_query(terms: list, rules_zh: list, rules_en: list) -> str:\n"
        "    words = \" \".join([x for x in (terms or []) if x])\n"
        "    sites = []\n"
        "    for r in (rules_zh or []) + (rules_en or []):\n"
        "        dom = (r.get(\"domain\") or \"\").strip()\n"
        "        if not dom:\n"
        "            continue\n"
        "        sites.append(\"site:\" + dom)\n"
        "    sites = sorted(list(set(sites)))\n"
        "    if sites:\n"
        "        return words + \" (\" + \" OR \".join(sites) + \")\"\n"
        "    return words\n"
        "\n"
        "def _news__format_final(items: list) -> str:\n"
        "    if not items:\n"
        "        return \"暂无符合来源池的新闻结果。\"\n"
        "    out_lines = []\n"
        "    i = 1\n"
        "    for it in items:\n"
        "        title = (it.get(\"title\") or \"\").strip()\n"
        "        url = (it.get(\"url\") or \"\").strip()\n"
        "        src = (it.get(\"source\") or \"\").strip()\n"
        "        snip = (it.get(\"snippet\") or \"\").strip()\n"
        "        if not title or not url:\n"
        "            continue\n"
        "        out_lines.append(str(i) + \") \" + title + \"（\" + src + \"）\")\n"
        "        if snip:\n"
        "            out_lines.append(\"   \" + snip)\n"
        "        i += 1\n"
        "    return \"\\n\".join(out_lines)\n"
        "\n"
        "@mcp.tool(description=\"(Tool) News digest for a category and time range\")\n"
        "def news_digest(category: str = \"world\", time_range: str = \"day\", limit: int = 5) -> dict:\n"
        "    cfg = _news__cfg()\n"
        "    if category not in cfg:\n"
        "        category = \"world\"\n"
        "    if time_range not in (\"day\", \"week\"):\n"
        "        time_range = \"day\"\n"
        "    if limit is None:\n"
        "        limit = 5\n"
        "    try:\n"
        "        limit_i = int(limit)\n"
        "    except Exception:\n"
        "        limit_i = 5\n"
        "    if limit_i < 1:\n"
        "        limit_i = 1\n"
        "    if limit_i > 10:\n"
        "        limit_i = 10\n"
        "\n"
        "    terms = cfg[category].get(\"terms\") or []\n"
        "    rules_zh = cfg[category].get(\"zh\") or []\n"
        "    rules_en = cfg[category].get(\"en\") or []\n"
        "\n"
        "    recency_hint = \" 今天\" if time_range == \"day\" else \" 本周\"\n"
        "    q = _news__build_query(terms, rules_zh, rules_en) + recency_hint\n"
        "    r = web_search(q, k=max(20, limit_i * 6), categories=\"general\")\n"
        "    results = (r.get(\"results\") or []) if isinstance(r, dict) else []\n"
        "\n"
        "    items_all = []\n"
        "    seen = set()\n"
        "    for it in results:\n"
        "        url = (it.get(\"url\") or \"\").strip()\n"
        "        title = (it.get(\"title\") or \"\").strip()\n"
        "        if not url or not title:\n"
        "            continue\n"
        "        if url in seen:\n"
        "            continue\n"
        "        seen.add(url)\n"
        "        items_all.append(it)\n"
        "\n"
        "    picked = []\n"
        "    for it in items_all:\n"
        "        if _news__match_source(it.get(\"url\"), rules_zh):\n"
        "            picked.append(it)\n"
        "            if len(picked) >= limit_i:\n"
        "                break\n"
        "\n"
        "    if len(picked) < limit_i:\n"
        "        for it in items_all:\n"
        "            if _news__match_source(it.get(\"url\"), rules_en):\n"
        "                if it in picked:\n"
        "                    continue\n"
        "                picked.append(it)\n"
        "                if len(picked) >= limit_i:\n"
        "                    break\n"
        "\n"
        "    query_used = q\n"
        "    if not picked and time_range == \"day\":\n"
        "        q2 = _news__build_query(terms, rules_zh, rules_en) + \" 本周\"\n"
        "        r2 = web_search(q2, k=max(20, limit_i * 6), categories=\"general\")\n"
        "        results2 = (r2.get(\"results\") or []) if isinstance(r2, dict) else []\n"
        "        items2 = []\n"
        "        seen2 = set()\n"
        "        for it in results2:\n"
        "            url = (it.get(\"url\") or \"\").strip()\n"
        "            title = (it.get(\"title\") or \"\").strip()\n"
        "            if not url or not title:\n"
        "                continue\n"
        "            if url in seen2:\n"
        "                continue\n"
        "            seen2.add(url)\n"
        "            items2.append(it)\n"
        "        for it in items2:\n"
        "            if _news__match_source(it.get(\"url\"), rules_zh):\n"
        "                picked.append(it)\n"
        "                if len(picked) >= limit_i:\n"
        "                    break\n"
        "        if len(picked) < limit_i:\n"
        "            for it in items2:\n"
        "                if _news__match_source(it.get(\"url\"), rules_en):\n"
        "                    if it in picked:\n"
        "                        continue\n"
        "                    picked.append(it)\n"
        "                    if len(picked) >= limit_i:\n"
        "                        break\n"
        "        query_used = q2\n"
        "        if picked:\n"
        "            time_range = \"week\"\n"
        "\n"
        "    out_items = []\n"
        "    for it in picked:\n"
        "        out_items.append({\n"
        "            \"title\": it.get(\"title\"),\n"
        "            \"url\": it.get(\"url\"),\n"
        "            \"snippet\": it.get(\"snippet\") or it.get(\"content\") or \"\",\n"
        "            \"source\": it.get(\"source\") or _news__norm_host(urlparse(it.get(\"url\") or \"\").netloc),\n"
        "            \"lang\": it.get(\"lang\") or \"\",\n"
        "        })\n"
        "\n"
        "    final = _news__format_final(out_items)\n"
        "    return {\n"
        "        \"ok\": True,\n"
        "        \"category\": category,\n"
        "        \"time_range\": time_range,\n"
        "        \"limit\": limit_i,\n"
        "        \"final\": final,\n"
        "        \"items\": out_items,\n"
        "        \"query_used\": query_used,\n"
        "    }\n"
        "\n"
        "# " + MARK_END + "\n"
        "# ===============================\n"
        "\n"
    )

def _inject_news_routing_into_route_request(lines):
    def_idx, end_idx = _find_route_request_block(lines)
    if def_idx is None:
        raise RuntimeError("route_request not found")

    # find the last open_domain return line inside route_request block
    block = lines[def_idx:end_idx]
    open_idx = None
    for k in range(len(block) - 1, -1, -1):
        if '"route_type": "open_domain"' in block[k]:
            open_idx = k
            break
    if open_idx is None:
        raise RuntimeError("open_domain return not found in route_request")

    inject = (
        "    # Semi-structured retrieval: news digest\n"
        "    if _is_news_query(user_text):\n"
        "        cat = _news_category_from_text(user_text)\n"
        "        tr = _news__time_range_from_text(user_text)\n"
        "        lim = _news__extract_limit(user_text, 5)\n"
        "        data = news_digest(category=cat, time_range=tr, limit=lim)\n"
        "        final = (data.get(\"final\") or \"\") if isinstance(data, dict) else \"\"\n"
        "        if not final:\n"
        "            final = \"暂无符合来源池的新闻结果。\"\n"
        "        return {\"ok\": True, \"route_type\": \"semi_structured_news\", \"final\": final, \"data\": data}\n"
        "\n"
        "    return {\"ok\": True, \"route_type\": \"open_domain\", \"final\": \"开放域问题：请直接提问（例如：解释某个概念、某个事件的背景）。\"}\n"
    )

    block[open_idx] = inject
    lines[def_idx:end_idx] = block
    return lines

def main():
    path = "app.py"
    if not os.path.exists(path):
        print("ERROR: app.py not found in current directory.")
        sys.exit(2)

    s = _read_text(path)
    if MARK_BEGIN in s:
        print("SKIP: news digest v3 already present in app.py")
        sys.exit(0)

    bak = _backup(path)
    lines = s.splitlines(True)

    ins_idx = _find_router_decorator_idx(lines)
    if ins_idx is None:
        print("ERROR: Router decorator anchor not found.")
        print("Hint: expected a line like: @mcp.tool(description=\"(Router) ...\")")
        print("Backup: " + bak)
        sys.exit(3)

    news_block = _build_news_block()
    lines = lines[:ins_idx] + [news_block] + lines[ins_idx:]

    lines = _inject_news_routing_into_route_request(lines)

    out = "".join(lines)
    _write_text(path, out)

    print("Backup: " + bak)
    print("OK: patched app.py with news digest v3")

if __name__ == "__main__":
    main()
