import re
import sys

PATH = "app.py"

def die(msg):
    sys.stderr.write(msg + "\n")
    sys.exit(1)

s = open(PATH, "r", encoding="utf-8", errors="replace").read()
orig = s

# --------------------------------------------------------------------
# A) Fix _mcp__mk_keywords(): for zh query, keep BOTH zh tokens and ascii tokens
# --------------------------------------------------------------------
mk_pat = re.compile(r"def _mcp__mk_keywords\([\s\S]*?\n\s*return kws\n", re.DOTALL)
m = mk_pat.search(s)
if not m:
    die("Cannot find _mcp__mk_keywords()")

mk_block = m.group(0)

# We patch by inserting ascii token extraction into the zh branch.
# Look for the zh branch "if _mcp__has_zh(q):" and where kws is assigned.
if "MCP_KW_V1" not in mk_block:
    # Insert after zh kws calculation: add ascii tokens and whitelist key terms.
    # We'll do a conservative injection: find the line 'kws = ...' inside zh branch.
    zh_kws_line = re.search(r"if _mcp__has_zh\(q\):[\s\S]*?\n(\s*kws\s*=\s*\[[^\n]*\]\s*)\n", mk_block)
    if not zh_kws_line:
        die("Cannot locate zh kws assignment inside _mcp__mk_keywords")
    inject = zh_kws_line.group(1) + "\n" + (
        "        # MCP_KW_V1: also keep ASCII tokens (e.g. Home Assistant Voice PE)\n"
        "        ascii_tokens = re.findall(r\"[A-Za-z0-9]+\", q)\n"
        "        ascii_tokens = [t.lower() for t in ascii_tokens if len(t) >= 3]\n"
        "        # Prefer domain terms\n"
        "        prefer = [\"home\", \"assistant\", \"voice\", \"assist\", \"ha\", \"mcp\", \"voicepe\", \"pe\"]\n"
        "        for t in prefer:\n"
        "            if t not in ascii_tokens:\n"
        "                continue\n"
        "            kws.append(t)\n"
        "        for t in ascii_tokens:\n"
        "            if t not in kws:\n"
        "                kws.append(t)\n"
        "        # keep list short\n"
        "        kws = kws[:10]\n"
    )
    mk_block2 = mk_block.replace(zh_kws_line.group(1), inject, 1)
    s = s.replace(mk_block, mk_block2, 1)

# --------------------------------------------------------------------
# B) Strengthen _mcp__is_relevant(): require at least one domain anchor for HA voice questions
# --------------------------------------------------------------------
# We'll add a small heuristic: if query contains "Home Assistant" (case-insensitive) or "HA" and/or "Voice"/"语音",
# then require candidate (title/snippet) to contain at least one of: "home assistant", "assist", "voice", "语音", "mcp"
# This reduces "home键在哪" type false positives.
rel_pat = re.compile(r"def _mcp__is_relevant\([\s\S]*?\n\s*return [^\n]*\n", re.DOTALL)
m2 = rel_pat.search(s)
if not m2:
    die("Cannot find _mcp__is_relevant()")
rel_block = m2.group(0)

if "MCP_REL_V1" not in rel_block:
    # Insert near start of function body after t = ... assembly.
    # Find first occurrence of building t string.
    ins = re.search(r"(t\s*=\s*\(.*?\)\s*\+\s*\" \".*?\n)", rel_block, re.DOTALL)
    if not ins:
        die("Cannot locate text assembly inside _mcp__is_relevant")
    add = ins.group(1) + (
        "    # MCP_REL_V1: avoid false positives like 'Home键在哪' when query is about Home Assistant Voice/Assist\n"
        "    ql = str(query or \"\").lower()\n"
        "    tl = str(t or \"\").lower()\n"
        "    if (\"home assistant\" in ql) or (\" voice\" in ql) or (\"语音\" in ql) or (\"assist\" in ql) or (\"voice pe\" in ql) or (\"voicepe\" in ql):\n"
        "        anchors = [\"home assistant\", \"assist\", \"voice\", \"语音\", \"mcp\"]\n"
        "        ok_anchor = False\n"
        "        for a in anchors:\n"
        "            if a in tl:\n"
        "                ok_anchor = True\n"
        "                break\n"
        "        if not ok_anchor:\n"
        "            return False\n"
    )
    rel_block2 = rel_block.replace(ins.group(1), add, 1)
    s = s.replace(rel_block, rel_block2, 1)

# --------------------------------------------------------------------
# C) In web_answer: do not hard-fail on relevance_low if we have decent snippet/extract in correct language
# --------------------------------------------------------------------
wa_pat = re.compile(r"def web_answer\([\s\S]*?\n\s*return\s*\{[\s\S]*?\n\s*\}\n", re.DOTALL)
m3 = wa_pat.search(s)
if not m3:
    die("Cannot find web_answer() block")
wa_block = m3.group(0)

if "MCP_WA_RELAX_V1" not in wa_block:
    # Find where relevance_low is checked. We relax it:
    # If relevance_low and best_snippet exists and (want_zh => snippet has zh), then allow returning snippet instead of generic fail.
    # We'll insert just before the current 'if relevance_low:' block if exists.
    mchk = re.search(r"\n(\s*if\s+relevance_low\s*:\n[\s\S]*?\n\s*return\s*\{[\s\S]*?\n\s*\}\n)", wa_block, re.DOTALL)
    if not mchk:
        # If no block, skip
        pass
    else:
        old = mchk.group(1)
        new = (
            "    # MCP_WA_RELAX_V1: if we have a usable snippet/extract, do not always hard-fail on relevance_low\n"
            "    try:\n"
            "        want_zh = True if str(language or \"\").strip().lower().startswith(\"zh\") else False\n"
            "        if relevance_low and answer:\n"
            "            if (not want_zh) or _mcp__has_zh(answer):\n"
            "                relevance_low = False\n"
            "    except Exception:\n"
            "        pass\n\n"
        ) + old
        wa_block2 = wa_block.replace(old, new, 1)
        s = s.replace(wa_block, wa_block2, 1)

# --------------------------------------------------------------------
# D) Language hard guarantee: if want zh and answer not zh, return fixed zh sentence
# (If you already added a similar lock earlier, we won't duplicate.)
# --------------------------------------------------------------------
if "MCP_LANG_GUARD_V1" not in s:
    # Insert near end of web_answer before the final return.
    # We look for 'return {' inside web_answer and inject just before it (the last one).
    mret = list(re.finditer(r"\n\s*return\s*\{\n", s))
    if not mret:
        die("Cannot find return dict to inject lang guard")
    last = mret[-1]
    # Insert only if this return seems inside web_answer by searching backwards for 'def web_answer'
    back = s.rfind("def web_answer", 0, last.start())
    if back >= 0:
        inj = (
            "    # MCP_LANG_GUARD_V1: never output foreign language when Chinese is requested\n"
            "    try:\n"
            "        want_zh = True if str(language or \"\").strip().lower().startswith(\"zh\") else False\n"
            "        if want_zh and (answer is not None) and (not _mcp__has_zh(str(answer))):\n"
            "            answer = \"我目前只搜到外文信息，暂时无法可靠地用中文概括。\"\n"
            "    except Exception:\n"
            "        pass\n\n"
        )
        s = s[:last.start()] + "\n" + inj + s[last.start():]

if s == orig:
    die("Patch did not change app.py (unexpected).")

open(PATH, "w", encoding="utf-8").write(s)
print("OK: patched app.py (relevance_fix_v1)")
