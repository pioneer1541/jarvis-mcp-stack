#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import time

APP = "app.py"


def read_lines(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.readlines()


def write_lines(path, lines):
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(lines))


def backup_file(path):
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = "{0}.bak.brave_search_{1}".format(path, ts)
    with open(path, "r", encoding="utf-8") as fsrc:
        with open(bak, "w", encoding="utf-8") as fdst:
            fdst.write(fsrc.read())
    return bak


def find_def_block(lines, def_name):
    # returns (start, end) for a top-level def block
    pat = re.compile(r"^def\s+" + re.escape(def_name) + r"\s*\(")
    start = None
    for i, l in enumerate(lines):
        if pat.match(l):
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


def replace_def_block(lines, def_name, new_block_text):
    blk = find_def_block(lines, def_name)
    if not blk:
        raise RuntimeError("def block not found: {0}".format(def_name))
    s, e = blk
    new_lines = new_block_text.splitlines(True)
    lines[s:e] = new_lines
    return lines


def insert_after_def(lines, def_name, insert_text):
    blk = find_def_block(lines, def_name)
    if not blk:
        raise RuntimeError("def block not found: {0}".format(def_name))
    s, e = blk
    ins = insert_text.splitlines(True)
    lines[e:e] = ins
    return lines


def patch_web_search_config(lines):
    blk = find_def_block(lines, "web_search")
    if not blk:
        raise RuntimeError("def block not found: web_search")
    s, e = blk
    ws = lines[s:e]

    # 1) base_url env: SEARXNG_URL -> BRAVE_SEARCH_URL
    # 2) insert token check (idempotent)
    have_token_check = False
    for l in ws:
        if "BRAVE_SEARCH_TOKEN" in l or "BRAVE_API_KEY" in l:
            have_token_check = True
            break

    replaced = False
    for i in range(len(ws)):
        if 'os.getenv("SEARXNG_URL"' in ws[i] or 'os.getenv("BRAVE_SEARCH_URL"' in ws[i]:
            ws[i] = '    base_url = os.getenv("BRAVE_SEARCH_URL", "https://api.search.brave.com/res/v1/web/search").strip()\n'
            replaced = True

            if not have_token_check:
                token_check = [
                    '    token = (os.getenv("BRAVE_SEARCH_TOKEN") or os.getenv("BRAVE_API_KEY") or "").strip()\n',
                    '    if not token:\n',
                    '        return {"ok": False, "error": "brave_not_configured", "base_url": base_url, "message": "BRAVE_SEARCH_TOKEN not set"}\n',
                ]
                ws[i + 1:i + 1] = token_check
            break

    if not replaced:
        raise RuntimeError("web_search: base_url env line not found")

    # replace error code searxng_failed -> brave_failed
    out = []
    for l in ws:
        out.append(l.replace('"error": "searxng_failed"', '"error": "brave_failed"'))
    ws = out

    lines[s:e] = ws
    return lines


def insert_web_route_branch(lines):
    blk = find_def_block(lines, "_route_request_impl")
    if not blk:
        raise RuntimeError("def block not found: _route_request_impl")
    s, e = blk
    route = lines[s:e]

    # already inserted?
    for l in route:
        if "semi_structured_web" in l and "_is_web_search_query" in "".join(route):
            return lines

    # find the final open_domain fallback (the one containing “开放域问题”)
    insert_at = None
    for i, l in enumerate(route):
        if ("开放域问题" in l) and ("route_type" in l) and ("open_domain" in l):
            insert_at = i
            break
    if insert_at is None:
        raise RuntimeError("_route_request_impl: open_domain fallback line not found")

    web_branch_body = [
        "\n",
        "    # Semi-structured retrieval: web search (Brave Search API)\n",
        "    if _is_web_search_query(user_text):\n",
        "        q = _web__strip_search_prefix(user_text) or user_text\n",
        "        tr = _news__time_range_from_text(user_text)\n",
        "        lim = _news__extract_limit(user_text, 5)\n",
        '        lang = "zh-CN" if str(prefer_lang or "").strip().lower().startswith("zh") else "en"\n',
        '        data = web_search(query=q, k=lim, categories="general", language=lang, time_range=tr)\n',
        "        if not isinstance(data, dict) or (not data.get(\"ok\")):\n",
        "            msg = \"\"\n",
        "            if isinstance(data, dict):\n",
        "                msg = (data.get(\"message\") or \"\").strip()\n",
        "            final = \"网页搜索失败。\"\n",
        "            if msg:\n",
        "                final = final + \" \" + msg\n",
        "            ret = {\"ok\": True, \"route_type\": \"semi_structured_web\", \"final\": final}\n",
        "            if _route_return_data:\n",
        "                ret[\"data\"] = data\n",
        "            return ret\n",
        "\n",
        "        items = data.get(\"results\") or []\n",
        "        out_lines = []\n",
        "        try:\n",
        "            for i, it in enumerate(items[:lim], 1):\n",
        "                title = str(it.get(\"title\") or \"\").strip()\n",
        "                url = str(it.get(\"url\") or \"\").strip()\n",
        "                snippet = str(it.get(\"snippet\") or \"\").strip()\n",
        "                if (not title) and (not url):\n",
        "                    continue\n",
        "                out_lines.append(\"{0}) {1}\".format(i, title or url))\n",
        "                if url:\n",
        "                    out_lines.append(\"   {0}\".format(url))\n",
        "                if snippet:\n",
        "                    out_lines.append(\"   {0}\".format(snippet[:220]))\n",
        "        except Exception:\n",
        "            pass\n",
        "\n",
        "        final = \"\\n\".join(out_lines).strip() if out_lines else \"暂无搜索结果。\"\n",
        "        ret = {\"ok\": True, \"route_type\": \"semi_structured_web\", \"final\": final}\n",
        "        if _route_return_data:\n",
        "            ret[\"data\"] = data\n",
        "        return ret\n",
        "\n",
    ]

    route[insert_at:insert_at] = web_branch_body
    lines[s:e] = route
    return lines


def apply_patch():
    lines = read_lines(APP)

    # If already brave backend present, avoid double replace
    content = "".join(lines)
    if ("Brave Search API backend" not in content) or ("X-Subscription-Token" not in content):
        new_backend = r'''
def _brave__map_time_range_to_freshness(time_range: Optional[str]) -> Optional[str]:
    """
    Brave Search API "freshness" param:
      pd / pw / pm / py
      or explicit range: YYYY-MM-DDtoYYYY-MM-DD
    We accept a few legacy values (day/week/month/year) for compatibility.
    """
    t = (time_range or "").strip()
    if not t:
        return None
    tl = t.lower().strip()
    if tl in ["pd", "pw", "pm", "py"]:
        return tl
    if tl in ["day", "today", "24h", "d"]:
        return "pd"
    if tl in ["week", "7d", "w"]:
        return "pw"
    if tl in ["month", "30d", "31d", "m"]:
        return "pm"
    if tl in ["year", "y"]:
        return "py"
    m = re.search(r"(\d{4}-\d{2}-\d{2})\s*to\s*(\d{4}-\d{2}-\d{2})", t, flags=re.IGNORECASE)
    if m:
        return m.group(1) + "to" + m.group(2)
    m2 = re.match(r"^\d{4}-\d{2}-\d{2}to\d{4}-\d{2}-\d{2}$", tl)
    if m2:
        return t.replace(" ", "")
    return None


def _brave__lang_params(language: str) -> Tuple[str, str]:
    """
    Map language hints to Brave params:
      search_lang: 2-letter (e.g., "en", "zh")
      ui_lang: locale (e.g., "en-US", "zh-CN")
    """
    lang = (language or "").strip()
    ll = lang.lower()
    if ll.startswith("zh"):
        return ("zh", "zh-CN")
    if ll.startswith("en"):
        return ("en", "en-US")
    m = re.match(r"^([a-z]{2})(?:-([a-z]{2}))?$", ll)
    if m:
        sl = m.group(1)
        if m.group(2):
            return (sl, sl + "-" + m.group(2).upper())
        return (sl, sl + "-" + sl.upper())
    return ("en", "en-US")


def _searxng_search(
    base_url: str,
    query: str,
    categories: str,
    language: str,
    count: int,
    time_range: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Brave Search API backend (replaces local SearXNG).
    Compatibility: returns a SearXNG-like JSON shape: {"results":[{title,url,content,engine,score},...]}.

    Env:
      - BRAVE_SEARCH_TOKEN (required)
      - BRAVE_SEARCH_URL (default: https://api.search.brave.com/res/v1/web/search)
      - BRAVE_SEARCH_TIMEOUT (default: 8)
      - BRAVE_SEARCH_COUNTRY (default: AU)
      - BRAVE_SAFESEARCH (default: moderate)
      - BRAVE_EXTRA_SNIPPETS (default: true)
    """
    api_url = (os.getenv("BRAVE_SEARCH_URL") or "").strip()
    if not api_url:
        api_url = (base_url or "").strip()
    if not api_url:
        api_url = "https://api.search.brave.com/res/v1/web/search"

    token = (os.getenv("BRAVE_SEARCH_TOKEN") or os.getenv("BRAVE_API_KEY") or "").strip()
    if not token:
        raise RuntimeError("BRAVE_SEARCH_TOKEN not set")

    timeout_s = float(os.getenv("BRAVE_SEARCH_TIMEOUT", "8"))
    country = (os.getenv("BRAVE_SEARCH_COUNTRY") or "AU").strip() or "AU"
    safesearch = (os.getenv("BRAVE_SAFESEARCH") or "moderate").strip() or "moderate"
    extra_snippets = str(os.getenv("BRAVE_EXTRA_SNIPPETS", "true")).strip().lower() in ["1", "true", "yes", "y", "on"]

    search_lang, ui_lang = _brave__lang_params(language)
    freshness = _brave__map_time_range_to_freshness(time_range)

    params = {
        "q": query,
        "count": int(count),
        "offset": 0,
        "country": country,
        "search_lang": search_lang,
        "ui_lang": ui_lang,
        "safesearch": safesearch,
    }
    if freshness:
        params["freshness"] = freshness
    if extra_snippets:
        params["extra_snippets"] = "true"

    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": token,
        "Accept-Language": ui_lang,
    }

    resp = requests.get(api_url, params=params, headers=headers, timeout=timeout_s)
    resp.raise_for_status()
    j = resp.json()

    web = j.get("web") if isinstance(j, dict) else None
    items = (web or {}).get("results") if isinstance(web, dict) else None
    if not isinstance(items, list):
        items = []

    out_results = []
    for it in items:
        if not isinstance(it, dict):
            continue
        title = str(it.get("title") or "").strip()
        url = str(it.get("url") or it.get("link") or "").strip()
        desc = str(it.get("description") or it.get("desc") or "").strip()
        extras = it.get("extra_snippets") or []
        extras2 = []
        if isinstance(extras, list):
            for x in extras:
                sx = str(x or "").strip()
                if sx:
                    extras2.append(sx)

        content = desc
        if extras2:
            for x in extras2[:2]:
                if x and (x not in content):
                    content = (content + " " + x).strip() if content else x

        if not title and not url and not content:
            continue

        out_results.append(
            {
                "title": title,
                "url": url,
                "content": content,
                "engine": "brave",
                "score": it.get("score"),
            }
        )

    return {
        "results": out_results,
        "query": (j.get("query") if isinstance(j, dict) else None),
        "backend": "brave",
    }
'''
        # Replace _searxng_search block
        lines = replace_def_block(lines, "_searxng_search", new_backend)

    # Insert helpers after _is_news_query (idempotent)
    content = "".join(lines)
    if "_is_web_search_query" not in content:
        helpers = r'''

def _is_web_search_query(text: str) -> bool:
    """
    Heuristic: decide whether we should use web search (semi-structured retrieval).
    Conservative triggers:
      - explicit "搜索/查询/查一下/帮我查/帮我搜索" or "search/look up"
      - recency words ("最新/现在/今天/目前/本周/本月/版本/价格/多少") or explicit year 20xx (>=2024)
    """
    t = (text or "").strip()
    if not t:
        return False
    tl = t.lower()

    explicit = ["搜索", "查询", "检索", "查一下", "查查", "查一查", "帮我查", "帮我搜索"]
    for k in explicit:
        if k in t:
            return True

    for k in ["search", "lookup", "look up", "google", "bing", "brave"]:
        if k in tl:
            return True

    rec = ["最新", "现在", "目前", "今天", "昨日", "昨天", "本周", "这周", "本月", "这个月", "更新", "版本",
           "多少钱", "价格", "多少", "排名", "榜单", "gdp", "population", "斩杀线"]
    for k in rec:
        if k in t:
            return True
    for k in ["latest", "current", "today", "this week", "this month"]:
        if k in tl:
            return True

    m = re.search(r"(20\d{2})", t)
    if m:
        try:
            y = int(m.group(1))
            if y >= 2024:
                return True
        except Exception:
            pass

    return False


def _web__strip_search_prefix(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    prefixes = [
        r"^\s*(请\s*)?(帮我\s*)?(搜索|查询|检索|查一下|查查|查一查)\s*",
        r"^\s*(please\s*)?(search|look\s*up|lookup)\s*",
    ]
    for p in prefixes:
        try:
            t2 = re.sub(p, "", t, flags=re.IGNORECASE).strip()
            if t2 and (t2 != t):
                t = t2
                break
        except Exception:
            pass
    return t.strip().strip('，。,.!?！？"“”\'')
'''
        lines = insert_after_def(lines, "_is_news_query", helpers)

    # Patch web_search env config & error code
    lines = patch_web_search_config(lines)

    # Insert route branch for web search
    lines = insert_web_route_branch(lines)

    write_lines(APP, lines)


def main():
    if not os.path.exists(APP):
        raise SystemExit("ERROR: {0} not found".format(APP))

    bak = backup_file(APP)
    apply_patch()
    print("OK patched: {0}".format(APP))
    print("Backup: {0}".format(bak))
    print("Next: python3 -m py_compile app.py".format())


if __name__ == "__main__":
    main()
