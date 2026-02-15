import sys

PATH = "app.py"

def die(msg):
    sys.stderr.write(msg + "\n")
    sys.exit(1)

s = open(PATH, "r", encoding="utf-8", errors="replace").read()
orig = s

# ---------- 0) 必要锚点检查 ----------
need = [
    "def _mcp__mk_keywords(query):",
    "def _mcp__is_relevant(title, snippet, kws):",
    "def web_search(",
    "prefer_zh = True if str(lang_used or \"\").strip().lower().startswith(\"zh\") else False",
]
for n in need:
    if n not in s:
        die("Required block not found: " + n)

# ---------- 1) _mcp__mk_keywords：中文分支也保留 ASCII tokens + bigrams（通用） ----------
if "MCP_KW_V4" not in s:
    anchor_else = "\n    else:\n        toks = re.findall(r\"[A-Za-z0-9]{3,}\", q)\n"
    pos = s.find(anchor_else)
    if pos < 0:
        die("Cannot locate mk_keywords else-branch anchor")

    inject = (
        "\n        # MCP_KW_V4: keep ASCII tokens + bigrams for mixed-language queries (generic)\n"
        "        ascii_tokens = re.findall(r\"[A-Za-z0-9]{2,}\", q)\n"
        "        ascii_tokens = [t.lower() for t in ascii_tokens if t]\n"
        "        for t in ascii_tokens:\n"
        "            if t not in kws:\n"
        "                kws.append(t)\n"
        "        if len(ascii_tokens) >= 2:\n"
        "            i = 0\n"
        "            while i + 1 < len(ascii_tokens):\n"
        "                bg = ascii_tokens[i] + \" \" + ascii_tokens[i + 1]\n"
        "                if bg not in kws:\n"
        "                    kws.append(bg)\n"
        "                i += 1\n"
        "        kws = kws[:12]\n"
    )
    s = s[:pos] + inject + s[pos:]

# ---------- 2) _mcp__is_relevant：从“命中任意词”改为“多词命中”+ 弱词降权（通用） ----------
if "MCP_REL_V4" not in s:
    anchor = "    tl = t.lower()\n"
    pos = s.find(anchor)
    if pos < 0:
        die("Cannot locate 'tl = t.lower()' anchor in _mcp__is_relevant")

    add = (
        anchor +
        "    # MCP_REL_V4: generic multi-keyword relevance (avoid single ambiguous token dominating)\n"
        "    try:\n"
        "        weak_words = set([\"home\", \"app\", \"login\", \"download\", \"官网\", \"入口\"])\n"
        "        kws2 = []\n"
        "        for k in (kws or []):\n"
        "            kk = str(k or \"\").strip().lower()\n"
        "            if kk:\n"
        "                kws2.append(kk)\n"
        "        hit = 0\n"
        "        seen = set()\n"
        "        for k in kws2:\n"
        "            if (k in weak_words) and (\" \" not in k):\n"
        "                continue\n"
        "            if (k in tl) and (k not in seen):\n"
        "                seen.add(k)\n"
        "                hit += 1\n"
        "        # If we have >=3 keywords, require >=2 hits\n"
        "        if len(kws2) >= 3 and hit < 2:\n"
        "            return False\n"
        "    except Exception:\n"
        "        pass\n"
    )
    s = s.replace(anchor, add, 1)

# ---------- 3) web_search：替换“第一个就 break”的 best 选择为 score-based（通用） ----------
if "MCP_WS_V4" not in s:
    old_sel = (
        "for it in results_out:\n"
        "            if not _mcp__is_relevant(it.get(\"title\"), it.get(\"snippet\"), kws):\n"
        "                continue\n"
        "            if prefer_zh:\n"
        "                t = (it.get(\"title\") or \"\") + \" \" + (it.get(\"snippet\") or \"\")\n"
        "                if not _mcp__has_zh(t):\n"
        "                    continue\n"
        "            best = it\n"
        "            break\n"
        "\n"
        "        if best is None and prefer_zh:\n"
        "            for it in results_out:\n"
        "                t = (it.get(\"title\") or \"\") + \" \" + (it.get(\"snippet\") or \"\")\n"
        "                if _mcp__has_zh(t):\n"
        "                    best = it\n"
        "                    break\n"
        "\n"
        "        if best is None and top:\n"
        "            best = top[0]\n"
        "\n"
        "        \n"
    )
    if old_sel not in s:
        die("Cannot find expected best-selection block in web_search (baseline mismatch).")

    new_sel = (
        "        # MCP_WS_V4: score-based selection (generic)\n"
        "        def _score(it):\n"
        "            try:\n"
        "                title = it.get(\"title\")\n"
        "                snippet = it.get(\"snippet\")\n"
        "                t = (str(title or \"\") + \" \" + str(snippet or \"\")).lower()\n"
        "                weak = set([\"home\", \"app\", \"login\", \"download\", \"官网\", \"入口\"])\n"
        "                kws2 = [str(k or \"\").strip().lower() for k in (kws or []) if str(k or \"\").strip()]\n"
        "                hit = 0\n"
        "                phrase_hit = 0\n"
        "                seen = set()\n"
        "                for k in kws2:\n"
        "                    if (k in weak) and (\" \" not in k):\n"
        "                        continue\n"
        "                    if (k in t) and (k not in seen):\n"
        "                        seen.add(k)\n"
        "                        hit += 1\n"
        "                    if (\" \" in k) and (k in t):\n"
        "                        phrase_hit += 1\n"
        "                zh_bonus = 3 if (prefer_zh and _mcp__has_zh(t)) else 0\n"
        "                return (hit * 10) + (phrase_hit * 6) + zh_bonus\n"
        "            except Exception:\n"
        "                return 0\n"
        "\n"
        "        best = None\n"
        "        best_score = -1\n"
        "        for it in results_out:\n"
        "            if not _mcp__is_relevant(it.get(\"title\"), it.get(\"snippet\"), kws):\n"
        "                continue\n"
        "            sc = _score(it)\n"
        "            if sc > best_score:\n"
        "                best_score = sc\n"
        "                best = it\n"
        "\n"
        "        if best is None and top:\n"
        "            best = top[0]\n"
        "        # MCP_WS_V4 END\n"
        "\n"
    )

    s = s.replace(old_sel, new_sel, 1)

# ---------- 4) web_search 返回增加 best_title（你现在 r.get('best_title') 为 None 是因为没返回该字段） ----------
if "\"best_title\":" not in s:
    ret_anchor = "        \"best_url\": (evidence.get(\"best_url\") if isinstance(evidence, dict) else None),\n"
    if ret_anchor not in s:
        die("Cannot locate web_search return best_url line")
    s = s.replace(
        ret_anchor,
        ret_anchor + "        \"best_title\": (evidence.get(\"best_title\") if isinstance(evidence, dict) else None),\n",
        1,
    )

if s == orig:
    die("Patch produced no changes (unexpected).")

open(PATH, "w", encoding="utf-8").write(s)
print("OK: patch applied: general_relevance_v4")
