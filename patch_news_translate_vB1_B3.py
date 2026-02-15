import io
import re

PATH = "app.py"

def read_text(p):
    with io.open(p, "r", encoding="utf-8") as f:
        return f.read()

def write_text(p, s):
    with io.open(p, "w", encoding="utf-8") as f:
        f.write(s)

s = read_text(PATH)

# -------------------------
# 1) Replace _news__format_voice_miniflux (no source/time; prefer title_zh/snippet_zh)
# -------------------------
def replace_format_voice(src):
    m1 = re.search(r"^def _news__format_voice_miniflux\([^\n]*\):\n", src, flags=re.M)
    if not m1:
        raise SystemExit("Cannot find _news__format_voice_miniflux()")

    start = m1.start()
    # end: before the first top-level "import " after this function
    m2 = re.search(r"^\s*import\s+os\s*$", src[m1.end():], flags=re.M)
    if not m2:
        raise SystemExit("Cannot locate end boundary for _news__format_voice_miniflux() (import os not found)")
    end = m1.end() + m2.start()

    new_func = (
        "def _news__format_voice_miniflux(items: list, limit: int = 5) -> str:\n"
        "    \"\"\"Voice-friendly news lines for TTS.\n"
        "    - No URL\n"
        "    - No source/time\n"
        "    - Prefer translated fields title_zh/snippet_zh when present\n"
        "    - Short snippet\n"
        "    \"\"\"\n"
        "    try:\n"
        "        lim = int(limit)\n"
        "    except Exception:\n"
        "        lim = 5\n"
        "    if lim < 1:\n"
        "        lim = 1\n"
        "    if lim > 10:\n"
        "        lim = 10\n"
        "\n"
        "    it = items or []\n"
        "    if (not isinstance(it, list)) or (len(it) == 0):\n"
        "        return \"\"\n"
        "\n"
        "    out = []\n"
        "    idx = 1\n"
        "    for x in it:\n"
        "        if idx > lim:\n"
        "            break\n"
        "        if not isinstance(x, dict):\n"
        "            continue\n"
        "        title = str(x.get(\"title_zh\") or x.get(\"title\") or \"\").strip()\n"
        "        if not title:\n"
        "            continue\n"
        "        sn = str(x.get(\"snippet_zh\") or \"\").strip()\n"
        "        # tighten snippet for TTS\n"
        "        if sn and (len(sn) > 88):\n"
        "            sn = sn[:88].rstrip() + \"…\"\n"
        "\n"
        "        out.append(str(idx) + \") \" + title)\n"
        "        if sn:\n"
        "            out.append(\"   \" + sn)\n"
        "        idx += 1\n"
        "\n"
        "    return \"\\n\".join(out).strip()\n"
        "\n"
    )

    return src[:start] + new_func + src[end:]

s = replace_format_voice(s)

# -------------------------
# 2) route_request: accept language, derive prefer_lang, pass into news_digest
# -------------------------
# signature
s2 = re.sub(
    r"^def route_request\(\s*text:\s*str\s*\)\s*->\s*dict\s*:",
    "def route_request(text: str, language: str = None) -> dict:",
    s,
    flags=re.M
)
s = s2

# insert prefer_lang derivation after user_text assignment
anchor = "    user_text = str(text or \"\").strip()\n"
ins = (
    anchor +
    "    # language hint from HA (e.g. zh-CN/en-US). Fallback: detect CJK in user_text.\n"
    "    lang0 = \"\"\n"
    "    try:\n"
    "        lang0 = str(language or \"\").strip().lower()\n"
    "    except Exception:\n"
    "        lang0 = \"\"\n"
    "    prefer_lang = None\n"
    "    if lang0.startswith(\"zh\"):\n"
    "        prefer_lang = \"zh\"\n"
    "    elif lang0.startswith(\"en\"):\n"
    "        prefer_lang = \"en\"\n"
    "    if not prefer_lang:\n"
    "        prefer_lang = \"zh\" if re.search(r\"[\\u4e00-\\u9fff]\", user_text or \"\") else \"en\"\n"
)
if anchor in s:
    if "prefer_lang = None" not in s[s.find(anchor):s.find(anchor)+600]:
        s = s.replace(anchor, ins, 1)

# pass prefer_lang into both news branches
s = s.replace(
    'news_digest(category=cat, limit=_news__extract_limit(user_text, 3), time_range=tr, prefer_lang="zh", user_text=user_text)',
    'news_digest(category=cat, limit=_news__extract_limit(user_text, 3), time_range=tr, prefer_lang=prefer_lang, user_text=user_text)'
)

# _is_news_query branch: add prefer_lang param if not already there
s = re.sub(
    r"news_digest\(\s*category=cat,\s*time_range=tr,\s*limit=_news__extract_limit\(user_text,\s*3\)\s*\)",
    "news_digest(category=cat, time_range=tr, limit=_news__extract_limit(user_text, 3), prefer_lang=prefer_lang)",
    s
)

# -------------------------
# 3) news_digest: add prefer_lang echo + batch translate title+snippet via Ollama keep_alive=-1
# -------------------------
m_news = re.search(r"^def news_digest\([^\n]*\)\s*->\s*dict\s*:\n", s, flags=re.M)
if not m_news:
    # signature may be without return annotation
    m_news = re.search(r"^def news_digest\([^\n]*\)\s*:\n", s, flags=re.M)
if not m_news:
    raise SystemExit("Cannot find news_digest()")

# add prefer normalization after lim_int clamp
# locate the clamp block end: 'if lim_int > 10:' then next lines
pat_lim = r"(    if lim_int > 10:\n        lim_int = 10\n)"
m_lim = re.search(pat_lim, s)
if not m_lim:
    raise SystemExit("Cannot locate lim_int clamp block in news_digest()")

prefer_block = (
    m_lim.group(1) + "\n\n"
    "    prefer = str(prefer_lang or \"zh\").strip().lower()\n"
    "    if prefer.startswith(\"zh\"):\n"
    "        prefer = \"zh\"\n"
    "    elif prefer.startswith(\"en\"):\n"
    "        prefer = \"en\"\n"
    "    else:\n"
    "        prefer = \"zh\"\n"
)

if "prefer = str(prefer_lang or \"zh\")" not in s[m_lim.start():m_lim.start()+500]:
    s = s[:m_lim.start()] + prefer_block + s[m_lim.end():]

# insert Ollama helpers inside news_digest (after _to_local_time helper)
anchor2 = "    def _to_local_time(iso_str: str) -> str:\n"
pos2 = s.find(anchor2)
if pos2 < 0:
    raise SystemExit("Cannot locate _to_local_time helper in news_digest()")
# find end of _to_local_time helper by next 'def ' at same indent (4 spaces)
after2 = s.find("\n    def _has_cjk", pos2)
if after2 < 0:
    raise SystemExit("Cannot locate _has_cjk after _to_local_time in news_digest()")

ollama_helpers = (
    "\n"
    "    def _ollama_chat(messages: list, model: str, keep_alive, timeout_sec: int) -> dict:\n"
    "        base = os.environ.get(\"OLLAMA_BASE_URL\") or \"http://192.168.1.162:11434\"\n"
    "        url = base.rstrip(\"/\") + \"/api/chat\"\n"
    "        payload = {\n"
    "            \"model\": model,\n"
    "            \"messages\": messages,\n"
    "            \"stream\": False,\n"
    "            \"keep_alive\": keep_alive,\n"
    "        }\n"
    "        try:\n"
    "            rr = requests.post(url, json=payload, timeout=timeout_sec)\n"
    "            sc = int(getattr(rr, \"status_code\", 0) or 0)\n"
    "            if sc >= 400:\n"
    "                return {\"ok\": False, \"status\": sc, \"text\": (rr.text or \"\")[:500]}\n"
    "            data = rr.json() if hasattr(rr, \"json\") else {}\n"
    "            # Ollama chat returns {message:{content:...}}\n"
    "            msg = data.get(\"message\") or {}\n"
    "            content = msg.get(\"content\") or data.get(\"response\") or \"\"\n"
    "            return {\"ok\": True, \"content\": str(content or \"\")}\n"
    "        except Exception as e:\n"
    "            return {\"ok\": False, \"error\": str(e)}\n"
    "\n"
    "    def _news_translate_batch(pairs: list) -> dict:\n"
    "        # pairs: [{\"i\":1,\"title\":\"...\",\"snippet\":\"...\"}, ...]\n"
    "        model = os.environ.get(\"NEWS_TRANSLATE_MODEL\") or \"qwen3:1.7b\"\n"
    "        ka0 = os.environ.get(\"NEWS_TRANSLATE_KEEPALIVE\")\n"
    "        keep_alive = -1\n"
    "        if ka0 is not None and str(ka0).strip() != \"\":\n"
    "            try:\n"
    "                keep_alive = int(str(ka0).strip())\n"
    "            except Exception:\n"
    "                keep_alive = str(ka0).strip()\n"
    "        timeout_sec = 18\n"
    "        t0 = os.environ.get(\"NEWS_TRANSLATE_TIMEOUT_SEC\")\n"
    "        if t0:\n"
    "            try:\n"
    "                timeout_sec = int(str(t0).strip())\n"
    "            except Exception:\n"
    "                timeout_sec = 18\n"
    "\n"
    "        sys_prompt = (\n"
    "            \"你是专业新闻翻译助手。把英文新闻标题和摘要翻译成简洁、自然、适合中文语音播报的中文。\"\n"
    "            \"严格要求：只翻译，不要添加原文没有的事实或背景；保留专有名词（可音译或保留英文）。\"\n"
    "            \"输出必须是纯 JSON 数组，每个元素包含 i, title_zh, snippet_zh 三个字段。\"\n"
    "            \"不要输出任何多余文字，不要代码块标记。\"\n"
    "        )\n"
    "        user_payload = json.dumps(pairs, ensure_ascii=False)\n"
    "        msgs = [\n"
    "            {\"role\": \"system\", \"content\": sys_prompt},\n"
    "            {\"role\": \"user\", \"content\": user_payload},\n"
    "        ]\n"
    "        rr = _ollama_chat(msgs, model=model, keep_alive=keep_alive, timeout_sec=timeout_sec)\n"
    "        if not rr.get(\"ok\"):\n"
    "            return {\"ok\": False, \"detail\": rr}\n"
    "        content = (rr.get(\"content\") or \"\").strip()\n"
    "        # strip accidental fences\n"
    "        if content.startswith(\"```\"):\n"
    "            content = re.sub(r\"^```[a-zA-Z0-9_\\-]*\\n\", \"\", content)\n"
    "            content = re.sub(r\"\\n```\\s*$\", \"\", content).strip()\n"
    "        try:\n"
    "            data = json.loads(content)\n"
    "        except Exception as e:\n"
    "            return {\"ok\": False, \"error\": \"json_parse_failed\", \"detail\": str(e), \"content_head\": content[:220]}\n"
    "        if not isinstance(data, list):\n"
    "            return {\"ok\": False, \"error\": \"json_not_list\", \"content_head\": content[:220]}\n"
    "        out = {}\n"
    "        for row in data:\n"
    "            if not isinstance(row, dict):\n"
    "                continue\n"
    "            i0 = row.get(\"i\")\n"
    "            try:\n"
    "                i1 = int(i0)\n"
    "            except Exception:\n"
    "                continue\n"
    "            out[i1] = {\n"
    "                \"title_zh\": str(row.get(\"title_zh\") or \"\").strip(),\n"
    "                \"snippet_zh\": str(row.get(\"snippet_zh\") or \"\").strip(),\n"
    "            }\n"
    "        return {\"ok\": True, \"map\": out}\n"
)

# only insert once
if "_news_translate_batch" not in s[pos2:after2]:
    s = s[:after2] + ollama_helpers + s[after2:]

# insert translation call after out_items selection
needle = "out_items = picked[:lim_int]\n"
pos3 = s.find(needle, m_news.start())
if pos3 < 0:
    raise SystemExit("Cannot locate out_items assignment in news_digest()")

if "news_translate_batch" not in s[pos3:pos3+900]:
    trans_call = (
        needle +
        "\n"
        "    # Batch translate EN->ZH for voice (Plan B: title + snippet)\n"
        "    if prefer == \"zh\":\n"
        "        pairs = []\n"
        "        for i, it2 in enumerate(out_items, 1):\n"
        "            if not isinstance(it2, dict):\n"
        "                continue\n"
        "            if bool(it2.get(\"is_zh\")):\n"
        "                # already CJK\n"
        "                it2[\"title_zh\"] = str(it2.get(\"title\") or \"\").strip()\n"
        "                it2[\"snippet_zh\"] = str(it2.get(\"snippet\") or \"\").strip()\n"
        "                continue\n"
        "            t_en = str(it2.get(\"title\") or \"\").strip()\n"
        "            s_en = str(it2.get(\"snippet\") or \"\").strip()\n"
        "            if len(s_en) > 260:\n"
        "                s_en = s_en[:260].rstrip() + \"…\"\n"
        "            pairs.append({\"i\": i, \"title\": t_en, \"snippet\": s_en})\n"
        "        if pairs:\n"
        "            trr = _news_translate_batch(pairs)\n"
        "            if trr.get(\"ok\"):\n"
        "                mp = trr.get(\"map\") or {}\n"
        "                for i, it2 in enumerate(out_items, 1):\n"
        "                    if not isinstance(it2, dict):\n"
        "                        continue\n"
        "                    if bool(it2.get(\"is_zh\")):\n"
        "                        continue\n"
        "                    row = mp.get(i) or {}\n"
        "                    tz = str(row.get(\"title_zh\") or \"\").strip()\n"
        "                    sz = str(row.get(\"snippet_zh\") or \"\").strip()\n"
        "                    if tz:\n"
        "                        it2[\"title_zh\"] = tz\n"
        "                    if sz:\n"
        "                        it2[\"snippet_zh\"] = sz\n"
        "\n"
    )
    s = s.replace(needle, trans_call, 1)

# add ret["prefer_lang"] and ensure final_voice uses formatter
needle_ret = "    if (\"final_voice\" not in ret) or (not str(ret.get(\"final_voice\") or \"\").strip()):\n"
pos4 = s.find(needle_ret, m_news.start())
if pos4 < 0:
    raise SystemExit("Cannot locate final_voice fill block in news_digest()")

# insert prefer_lang echo once before that block
before = s[:pos4]
after = s[pos4:]
if "ret[\"prefer_lang\"]" not in before[-400:]:
    before = before + "    ret[\"prefer_lang\"] = prefer\n"
s = before + after

# force ret["final_voice"] to always be formatter output (after translation)
# Replace the conditional fill with unconditional assignment, but only if not already done.
pat_fill = (
    r"    if\s+\(\"final_voice\" not in ret\)\s+or\s+\(not str\(ret\.get\(\"final_voice\"\) or \"\"\)\.strip\(\)\):\n"
    r"        ret\[\"final_voice\"\]\s*=\s*_news__format_voice_miniflux\(ret\.get\(\"items\"\) or \[\], ret\.get\(\"limit\"\) or 5\)\n"
)
m_fill = re.search(pat_fill, s)
if m_fill:
    repl = "    ret[\"final_voice\"] = _news__format_voice_miniflux(ret.get(\"items\") or [], ret.get(\"limit\") or 5)\n"
    s = s[:m_fill.start()] + repl + s[m_fill.end():]

write_text(PATH, s)
print("OK patched", PATH)
