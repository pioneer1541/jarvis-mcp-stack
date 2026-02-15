import sys
import re

PATH = "app.py"

def die(msg):
    sys.stderr.write(msg + "\n")
    sys.exit(1)

s = open(PATH, "r", encoding="utf-8", errors="replace").read()
orig = s

# -----------------------------
# 0) Sanity check: required blocks must exist
# -----------------------------
required = [
    "def _mcp__mk_keywords(query):",
    "def _mcp__is_relevant(title, snippet, kws):",
    "def web_search(",
    "def web_answer(",
    "# --- MCP_LANG_LOCK_V1 BEGIN ---",
]
for r in required:
    if r not in s:
        die("Required block not found: " + r)

# -----------------------------
# 1) _mcp__mk_keywords: zh branch also keep ASCII tokens (Home Assistant Voice PE...)
# Insert before the 'else:' of that function.
# -----------------------------
if "MCP_KW_V1" not in s:
    # Extract function block (until next 'def ' after it)
    mk_start = s.find("def _mcp__mk_keywords(query):")
    mk_end = s.find("\ndef _mcp__is_relevant", mk_start)
    if mk_end < 0:
        die("Cannot locate end of _mcp__mk_keywords block")
    mk = s[mk_start:mk_end]

    # Find insertion point: the exact 'else:\n        toks = re.findall' in this file
    needle = "\n    else:\n        toks = re.findall(r\"[A-Za-z0-9]{3,}\", q)\n"
    pos = mk.find(needle)
    if pos < 0:
        die("Cannot locate mk_keywords else-branch anchor")

    inject = (
        "\n        # MCP_KW_V1: also keep ASCII tokens for mixed queries (e.g. Home Assistant Voice PE)\n"
        "        ascii_tokens = re.findall(r\"[A-Za-z0-9]{2,}\", q)\n"
        "        ascii_tokens = [t.lower() for t in ascii_tokens if t]\n"
        "        # Add strong phrase token when possible\n"
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

    mk2 = mk[:pos] + inject + mk[pos:]
    s = s[:mk_start] + mk2 + s[mk_end:]

# -----------------------------
# 2) _mcp__is_relevant: add HA-anchor guard to avoid false positives like "Home 键在哪"
# Insert after 'tl = t.lower()'
# -----------------------------
if "MCP_REL_V1" not in s:
    rel_start = s.find("def _mcp__is_relevant(title, snippet, kws):")
    rel_end = s.find("\n\n# --- MCP_PHASEB_DEFAULT_NORUNAWAY_V3 END ---", rel_start)
    if rel_end < 0:
        die("Cannot locate end of _mcp__is_relevant block")
    rel = s[rel_start:rel_end]

    anchor = "    tl = t.lower()\n"
    pos = rel.find(anchor)
    if pos < 0:
        die("Cannot locate 'tl = t.lower()' inside _mcp__is_relevant (unexpected for this baseline)")

    add = (
        anchor +
        "    # MCP_REL_V1: avoid false positives like 'Home键在哪' when keywords imply Home Assistant\n"
        "    try:\n"
        "        kwset = set([str(k or \"\").strip().lower() for k in (kws or []) if str(k or \"\").strip()])\n"
        "        implied_ha = False\n"
        "        if (\"home assistant\" in kwset) or ((\"home\" in kwset) and (\"assistant\" in kwset)) or (\"homeassistant\" in kwset) or (\"hass\" in kwset):\n"
        "            implied_ha = True\n"
        "        if implied_ha:\n"
        "            anchors = [\"home assistant\", \"homeassistant\", \"hass\", \"assistant\", \"assist\", \"voice\", \"mcp\"]\n"
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

    rel2 = rel.replace(anchor, add, 1)
    s = s[:rel_start] + rel2 + s[rel_end:]

# -----------------------------
# 3) web_search: add 'best_title' field to return dict (web_answer reads it)
# -----------------------------
if "\"best_title\"" not in s:
    # Find the exact return dict block of web_search
    ws_key = "return {\n        \"ok\": True,"
    p = s.find(ws_key)
    if p < 0:
        die("Cannot locate web_search return dict start")
    # Insert best_title near best_url/best_snippet
    # Ensure evidence has best_title already (it does in this baseline)
    if "best_title" not in s[s.find("evidence = {", p):s.find("return {", p)]:
        die("Cannot confirm evidence.best_title exists before return")

    # Add line after best_url line
    tgt = "        \"best_url\": (evidence.get(\"best_url\") if isinstance(evidence, dict) else None),\n"
    if tgt not in s:
        die("Cannot locate best_url line in web_search return dict")
    ins = tgt + "        \"best_title\": (evidence.get(\"best_title\") if isinstance(evidence, dict) else None),\n"
    s = s.replace(tgt, ins, 1)

# -----------------------------
# 4) web_answer: relax hard-fail on relevance_low when answer exists and matches requested language
# Insert just before: if (not answer) or (relevance_low is True):
# -----------------------------
if "MCP_WA_RELAX_V1" not in s:
    hard = "\n    if (not answer) or (relevance_low is True):\n"
    idx = s.find(hard)
    if idx < 0:
        die("Cannot locate web_answer hard-fail line")
    relax = (
        "\n    # MCP_WA_RELAX_V1: if we already have a usable answer in requested language, do not hard-fail on relevance_low\n"
        "    try:\n"
        "        want_zh = True if str(language or \"\").strip().lower().startswith(\"zh\") else False\n"
        "        if (relevance_low is True) and answer:\n"
        "            if (not want_zh) or _mcp__has_zh(str(answer)):\n"
        "                relevance_low = False\n"
        "    except Exception:\n"
        "        pass\n"
    )
    s = s[:idx] + relax + s[idx:]

if s == orig:
    die("Patch produced no changes (unexpected).")

open(PATH, "w", encoding="utf-8").write(s)
print("OK: patch applied: lang_consistency_and_relevance_v1")
