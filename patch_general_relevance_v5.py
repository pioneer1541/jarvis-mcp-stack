import re
import sys

PATH = "app.py"

def die(msg):
    sys.stderr.write(msg + "\n")
    sys.exit(1)

s = open(PATH, "r", encoding="utf-8", errors="replace").read()
orig = s

# -----------------------------
# 0) Sanity checks (must exist)
# -----------------------------
need = [
    "def _mcp__mk_keywords(query):",
    "# MCP_KW_V1: also keep ASCII tokens for mixed queries (e.g. Home Assistant Voice PE)",
    "def _mcp__is_relevant(title, snippet, kws):",
    "# MCP_REL_V1: avoid false positives like 'Home键在哪' when keywords imply Home Assistant",
    "def web_search(",
    "for it in results_out:",
    "best = it",
    "break",
    "best_title = (best or {}).get(\"title\")",
]
for n in need:
    if n not in s:
        die("Required anchor not found (baseline mismatch): " + n)

# ============================================================
# 1) Replace MCP_KW_V1 block with generic ASCII token + bigram (no HA prefer list)
# ============================================================
kw_pat = re.compile(
    r"\n\s*# MCP_KW_V1:.*?\n\s*ascii_tokens\s*=.*?\n\s*kws\s*=\s*kws\[:10\]\n",
    re.DOTALL
)
m = kw_pat.search(s)
if not m:
    die("Cannot locate MCP_KW_V1 block to replace in _mcp__mk_keywords")

kw_new = (
    "\n        # MCP_KW_V5: keep ASCII tokens + adjacent bigrams for mixed-language queries (generic)\n"
    "        ascii_tokens = re.findall(r\"[A-Za-z0-9]{2,}\", q)\n"
    "        ascii_tokens = [t.lower() for t in ascii_tokens if t]\n"
    "        # Add ascii tokens (drop very short/low-signal tokens later in relevance)\n"
    "        for t in ascii_tokens:\n"
    "            if t not in kws:\n"
    "                kws.append(t)\n"
    "        # Add adjacent bigrams (generic n-gram)\n"
    "        if len(ascii_tokens) >= 2:\n"
    "            i = 0\n"
    "            while i + 1 < len(ascii_tokens):\n"
    "                bg = ascii_tokens[i] + \" \" + ascii_tokens[i + 1]\n"
    "                if bg not in kws:\n"
    "                    kws.append(bg)\n"
    "                i += 1\n"
    "        kws = kws[:12]\n"
)
s = s[:m.start()] + kw_new + s[m.end():]

# ============================================================
# 2) Remove MCP_REL_V1 HA-specific block and replace relevance logic with generic multi-hit
# ============================================================
rel_pat = re.compile(
    r"\n\s*# MCP_REL_V1:.*?\n\s*except Exception:\n\s*pass\n",
    re.DOTALL
)
m2 = rel_pat.search(s)
if not m2:
    die("Cannot locate MCP_REL_V1 block to remove in _mcp__is_relevant")

s = s[:m2.start()] + "\n" + s[m2.end():]

# Replace the simple "any-hit returns True" tail with generic multi-hit logic
tail_pat = re.compile(
    r"\n\s*for k in \(kws or \[\]\):\n(?:.|\n)*?\n\s*return False\n",
    re.DOTALL
)
m3 = tail_pat.search(s, s.find("def _mcp__is_relevant"))
if not m3:
    die("Cannot locate old any-hit loop tail in _mcp__is_relevant")

tail_new = (
    "\n    # MCP_REL_V5: generic multi-keyword relevance\n"
    "    try:\n"
    "        weak_words = set([\"home\", \"app\", \"login\", \"download\", \"官网\", \"入口\"])  # generic low-signal\n"
    "        kws2 = []\n"
    "        for k in (kws or []):\n"
    "            kk = str(k or \"\").strip()\n"
    "            if kk:\n"
    "                kws2.append(kk)\n"
    "        if not kws2:\n"
    "            return True\n"
    "        hits = 0\n"
    "        seen = set()\n"
    "        for kk in kws2:\n"
    "            if _mcp__has_zh(kk):\n"
    "                if (kk in t) and (kk not in seen):\n"
    "                    seen.add(kk)\n"
    "                    hits += 1\n"
    "            else:\n"
    "                kl = kk.lower()\n"
    "                if (kl in weak_words) and (\" \" not in kl):\n"
    "                    continue\n"
    "                if (kl in tl) and (kl not in seen):\n"
    "                    seen.add(kl)\n"
    "                    hits += 1\n"
    "        # If we have >=3 keywords, require >=2 distinct hits; else require >=1\n"
    "        if len(kws2) >= 3:\n"
    "            return True if hits >= 2 else False\n"
    "        return True if hits >= 1 else False\n"
    "    except Exception:\n"
    "        # Fallback: previous behavior\n"
    "        for k in (kws or []):\n"
    "            kk = str(k or \"\").strip()\n"
    "            if not kk:\n"
    "                continue\n"
    "            if _mcp__has_zh(kk):\n"
    "                if kk in t:\n"
    "                    return True\n"
    "            else:\n"
    "                if kk.lower() in tl:\n"
    "                    return True\n"
    "        return False\n"
)

s = s[:m3.start()] + tail_new + s[m3.end():]

# ============================================================
# 3) Replace web_search best-selection block (first-hit) with score-based selection (generic)
#    NOTE: keep prefer_zh as bonus, not forced filter.
# ============================================================
old_block = (
    "        for it in results_out:\n"
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
)

if old_block not in s:
    die("Cannot find expected web_search best-selection block (baseline mismatch).")

new_block = (
    "        # MCP_WS_V5: score-based selection (generic)\n"
    "        def _score(it):\n"
    "            try:\n"
    "                title = it.get(\"title\")\n"
    "                snippet = it.get(\"snippet\")\n"
    "                txt = (str(title or \"\") + \" \" + str(snippet or \"\")).lower()\n"
    "                weak = set([\"home\", \"app\", \"login\", \"download\", \"官网\", \"入口\"])  # generic\n"
    "                kws2 = [str(k or \"\").strip().lower() for k in (kws or []) if str(k or \"\").strip()]\n"
    "                hit = 0\n"
    "                phrase_hit = 0\n"
    "                seen = set()\n"
    "                for k in kws2:\n"
    "                    if (k in weak) and (\" \" not in k):\n"
    "                        continue\n"
    "                    if (k in txt) and (k not in seen):\n"
    "                        seen.add(k)\n"
    "                        hit += 1\n"
    "                    if (\" \" in k) and (k in txt):\n"
    "                        phrase_hit += 1\n"
    "                zh_bonus = 2 if (prefer_zh and _mcp__has_zh(txt)) else 0\n"
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
)

s = s.replace(old_block, new_block, 1)

# ============================================================
# 4) web_search return: add best_title (currently not returned)
# ============================================================
ret_anchor = "        \"best_url\": (evidence.get(\"best_url\") if isinstance(evidence, dict) else None),\n"
if ret_anchor not in s:
    die("Cannot locate web_search return best_url line")
if "        \"best_title\":" not in s:
    s = s.replace(
        ret_anchor,
        ret_anchor + "        \"best_title\": (evidence.get(\"best_title\") if isinstance(evidence, dict) else None),\n",
        1
    )

if s == orig:
    die("Patch produced no changes (unexpected).")

open(PATH, "w", encoding="utf-8").write(s)
print("OK: applied patch_general_relevance_v5")
