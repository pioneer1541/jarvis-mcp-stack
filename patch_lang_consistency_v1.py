import re
import sys

PATH = "app.py"

def die(msg):
    sys.stderr.write(msg + "\n")
    sys.exit(1)

def read_text(p):
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        return f.read()

def write_text(p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)

s = read_text(PATH)
orig = s

# 1) Insert helper: _mcp__norm_accept_language (after _mcp__auto_language)
if "_mcp__norm_accept_language" not in s:
    m = re.search(r"(def _mcp__auto_language\([\s\S]*?\n\s*return lg\n)", s)
    if not m:
        die("Patch failed: cannot find _mcp__auto_language block")
    insert = """

def _mcp__norm_accept_language(lang):
    # Normalize to a safe Accept-Language header value.
    lg = str(lang or "").strip()
    if not lg:
        return ""
    lg = lg.replace("_", "-")
    if lg.lower() == "zh":
        lg = "zh-CN"
    base = lg.split("-")[0].strip()
    if not base:
        return lg
    # Prefer requested locale, then base language, then English as fallback.
    if base.lower() == "zh":
        return lg + ",zh;q=0.9,en;q=0.2"
    if base.lower() == "en":
        return lg + ",en;q=0.9"
    return lg + "," + base + ";q=0.9,en;q=0.2"
"""
    s = s[:m.end()] + insert + s[m.end():]

# 2) _searxng_search: add Accept-Language header
needle = '    headers = {"Accept": "application/json"}'
if needle in s and 'headers["Accept-Language"]' not in s:
    s = s.replace(
        needle,
        '    headers = {"Accept": "application/json"}\n'
        '    al = _mcp__norm_accept_language(language)\n'
        '    if al:\n'
        '        headers["Accept-Language"] = al'
    )

# 3) _ug_open_url_fetch signature: add accept_language param
s = s.replace(
    "def _ug_open_url_fetch(url: str, max_chars: int = 4000, timeout_sec: int = 10) -> dict:",
    "def _ug_open_url_fetch(url: str, max_chars: int = 4000, timeout_sec: int = 10, accept_language: str = \"\") -> dict:"
)

# 4) _ug_open_url_fetch headers: add Accept-Language
hdr_pat = re.compile(
    r"(headers = \{\n\s*\"User-Agent\":.*?\n\s*\"Accept\":.*?\n\s*\})",
    re.DOTALL
)
m = hdr_pat.search(s)
if not m:
    die("Patch failed: cannot find headers block in _ug_open_url_fetch")
if "Accept-Language" not in m.group(1):
    repl = m.group(1) + "\n\n    al = str(accept_language or \"\").strip()\n    if al:\n        headers[\"Accept-Language\"] = al"
    s = s[:m.start(1)] + repl + s[m.end(1):]

# 5) open_url_extract / open_url: pass accept_language through
s = s.replace(
    "def open_url_extract(url: str, max_chars: int = 4000, timeout_sec: int = 10) -> dict:",
    "def open_url_extract(url: str, max_chars: int = 4000, timeout_sec: int = 10, accept_language: str = \"\") -> dict:"
)
s = s.replace(
    "    return _ug_open_url_fetch(url=url, max_chars=max_chars, timeout_sec=timeout_sec)",
    "    return _ug_open_url_fetch(url=url, max_chars=max_chars, timeout_sec=timeout_sec, accept_language=accept_language)"
)
s = s.replace(
    "def open_url(url: str) -> dict:",
    "def open_url(url: str, accept_language: str = \"\") -> dict:"
)
s = s.replace(
    "    out = _ug_open_url_fetch(url=url, max_chars=1200, timeout_sec=10)",
    "    out = _ug_open_url_fetch(url=url, max_chars=1200, timeout_sec=10, accept_language=accept_language)"
)

# 6) web_search: prefer zh result when language starts with zh
block_pat = re.compile(
    r"best = None\n\s*for it in results_out:\n\s*if _mcp__is_relevant\(it.get\(\"title\"\), it.get\(\"snippet\"\), kws\):\n\s*best = it\n\s*break\n\s*if best is None and top:\n\s*best = top\[0\]",
    re.DOTALL
)
m = block_pat.search(s)
if not m:
    die("Patch failed: cannot find best-selection block in web_search")
new_block = (
    'best = None\n'
    '        prefer_zh = True if str(lang_used or "").strip().lower().startswith("zh") else False\n\n'
    '        for it in results_out:\n'
    '            if not _mcp__is_relevant(it.get("title"), it.get("snippet"), kws):\n'
    '                continue\n'
    '            if prefer_zh:\n'
    '                t = (it.get("title") or "") + " " + (it.get("snippet") or "")\n'
    '                if not _mcp__has_zh(t):\n'
    '                    continue\n'
    '            best = it\n'
    '            break\n\n'
    '        if best is None and prefer_zh:\n'
    '            for it in results_out:\n'
    '                t = (it.get("title") or "") + " " + (it.get("snippet") or "")\n'
    '                if _mcp__has_zh(t):\n'
    '                    best = it\n'
    '                    break\n\n'
    '        if best is None and top:\n'
    '            best = top[0]'
)
s = s[:m.start()] + new_block + s[m.end():]

# 7) web_answer: pass Accept-Language into open_url_extract
s = s.replace(
    "            ex = open_url_extract(best_url, max_chars=int(max_chars_per_source), timeout_sec=float(timeout_sec))",
    "            al = _mcp__norm_accept_language(language)\n"
    "            ex = open_url_extract(best_url, max_chars=int(max_chars_per_source), timeout_sec=float(timeout_sec), accept_language=al)"
)

# 8) web_answer: hard language lock (zh only) with fallback search
if "MCP_LANG_LOCK_V1" not in s:
    ins_pat = re.compile(
        r"(try:\n\s*answer = _mcp__first_sentence\(answer, 240\)\n\s*except Exception:\n\s*pass\n)",
        re.DOTALL
    )
    m = ins_pat.search(s)
    if not m:
        die("Patch failed: cannot find first_sentence block in web_answer")
    lock = """
# --- MCP_LANG_LOCK_V1 BEGIN ---
try:
    want_zh = True if str(language or "").strip().lower().startswith("zh") else False
    if want_zh and (not _mcp__has_zh(answer)):
        # Fallback search: nudge towards Chinese sources/snippets.
        try:
            sr2 = web_search(
                q + " 中文",
                k=int(max_sources),
                categories=str(categories or "general"),
                language="zh-CN",
                time_range=str(time_range or ""),
            )
        except Exception:
            sr2 = None

        if isinstance(sr2, dict) and sr2.get("ok"):
            sn2 = sr2.get("best_snippet") or sr2.get("answer_hint") or ""
            sn2 = _mcp__strip_snippet_meta(sn2)
            if _mcp__has_zh(sn2):
                answer = sn2

        if not _mcp__has_zh(answer):
            # Hard guarantee: do not return foreign-language text when user expects Chinese.
            answer = "我目前只搜到外文信息，暂时无法可靠地用中文概括。"
except Exception:
    pass
# --- MCP_LANG_LOCK_V1 END ---
"""
    s = s[:m.end()] + lock + s[m.end():]

if s == orig:
    die("Patch did not change app.py (unexpected).")
write_text(PATH, s)
print("OK: patched app.py")
