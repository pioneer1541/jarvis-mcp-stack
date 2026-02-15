import re
import sys

PATH = "app.py"

def die(msg):
    sys.stderr.write(msg + "\n")
    sys.exit(1)

s = open(PATH, "r", encoding="utf-8", errors="replace").read()
orig = s

# ------------------------------------------------------------
# A) _mcp__mk_keywords: zh query also keep ASCII tokens (Home Assistant Voice PE...)
# Insert just before the "else:" that handles non-zh.
# ------------------------------------------------------------
mk_pat = re.compile(r"def _mcp__mk_keywords\(query\):[\s\S]*?\n\s*return kws\n", re.DOTALL)
m = mk_pat.search(s)
if not m:
    die("Cannot find _mcp__mk_keywords() block")

mk_block = m.group(0)
if "MCP_KW_V1" not in mk_block:
    # Find the 'else:' that corresponds to 'if _mcp__has_zh(q):'
    # Pattern: zh-branch ends, then "\n    else:" at indent 4.
    p = re.compile(r"(if _mcp__has_zh\(q\):[\s\S]*?\n)(\s*else:\n\s*toks\s*=\s*re\.findall)", re.DOTALL)
    m2 = p.search(mk_block)
    if not m2:
        die("Cannot locate insertion point before else: in _mcp__mk_keywords")

    insert = (
        "        # MCP_KW_V1: also keep ASCII tokens (e.g. Home Assistant Voice PE)\n"
        "        ascii_tokens = re.findall(r\"[A-Za-z0-9]{2,}\", q)\n"
        "        ascii_tokens = [t.lower() for t in ascii_tokens if t]\n"
        "        # Add a strong phrase token when both words exist\n"
        "        if (\"home\" in ascii_tokens) and (\"assistant\" in ascii_tokens) and (\"home assistant\" not in kws):\n"
        "            kws.append(\"home assistant\")\n"
        "        # Prefer domain anchors\n"
        "        prefer = [\"homeassistant\", \"hass\", \"assistant\", \"voice\", \"assist\", \"voicepe\", \"pe\", \"mcp\"]\n"
        "        for t in prefer:\n"
        "            if t in ascii_tokens and (t not in kws):\n"
        "                kws.append(t)\n"
        "        # Add remaining ascii tokens, but avoid 'home' alone (too noisy)\n"
        "        for t in ascii_tokens:\n"
        "            if t == \"home\":\n"
        "                continue\n"
        "            if t not in kws:\n"
        "                kws.append(t)\n"
        "        kws = kws[:10]\n"
    )

    mk_block2 = m2.group(1) + insert + m2.group(2)
    mk_block_new = mk_block[:m2.start()] + mk_block2 + mk_block[m2.end():]
    s = s.replace(mk_block, mk_block_new, 1)

# ------------------------------------------------------------
# B) _mcp__is_relevant: if kws imply Home Assistant, require anchor to avoid "Home键在哪"
# ------------------------------------------------------------
rel_pat = re.compile(r"def _mcp__is_relevant\(title, snippet, kws\):[\s\S]*?\n\s*return False\n", re.DOTALL)
m3 = rel_pat.search(s)
if not m3:
    die("Cannot find _mcp__is_relevant() block")
rel_block = m3.group(0)

if "MCP_REL_V1" not in rel_block:
    # Insert after tl = t.lower()
    ins = re.search(r"(tl\s*=\s*t\.lower\(\)\n)", rel_block)
    if not ins:
        die("Cannot locate 'tl = t.lower()' in _mcp__is_relevant")
    add = ins.group(1) + (
        "    # MCP_REL_V1: avoid false positives like 'Home键在哪' when keywords imply Home Assistant\n"
        "    try:\n"
        "        kwset = set([str(k or \"\").strip().lower() for k in (kws or []) if str(k or \"\").strip()])\n"
        "        implied_ha = False\n"
        "        if (\"home assistant\" in kwset) or ((\"home\" in kwset) and (\"assistant\" in kwset)) or (\"homeassistant\" in kwset) or (\"hass\" in kwset):\n"
        "            implied_ha = True\n"
        "        if implied_ha:\n"
        "            anchors = [\"home assistant\", \"homeassistant\", \"assistant\", \"hass\"]\n"
        "            ok_anchor = False\n"
        "            for a in anchors:\n"
        "                if a in tl:\n"
        "                    ok_anchor = True\n"
        "                    break\n"
        "            if not ok_anchor:\n"
        "                return False\n"
        "    except Exception:\n"
        "        pass\n"
    )
    rel_block2 = rel_block.replace(ins.group(1), add, 1)
    s = s.replace(rel_block, rel_block2, 1)

# ------------------------------------------------------------
# C) web_answer: relax hard-fail on relevance_low when we already have usable answer in requested language
# ------------------------------------------------------------
wa_pat = re.compile(r"def web_answer\([\s\S]*?\n\s*return\s*\{[\s\S]*?\n\s*\}\n\s*\n# --- MCP_WEB_ANSWER_V1 END ---", re.DOTALL)
m4 = wa_pat.search(s)
if not m4:
    die("Cannot find web_answer() block")
wa_block = m4.group(0)

if "MCP_WA_RELAX_V1" not in wa_block:
    # Find the block: if (not answer) or (relevance_low is True):
    mchk = re.search(r"\n(\s*if\s*\(not answer\)\s*or\s*\(relevance_low is True\)\s*:\n)", wa_block)
    if not mchk:
        die("Cannot find relevance_low hard-fail line in web_answer")
    inject = (
        "    # MCP_WA_RELAX_V1: if we have a usable answer in requested language, don't hard-fail on relevance_low\n"
        "    try:\n"
        "        want_zh = True if str(language or \"\").strip().lower().startswith(\"zh\") else False\n"
        "        if (relevance_low is True) and answer:\n"
        "            if (not want_zh) or _mcp__has_zh(str(answer)):\n"
        "                relevance_low = False\n"
        "    except Exception:\n"
        "        pass\n\n"
    )
    wa_block2 = wa_block.replace(mchk.group(1), "\n" + inject + mchk.group(1), 1)
    s = s.replace(wa_block, wa_block2, 1)

# ------------------------------------------------------------
# D) web_answer: language guard (zh requested => never output foreign-only text)
# Insert after first_sentence try/except, before final return dict.
# ------------------------------------------------------------
if "MCP_LANG_GUARD_V1" not in s:
    # Find the first_sentence block inside web_answer
    needle = re.compile(r"(try:\n\s*answer\s*=\s*_mcp__first_sentence\(answer,\s*240\)\n\s*except Exception:\n\s*pass\n)", re.DOTALL)
    m5 = needle.search(s)
    if not m5:
        die("Cannot find first_sentence block to inject language guard")
    guard = (
        "\n    # MCP_LANG_GUARD_V1: never output foreign language when Chinese is requested\n"
        "    try:\n"
        "        want_zh = True if str(language or \"\").strip().lower().startswith(\"zh\") else False\n"
        "        if want_zh and answer and (not _mcp__has_zh(str(answer))):\n"
        "            answer = \"我目前只搜到外文信息，暂时无法可靠地用中文概括。\"\n"
        "    except Exception:\n"
        "        pass\n"
    )
    s = s[:m5.end()] + guard + s[m5.end():]

if s == orig:
    die("Patch did not change app.py (unexpected).")

open(PATH, "w", encoding="utf-8").write(s)
print("OK: patched app.py (relevance_fix_v1_1)")
