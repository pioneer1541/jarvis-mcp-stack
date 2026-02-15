import re
import sys

PATH = "app.py"

def die(msg):
    sys.stderr.write(msg + "\n")
    sys.exit(1)

s = open(PATH, "r", encoding="utf-8", errors="replace").read()
orig = s

# ---------------------------
# A) _mcp__mk_keywords: zh query also keep ASCII tokens (avoid losing "Home Assistant Voice PE")
# ---------------------------
if "MCP_KW_V1" not in s:
    # Insert inside _mcp__mk_keywords, just before the else: (non-zh branch)
    pat = re.compile(r"(def _mcp__mk_keywords\(query\):[\s\S]*?\n\s*if _mcp__has_zh\(q\):[\s\S]*?\n)(\s*else:\n\s*toks\s*=\s*re\.findall)", re.DOTALL)
    m = pat.search(s)
    if not m:
        die("Cannot locate insertion point in _mcp__mk_keywords")
    inject = (
        "        # MCP_KW_V1: also keep ASCII tokens (e.g. Home Assistant Voice PE)\n"
        "        ascii_tokens = re.findall(r\"[A-Za-z0-9]{2,}\", q)\n"
        "        ascii_tokens = [t.lower() for t in ascii_tokens if t]\n"
        "        # Add strong phrase token\n"
        "        if (\"home\" in ascii_tokens) and (\"assistant\" in ascii_tokens) and (\"home assistant\" not in kws):\n"
        "            kws.append(\"home assistant\")\n"
        "        # Prefer domain anchors\n"
        "        prefer = [\"homeassistant\", \"hass\", \"assistant\", \"voice\", \"assist\", \"voicepe\", \"pe\", \"mcp\"]\n"
        "        for t in prefer:\n"
        "            if (t in ascii_tokens) and (t not in kws):\n"
        "                kws.append(t)\n"
        "        # Add remaining ascii tokens, but avoid 'home' alone (too noisy)\n"
        "        for t in ascii_tokens:\n"
        "            if t == \"home\":\n"
        "                continue\n"
        "            if t not in kws:\n"
        "                kws.append(t)\n"
        "        kws = kws[:10]\n"
    )
    s = s[:m.start(2)]  # up to "else:"
    s = s + inject + s[m.start(2):]

# ---------------------------
# B) _mcp__is_relevant: add HA anchor requirement to avoid false positives like "Home键在哪"
# ---------------------------
# We patch function body by inserting after the line that computes t.lower()
# If not found, insert after the line "t = (...).strip()"
if "MCP_REL_V1" not in s:
    # Extract _mcp__is_relevant block (simple heuristic: until next 'def ')
    m = re.search(r"def _mcp__is_relevant\([^\)]*\):", s)
    if not m:
        die("Cannot find def _mcp__is_relevant")
    start = m.start()
    nxt = s.find("\ndef ", start + 1)
    if nxt < 0:
        die("Cannot find end of _mcp__is_relevant block")
    block = s[start:nxt]

    if "MCP_REL_V1" not in block:
        ins = None
        # Try to find any line like "<var> = t.lower()"
        m_low = re.search(r"(\n\s*\w+\s*=\s*t\.lower\(\)\s*\n)", block)
        if m_low:
            ins = m_low.end()
        else:
            # Fallback: after 't = (...).strip()' line
            m_t = re.search(r"(\n\s*t\s*=\s*\(.*?\)\.strip\(\)\s*\n)", block, re.DOTALL)
            if m_t:
                ins = m_t.end()

        if ins is None:
            die("Cannot locate insertion point in _mcp__is_relevant")

        add = (
            "    # MCP_REL_V1: avoid false positives like 'Home键在哪' when keywords imply Home Assistant\n"
            "    try:\n"
            "        kwset = set([str(k or \"\").strip().lower() for k in (kws or []) if str(k or \"\").strip()])\n"
            "        implied_ha = False\n"
            "        if (\"home assistant\" in kwset) or ((\"home\" in kwset) and (\"assistant\" in kwset)) or (\"homeassistant\" in kwset) or (\"hass\" in kwset):\n"
            "            implied_ha = True\n"
            "        if implied_ha:\n"
            "            # Require at least one HA anchor present in candidate text\n"
            "            t_all = (str(title or \"\") + \" \" + str(snippet or \"\")).lower()\n"
            "            anchors = [\"home assistant\", \"homeassistant\", \"hass\", \"assist\", \"voice\", \"mcp\"]\n"
            "            ok_anchor = False\n"
            "            for a in anchors:\n"
            "                if a in t_all:\n"
            "                    ok_anchor = True\n"
            "                    break\n"
            "            if not ok_anchor:\n"
            "                return False\n"
            "    except Exception:\n"
            "        pass\n"
        )

        block2 = block[:ins] + add + block[ins:]
        s = s[:start] + block2 + s[nxt:]

# ---------------------------
# C) web_answer: relax hard-fail on relevance_low if answer already usable in requested language
# ---------------------------
if "MCP_WA_RELAX_V1" not in s:
    m = re.search(r"def web_answer\([\s\S]*?\n", s)
    if not m:
        die("Cannot find def web_answer")
    # Insert just before the hard-fail condition line if present
    hard = re.search(r"\n(\s*if\s*\(not answer\)\s*or\s*\(relevance_low is True\)\s*:\n)", s)
    if not hard:
        die("Cannot find relevance_low hard-fail in web_answer")
    inject = (
        "\n    # MCP_WA_RELAX_V1: if we have a usable answer in requested language, don't hard-fail on relevance_low\n"
        "    try:\n"
        "        want_zh = True if str(language or \"\").strip().lower().startswith(\"zh\") else False\n"
        "        if (relevance_low is True) and answer:\n"
        "            if (not want_zh) or _mcp__has_zh(str(answer)):\n"
        "                relevance_low = False\n"
        "    except Exception:\n"
        "        pass\n"
    )
    s = s[:hard.start(1)] + inject + s[hard.start(1):]

# ---------------------------
# D) Language guard: zh requested => never output foreign-only text
# ---------------------------
if "MCP_LANG_GUARD_V1" not in s:
    m5 = re.search(r"(try:\n\s*answer\s*=\s*_mcp__first_sentence\(answer,\s*240\)\n\s*except Exception:\n\s*pass\n)", s, re.DOTALL)
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
print("OK: patched app.py (relevance_fix_v1_2)")
