#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import os
import sys
import re

TARGET = "app.py"

NEW_FORMATTER = [
"def _news__format_voice_miniflux(items: list, limit: int = 5) -> str:\n",
"    \"\"\"Voice-friendly news lines (titles only).\n",
"    - No source/time/URL\n",
"    - Prefer translated title fields when available\n",
"    \"\"\"\n",
"    try:\n",
"        lim = int(limit)\n",
"    except Exception:\n",
"        lim = 5\n",
"    if lim < 1:\n",
"        lim = 1\n",
"    if lim > 10:\n",
"        lim = 10\n",
"\n",
"    it = items or []\n",
"    if (not isinstance(it, list)) or (len(it) == 0):\n",
"        return \"\"\n",
"\n",
"    def _clean_title(s: str) -> str:\n",
"        t = (s or \"\").strip()\n",
"        # remove trailing video markers\n",
"        t = re.sub(r\"\\s*[\\-–—]\\s*video\\s*$\", \"\", t, flags=re.I).strip()\n",
"        t = re.sub(r\"\\s*\\|\\s*video\\s*$\", \"\", t, flags=re.I).strip()\n",
"        return t\n",
"\n",
"    out = []\n",
"    idx = 1\n",
"    for x in it:\n",
"        if idx > lim:\n",
"            break\n",
"        if not isinstance(x, dict):\n",
"            continue\n",
"        title = str(x.get(\"title_voice\") or x.get(\"title_zh\") or x.get(\"title\") or \"\").strip()\n",
"        title = _clean_title(title)\n",
"        if not title:\n",
"            continue\n",
"        if len(title) > 120:\n",
"            title = title[:120].rstrip() + \"…\"\n",
"        out.append(str(idx) + \") \" + title)\n",
"        idx += 1\n",
"\n",
"    return \"\\n\".join(out).strip()\n",
"\n",
]

def _leading_spaces(s):
    i = 0
    while i < len(s) and s[i] == " ":
        i += 1
    return i

def replace_top_level_func(src_lines, func_name, new_block_lines):
    # find "def func_name" at top-level
    start = None
    for i, ln in enumerate(src_lines):
        if _leading_spaces(ln) == 0 and ln.startswith("def " + func_name):
            start = i
            break
    if start is None:
        return None, "Cannot find top-level def {0}".format(func_name)

    end = None
    for j in range(start + 1, len(src_lines)):
        ln = src_lines[j]
        if _leading_spaces(ln) == 0 and ln.startswith("def "):
            end = j
            break
        if _leading_spaces(ln) == 0 and (ln.startswith("import ") or ln.startswith("from ")):
            end = j
            break
    if end is None:
        end = len(src_lines)

    out = src_lines[:start] + new_block_lines + src_lines[end:]
    return out, None

def patch_route_request(src_lines):
    # locate route_request block
    start = None
    for i, ln in enumerate(src_lines):
        if _leading_spaces(ln) == 0 and ln.startswith("def route_request("):
            start = i
            break
    if start is None:
        return None, "Cannot find def route_request"

    # find end of function (next top-level def or decorator)
    end = None
    for j in range(start + 1, len(src_lines)):
        ln = src_lines[j]
        if _leading_spaces(ln) == 0 and (ln.startswith("def ") or ln.startswith("@mcp.tool")):
            end = j
            break
    if end is None:
        end = len(src_lines)

    block = src_lines[start:end]

    # 1) update signature to accept language
    block[0] = re.sub(r"def route_request\(\s*text:\s*str\s*\)\s*->\s*dict\s*:",
                      "def route_request(text: str, language: str = None) -> dict:",
                      block[0])

    # 2) insert prefer_lang derivation after empty-text early return
    insert_after = None
    for i, ln in enumerate(block):
        if "return {\"ok\": True, \"route_type\": \"open_domain\"" in ln:
            insert_after = i
            break
    if insert_after is None:
        return None, "Cannot find early return anchor in route_request"

    prefer_block = [
        "\n",
        "    # derive prefer_lang from HA-provided language (e.g., zh-CN) when present\n",
        "    lang = str(language or \"\").strip().lower()\n",
        "    prefer_lang = \"zh\" if lang.startswith(\"zh\") else \"en\"\n",
        "    # fallback: if HA didn't pass language, infer from user text\n",
        "    if (not lang) and (\"_has_cjk\" in globals()):\n",
        "        try:\n",
        "            prefer_lang = \"zh\" if _has_cjk(user_text) else \"en\"\n",
        "        except Exception:\n",
        "            prefer_lang = \"zh\"\n",
        "\n",
    ]
    block = block[:insert_after+1] + prefer_block + block[insert_after+1:]

    # 3) pass prefer_lang through both news branches
    out_block = []
    for ln in block:
        if "rrn = news_digest(" in ln and "prefer_lang=" in ln:
            ln = re.sub(r"prefer_lang\s*=\s*\"zh\"", "prefer_lang=prefer_lang", ln)
        if ln.strip().startswith("data = news_digest("):
            # make sure it uses lim + prefer_lang + user_text
            ln = re.sub(r"data\s*=\s*news_digest\((.*)\)\s*$",
                        "        data = news_digest(category=cat, time_range=tr, limit=lim, prefer_lang=prefer_lang, user_text=user_text)\n",
                        ln)
        out_block.append(ln)

    return src_lines[:start] + out_block + src_lines[end:], None

def patch_news_digest(src_lines):
    # locate news_digest block
    start = None
    for i, ln in enumerate(src_lines):
        if _leading_spaces(ln) == 0 and ln.startswith("def news_digest("):
            start = i
            break
    if start is None:
        return None, "Cannot find def news_digest"

    end = None
    for j in range(start + 1, len(src_lines)):
        ln = src_lines[j]
        if _leading_spaces(ln) == 0 and ln.startswith("def ") and (not ln.startswith("def news_digest(")):
            end = j
            break
    if end is None:
        end = len(src_lines)

    block = src_lines[start:end]

    # A) insert prefer_lang normalization + ollama translate helper AFTER _has_cjk definition
    insert_at = None
    for i, ln in enumerate(block):
        if ln.strip().startswith("def _kw_hit("):
            insert_at = i
            break
    if insert_at is None:
        return None, "Cannot find insertion anchor (def _kw_hit) in news_digest"

    helper = [
        "\n",
        "    # normalize prefer_lang\n",
        "    pl = str(prefer_lang or \"\").strip().lower()\n",
        "    if pl.startswith(\"zh\"):\n",
        "        prefer_lang = \"zh\"\n",
        "    elif pl.startswith(\"en\"):\n",
        "        prefer_lang = \"en\"\n",
        "    else:\n",
        "        prefer_lang = \"zh\" if _has_cjk(user_text) else \"en\"\n",
        "\n",
        "    def _ollama_translate_batch(titles: list) -> list:\n",
        "        # Best-effort batch translation (titles only)\n",
        "        if not titles:\n",
        "            return []\n",
        "        base = str(os.environ.get(\"OLLAMA_BASE_URL\") or \"http://192.168.1.162:11434\").rstrip(\"/\")\n",
        "        model = str(os.environ.get(\"OLLAMA_TRANSLATE_MODEL\") or \"qwen3:1.7b\").strip() or \"qwen3:1.7b\"\n",
        "        url = base + \"/api/generate\"\n",
        "        # numbered lines in, numbered lines out\n",
        "        in_lines = []\n",
        "        i = 1\n",
        "        for t in titles:\n",
        "            s = str(t or \"\").strip()\n",
        "            if not s:\n",
        "                s = \"(empty)\"\n",
        "            if len(s) > 140:\n",
        "                s = s[:140].rstrip() + \"…\"\n",
        "            in_lines.append(str(i) + \". \" + s)\n",
        "            i += 1\n",
        "        prompt = (\n",
        "            \"把下面每一行英文标题翻译成中文。\\n\"\n",
        "            \"要求：只输出对应的中文标题列表，每行一个，不要加解释，不要加序号，不要加任何多余文字。\\n\"\n",
        "            \"保留专有名词/型号/人名的原文或常见译名。\\n\\n\"\n",
        "            + \"\\n\".join(in_lines)\n",
        "        )\n",
        "        payload = {\n",
        "            \"model\": model,\n",
        "            \"prompt\": prompt,\n",
        "            \"stream\": False,\n",
        "            \"keep_alive\": -1,\n",
        "            \"options\": {\"temperature\": 0.2, \"num_ctx\": 2048}\n",
        "        }\n",
        "        try:\n",
        "            r = requests.post(url, json=payload, timeout=14)\n",
        "            if int(getattr(r, \"status_code\", 0) or 0) >= 400:\n",
        "                return []\n",
        "            j = r.json() if hasattr(r, \"json\") else {}\n",
        "            txt = str((j.get(\"response\") or \"\")).strip()\n",
        "            if not txt:\n",
        "                return []\n",
        "            out = [x.strip() for x in txt.splitlines() if x.strip()]\n",
        "            # if model echoed numbering, strip it\n",
        "            cleaned = []\n",
        "            for x in out:\n",
        "                x2 = re.sub(r\"^\\s*\\d+\\s*[\\.|\\)|、]\\s*\", \"\", x).strip()\n",
        "                cleaned.append(x2)\n",
        "            return cleaned\n",
        "        except Exception:\n",
        "            return []\n",
        "\n",
    ]

    block = block[:insert_at] + helper + block[insert_at:]

    # B) after out_items = picked[:lim_int], translate EN titles if prefer_lang == zh
    anchor = None
    for i, ln in enumerate(block):
        if ln.strip() == "out_items = picked[:lim_int]":
            anchor = i
            break
    if anchor is None:
        return None, "Cannot find anchor out_items = picked[:lim_int]"

    trans_block = [
        "\n",
        "    # Build voice title field (translate EN titles when prefer_lang=zh)\n",
        "    try:\n",
        "        want_zh = (str(prefer_lang or \"\").strip().lower() == \"zh\")\n",
        "    except Exception:\n",
        "        want_zh = True\n",
        "    if want_zh:\n",
        "        need = []\n",
        "        need_idx = []\n",
        "        for ii, it in enumerate(out_items):\n",
        "            try:\n",
        "                tt = str(it.get(\"title\") or \"\").strip()\n",
        "            except Exception:\n",
        "                tt = \"\"\n",
        "            if not tt:\n",
        "                continue\n",
        "            if _has_cjk(tt):\n",
        "                it[\"title_voice\"] = tt\n",
        "            else:\n",
        "                need.append(tt)\n",
        "                need_idx.append(ii)\n",
        "        if need:\n",
        "            tr = _ollama_translate_batch(need)\n",
        "            if tr and (len(tr) >= len(need_idx)):\n",
        "                for k, ii in enumerate(need_idx):\n",
        "                    out_items[ii][\"title_voice\"] = str(tr[k] or \"\").strip() or str(out_items[ii].get(\"title\") or \"\").strip()\n",
        "            else:\n",
        "                # fallback: keep English if translation failed\n",
        "                for ii in need_idx:\n",
        "                    out_items[ii][\"title_voice\"] = str(out_items[ii].get(\"title\") or \"\").strip()\n",
        "    else:\n",
        "        for it in out_items:\n",
        "            try:\n",
        "                it[\"title_voice\"] = str(it.get(\"title\") or \"\").strip()\n",
        "            except Exception:\n",
        "                pass\n",
        "\n",
    ]
    block = block[:anchor+1] + trans_block + block[anchor+1:]

    return src_lines[:start] + block + src_lines[end:], None

def main():
    if not os.path.exists(TARGET):
        print("ERROR: {0} not found".format(TARGET))
        sys.exit(2)

    with io.open(TARGET, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # backup
    bak = TARGET + ".bak.before_news_B2"
    if not os.path.exists(bak):
        with io.open(bak, "w", encoding="utf-8") as f:
            f.writelines(lines)

    # 1) formatter
    lines2, err = replace_top_level_func(lines, "_news__format_voice_miniflux", NEW_FORMATTER)
    if err:
        print("ERROR:", err)
        sys.exit(3)

    # 2) route_request
    lines3, err = patch_route_request(lines2)
    if err:
        print("ERROR:", err)
        sys.exit(4)

    # 3) news_digest
    lines4, err = patch_news_digest(lines3)
    if err:
        print("ERROR:", err)
        sys.exit(5)

    with io.open(TARGET, "w", encoding="utf-8") as f:
        f.writelines(lines4)

    print("OK: patched formatter + route_request(language) + news_digest(ollama translate). backup:", bak)

if __name__ == "__main__":
    main()
