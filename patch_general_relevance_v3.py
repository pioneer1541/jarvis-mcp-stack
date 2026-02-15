import sys
import re

PATH = "app.py"

def die(msg):
    sys.stderr.write(msg + "\n")
    sys.exit(1)

s = open(PATH, "r", encoding="utf-8", errors="replace").read()
orig = s

# --------- sanity checks ----------
required = [
    "def _mcp__mk_keywords(query):",
    "def _mcp__is_relevant(title, snippet, kws):",
    "def web_search(",
]
for r in required:
    if r not in s:
        die("Required block not found: " + r)

# --------- helper to extract a def block (best-effort) ----------
def extract_block(src, def_name):
    k = src.find("def " + def_name)
    if k < 0:
        return None, None, None
    nxt = src.find("\ndef ", k + 1)
    if nxt < 0:
        die("Cannot find end of def " + def_name)
    return k, nxt, src[k:nxt]

# ============================================================
# 1) Patch _mcp__mk_keywords: add ascii tokens + bigrams (generic)
# ============================================================
mk_start, mk_end, mk = extract_block(s, "_mcp__mk_keywords(query):")
if mk is None:
    die("Cannot extract _mcp__mk_keywords")

if "MCP_KW_V3" not in mk:
    # Insert inside zh branch before the 'else:' that starts ascii-only path
    # We anchor to the exact else line with toks = re.findall used in your baseline.
    needle = "\n    else:\n        toks = re.findall(r\"[A-Za-z0-9]{3,}\", q)\n"
    pos = mk.find(needle)
    if pos < 0:
        die("Cannot locate mk_keywords else-branch anchor. Please grep mk_keywords else block.")

    inject = (
        "\n        # MCP_KW_V3: also keep ASCII tokens + simple bigrams for mixed-language queries\n"
        "        ascii_tokens = re.findall(r\"[A-Za-z0-9]{2,}\", q)\n"
        "        ascii_tokens = [t.lower() for t in ascii_tokens if t]\n"
        "        # Add ascii tokens\n"
        "        for t in ascii_tokens:\n"
        "            if t not in kws:\n"
        "                kws.append(t)\n"
        "        # Add bigrams (adjacent token phrases), e.g. 'home assistant', 'voice pe'\n"
        "        if len(ascii_tokens) >= 2:\n"
        "            i = 0\n"
        "            while i + 1 < len(ascii_tokens):\n"
        "                bg = ascii_tokens[i] + \" \" + ascii_tokens[i + 1]\n"
        "                if bg not in kws:\n"
        "                    kws.append(bg)\n"
        "                i += 1\n"
        "        # Keep list short\n"
        "        kws = kws[:12]\n"
    )

    mk2 = mk[:pos] + inject + mk[pos:]
    s = s[:mk_start] + mk2 + s[mk_end:]

# ============================================================
# 2) Patch _mcp__is_relevant: require multi-keyword match when kws is long (generic)
#    - downgrade very common tokens via weak_words
# ============================================================
rel_start, rel_end, rel = extract_block(s, "_mcp__is_relevant(title, snippet, kws):")
if rel is None:
    die("Cannot extract _mcp__is_relevant")

if "MCP_REL_V3" not in rel:
    # Anchor after 'tl = t.lower()' which exists in your uploaded baseline
    anchor = "    tl = t.lower()\n"
    pos = rel.find(anchor)
    if pos < 0:
        die("Cannot find 'tl = t.lower()' inside _mcp__is_relevant. Please show that function block.")

    add = (
        anchor +
        "    # MCP_REL_V3: generic multi-keyword relevance (avoid single ambiguous token dominating)\n"
        "    try:\n"
        "        weak_words = set([\"home\", \"login\", \"官网\", \"入口\", \"download\", \"app\"])  # generic low-signal tokens\n"
        "        kws2 = []\n"
        "        for k in (kws or []):\n"
        "            kk = str(k or \"\").strip().lower()\n"
        "            if not kk:\n"
        "                continue\n"
        "            kws2.append(kk)\n"
        "        # Count distinct keyword hits (ignore weak_words as standalone)\n"
        "        hit = 0\n"
        "        seen = set()\n"
        "        for k in kws2:\n"
        "            if (k in weak_words) and (\" \" not in k):\n"
        "                continue\n"
        "            if (k in tl) and (k not in seen):\n"
        "                seen.add(k)\n"
        "                hit += 1\n"
        "        # If we have many keywords, require at least 2 hits\n"
        "        if len(kws2) >= 3:\n"
        "            if hit < 2:\n"
        "                return False\n"
        "    except Exception:\n"
        "        pass\n"
    )

    rel2 = rel.replace(anchor, add, 1)
    s = s[:rel_start] + rel2 + s[rel_end:]

# ============================================================
# 3) Patch web_search best selection: score all results, pick max; auto-expand k if low score
#    (generic, no HA special-case)
# ============================================================
ws_start = s.find("def web_search(")
if ws_start < 0:
    die("Cannot find def web_search")
ws_end = s.find("\ndef ", ws_start + 1)
if ws_end < 0:
    die("Cannot find end of web_search")
ws = s[ws_start:ws_end]

if "MCP_WS_V3" not in ws:
    # Find the existing "best = None ... break ... if best is None and top: best = top[0]" block
    sel_pat = re.compile(
        r"best = None\n\s*for it in results_out:\n\s*if _mcp__is_relevant\(it.get\(\"title\"\), it.get\(\"snippet\"\), kws\):\n\s*best = it\n\s*break\n\s*if best is None and top:\n\s*best = top\[0\]\n",
        re.DOTALL
    )
    m = sel_pat.search(ws)
    if not m:
        die("Cannot find expected best-selection block in web_search (baseline mismatch).")

    new_sel = (
        "best = None\n"
        "        # MCP_WS_V3: score-based selection (generic)\n"
        "        def _score(it):\n"
        "            try:\n"
        "                title = it.get(\"title\")\n"
        "                snippet = it.get(\"snippet\")\n"
        "                t = (str(title or \"\") + \" \" + str(snippet or \"\")).lower()\n"
        "                kws2 = [str(k or \"\").strip().lower() for k in (kws or []) if str(k or \"\").strip()]\n"
        "                weak = set([\"home\", \"login\", \"官网\", \"入口\", \"download\", \"app\"])  # generic\n"
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
        "                # small bonus for longer snippet (often higher info)\n"
        "                sl = len(str(snippet or \"\"))\n"
        "                bonus = 1 if sl >= 80 else 0\n"
        "                return (hit * 10) + (phrase_hit * 6) + bonus\n"
        "            except Exception:\n"
        "                return 0\n"
        "\n"
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

    ws2 = ws[:m.start()] + new_sel + ws[m.end():]

    # Add auto-expand: if best_score low and k small, refetch with larger k and rescore
    # Insert after 'if best is None and top: best = top[0]' line (exists in new_sel tail)
    insert_point = ws2.find("            best = top[0]\n")
    if insert_point < 0:
        die("Internal error: cannot locate insert point after new selection block")
    insert_point += len("            best = top[0]\n")

    expand = (
        "\n        # MCP_WS_V3: auto-expand k when score is low and k is small (generic)\n"
        "        try:\n"
        "            if (best_score is not None) and (best_score >= 0) and (k is not None):\n"
        "                if (int(k) <= 3) and (best_score < 12):\n"
        "                    # re-run with larger k\n"
        "                    k2 = 8\n"
        "                    data2 = {\n"
        "                        \"q\": q,\n"
        "                        \"format\": \"json\",\n"
        "                        \"categories\": cats,\n"
        "                        \"language\": lang_used,\n"
        "                        \"time_range\": time_range,\n"
        "                        \"safesearch\": 1,\n"
        "                        \"pageno\": 1,\n"
        "                    }\n"
        "                    r2 = requests.get(SEARXNG_URL.rstrip(\"/\") + \"/search\", params=data2, timeout=timeout)\n"
        "                    if r2.status_code == 200:\n"
        "                        j2 = r2.json() if \"application/json\" in str(r2.headers.get(\"Content-Type\") or \"\") else None\n"
        "                        if isinstance(j2, dict) and isinstance(j2.get(\"results\"), list):\n"
        "                            extra = []\n"
        "                            for it in j2.get(\"results\")[:k2]:\n"
        "                                title = str(it.get(\"title\") or \"\").strip()\n"
        "                                url = str(it.get(\"url\") or \"\").strip()\n"
        "                                snippet = str(it.get(\"content\") or \"\").strip()\n"
        "                                if not title or not url:\n"
        "                                    continue\n"
        "                                extra.append({\"title\": title, \"url\": url, \"snippet\": snippet})\n"
        "                            # merge\n"
        "                            for it in extra:\n"
        "                                results_out.append(it)\n"
        "                            # rescore\n"
        "                            best2 = None\n"
        "                            best_score2 = -1\n"
        "                            for it in results_out:\n"
        "                                if not _mcp__is_relevant(it.get(\"title\"), it.get(\"snippet\"), kws):\n"
        "                                    continue\n"
        "                                sc = _score(it)\n"
        "                                if sc > best_score2:\n"
        "                                    best_score2 = sc\n"
        "                                    best2 = it\n"
        "                            if best2 is not None:\n"
        "                                best = best2\n"
        "                                best_score = best_score2\n"
        "        except Exception:\n"
        "            pass\n"
    )

    ws3 = ws2[:insert_point] + expand + ws2[insert_point:]

    s = s[:ws_start] + ws3 + s[ws_end:]

# Final: ensure file changed
if s == orig:
    die("Patch produced no changes (unexpected).")

open(PATH, "w", encoding="utf-8").write(s)
print("OK: patched general relevance v3")
