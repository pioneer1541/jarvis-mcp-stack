import re
import sys

PATH = "app.py"

def die(msg):
    sys.stderr.write(msg + "\n")
    sys.exit(1)

s = open(PATH, "r", encoding="utf-8", errors="replace").read()
orig = s

# -----------------------------
# 0) 必要锚点（与你上传的这份 app.py 对齐）
# -----------------------------
need = [
    "def _mcp__mk_keywords(query):",
    "def _mcp__is_relevant(title, snippet, kws):",
    "def web_search(",
    "best_title = (best or {}).get(\"title\")",
    "\"best_title\": best_title",   # evidence 里已有
    "\"best_url\": (evidence.get(\"best_url\")",
]
for n in need:
    if n not in s:
        die("Required anchor not found (baseline mismatch): " + n)

# ============================================================
# 1) Replace _mcp__mk_keywords with generic: zh + ascii tokens + bigrams
# ============================================================
mk_pat = re.compile(r"def _mcp__mk_keywords\(query\):[\s\S]*?\n\n", re.DOTALL)
mk_m = mk_pat.search(s)
if not mk_m:
    die("Cannot locate _mcp__mk_keywords block")

mk_new = (
"def _mcp__mk_keywords(query):\n"
"    q = str(query or \"\").strip()\n"
"    if not q:\n"
"        return []\n"
"    kws = []\n"
"    # 1) Chinese fragments (existing behavior)\n"
"    if _mcp__has_zh(q):\n"
"        stop = set([\"怎么\",\"回事\",\"什么\",\"如何\",\"怎么样\",\"最新\",\"情况\",\"新闻\",\"事件\",\"问题\"])\n"
"        qq = re.sub(r\"[^\\u4e00-\\u9fff]\", \"\", q)\n"
"        seen = set()\n"
"        for L in [4,3,2]:\n"
"            for i in range(0, max(0, len(qq) - L + 1)):\n"
"                sub = qq[i:i+L]\n"
"                if (not sub) or (sub in stop):\n"
"                    continue\n"
"                if sub in seen:\n"
"                    continue\n"
"                seen.add(sub)\n"
"                kws.append(sub)\n"
"                if len(kws) >= 8:\n"
"                    break\n"
"            if len(kws) >= 8:\n"
"                break\n"
"\n"
"    # 2) ASCII tokens + adjacent bigrams (generic, no special-case)\n"
"    toks = re.findall(r\"[A-Za-z0-9]{2,}\", q)\n"
"    toks = [t.lower() for t in toks if t]\n"
"    for t in toks:\n"
"        if t not in kws:\n"
"            kws.append(t)\n"
"    if len(toks) >= 2:\n"
"        i = 0\n"
"        while i + 1 < len(toks):\n"
"            bg = toks[i] + \" \" + toks[i+1]\n"
"            if bg not in kws:\n"
"                kws.append(bg)\n"
"            i += 1\n"
"\n"
"    return kws[:12]\n"
"\n"
)

s = s[:mk_m.start()] + mk_new + s[mk_m.end():]

# ============================================================
# 2) Replace _mcp__is_relevant with generic multi-hit + weak-word downweight
# ============================================================
rel_pat = re.compile(r"def _mcp__is_relevant\(title, snippet, kws\):[\s\S]*?\n\n", re.DOTALL)
rel_m = rel_pat.search(s)
if not rel_m:
    die("Cannot locate _mcp__is_relevant block")

rel_new = (
"def _mcp__is_relevant(title, snippet, kws):\n"
"    t = (str(title or \"\") + \" \" + str(snippet or \"\")).strip()\n"
"    if not t:\n"
"        return False\n"
"    tl = t.lower()\n"
"\n"
"    # Generic weak/low-signal tokens (not domain-specific)\n"
"    weak = set([\"home\", \"app\", \"login\", \"download\", \"官网\", \"入口\", \"windows\", \"电脑\", \"键盘\"])\n"
"\n"
"    kws2 = []\n"
"    for k in (kws or []):\n"
"        kk = str(k or \"\").strip()\n"
"        if kk:\n"
"            kws2.append(kk)\n"
"    if not kws2:\n"
"        return True\n"
"\n"
"    hits = 0\n"
"    seen = set()\n"
"    for kk in kws2:\n"
"        if _mcp__has_zh(kk):\n"
"            if (kk in t) and (kk not in seen):\n"
"                seen.add(kk)\n"
"                hits += 1\n"
"        else:\n"
"            kl = kk.lower()\n"
"            # ignore standalone weak words (keep phrases like 'home assistant' because it has space)\n"
"            if (kl in weak) and (\" \" not in kl):\n"
"                continue\n"
"            if (kl in tl) and (kl not in seen):\n"
"                seen.add(kl)\n"
"                hits += 1\n"
"\n"
"    # Generic rule: if we have 3+ keywords, require 2+ distinct hits\n"
"    if len(kws2) >= 3:\n"
"        return True if hits >= 2 else False\n"
"    return True if hits >= 1 else False\n"
"\n"
)

s = s[:rel_m.start()] + rel_new + s[rel_m.end():]

# ============================================================
# 3) Patch web_search best selection: score-based + auto-expand when low score (generic)
#    Replace the block from: best=None ... best_snippet=...
# ============================================================
ws_pat = re.compile(
    r"top = results_out\[: min\(3, len\(results_out\)\)\]\n"
    r"\s*best = None\n"
    r"\s*prefer_zh = True if str\(lang_used or \"\"\)\.strip\(\)\.lower\(\)\.startswith\(\"zh\"\) else False\n"
    r"[\s\S]*?"
    r"best_snippet = \(best or \{\}\)\.get\(\"snippet\"\) or \"\"\n",
    re.DOTALL
)
ws_m = ws_pat.search(s)
if not ws_m:
    die("Cannot locate web_search best-selection block for replacement")

ws_new = (
"        top = results_out[: min(3, len(results_out))]\n"
"        prefer_zh = True if str(lang_used or \"\").strip().lower().startswith(\"zh\") else False\n"
"\n"
"        # MCP_WS_V6: score-based selection (generic)\n"
"        def _score(it):\n"
"            try:\n"
"                title = it.get(\"title\")\n"
"                snippet = it.get(\"snippet\")\n"
"                txt = (str(title or \"\") + \" \" + str(snippet or \"\")).lower()\n"
"                kws2 = [str(k or \"\").strip().lower() for k in (kws or []) if str(k or \"\").strip()]\n"
"                weak = set([\"home\", \"app\", \"login\", \"download\", \"官网\", \"入口\", \"windows\", \"电脑\", \"键盘\"])\n"
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
"        # Generic auto-expand: if k small and score low, fetch more results once and re-score\n"
"        try:\n"
"            if (best_score < 12) and (kk <= 3):\n"
"                kk2 = 8\n"
"                data2 = _searxng_search(\n"
"                    base_url=base_url,\n"
"                    query=q,\n"
"                    categories=cat_used,\n"
"                    language=lang_used,\n"
"                    count=int(kk2),\n"
"                    time_range=tr,\n"
"                )\n"
"                r2 = data2.get(\"results\") if isinstance(data2, dict) else None\n"
"                if isinstance(r2, list):\n"
"                    seen_url = set([str(it.get(\"url\") or \"\") for it in results_out])\n"
"                    for it2 in r2:\n"
"                        title2 = str(it2.get(\"title\") or \"\").strip()\n"
"                        url2 = str(it2.get(\"url\") or \"\").strip()\n"
"                        sn2 = str(it2.get(\"content\") or \"\").strip()\n"
"                        if (not title2) or (not url2):\n"
"                            continue\n"
"                        if url2 in seen_url:\n"
"                            continue\n"
"                        seen_url.add(url2)\n"
"                        results_out.append({\"title\": title2, \"url\": url2, \"snippet\": sn2})\n"
"                    # re-score\n"
"                    best = None\n"
"                    best_score = -1\n"
"                    for it in results_out:\n"
"                        if not _mcp__is_relevant(it.get(\"title\"), it.get(\"snippet\"), kws):\n"
"                            continue\n"
"                        sc = _score(it)\n"
"                        if sc > best_score:\n"
"                            best_score = sc\n"
"                            best = it\n"
"        except Exception:\n"
"            pass\n"
"\n"
"        if best is None and top:\n"
"            best = top[0]\n"
"\n"
"        best_url = (best or {}).get(\"url\")\n"
"        best_title = (best or {}).get(\"title\")\n"
"        best_snippet = (best or {}).get(\"snippet\") or \"\"\n"
)

s = s[:ws_m.start()] + ws_new + s[ws_m.end():]

# ============================================================
# 4) web_search return: add best_title field (currently missing)
# ============================================================
ret_anchor = "\"best_url\": (evidence.get(\"best_url\") if isinstance(evidence, dict) else None),"
if ret_anchor not in s:
    die("Cannot locate web_search return best_url line")
if "\"best_title\":" not in s[s.find("def web_search("):s.find("def web_answer(")]:
    s = s.replace(
        ret_anchor,
        ret_anchor + "\n        \"best_title\": (evidence.get(\"best_title\") if isinstance(evidence, dict) else None),",
        1
    )

if s == orig:
    die("Patch produced no changes (unexpected).")

open(PATH, "w", encoding="utf-8").write(s)
print("OK: applied patch_general_relevance_v6")
