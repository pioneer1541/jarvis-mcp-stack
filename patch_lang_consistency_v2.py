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

# -------------------------------------------------------------------
# 1) Remove duplicate tools_selfcheck registration noise:
#    Comment out the FIRST decorator+def tools_selfcheck, keep the later one.
# -------------------------------------------------------------------
pat = re.compile(r"@mcp\.tool\([\s\S]*?\)\n(def tools_selfcheck\s*\()", re.DOTALL)
m = pat.search(s)
if not m:
    die("Cannot find tools_selfcheck tool definition")
# Only do this once, if we haven't already
if "def _tools_selfcheck_old" not in s:
    # Comment only the first @mcp.tool(...) line (the one matched)
    # and rename def tools_selfcheck( -> def _tools_selfcheck_old(
    block_start = m.start()
    # Find the line start of the decorator
    ls = s.rfind("\n", 0, block_start) + 1
    # Replace the decorator line by prefixing '# '
    # Safer: just insert '# ' at that line start if not already commented.
    if not s[ls:ls+2] == "# ":
        s = s[:ls] + "# " + s[ls:]
    # Rename first def tools_selfcheck(
    s = s[:m.start(1)] + "def _tools_selfcheck_old(" + s[m.end(1):]

# -------------------------------------------------------------------
# 2) Add optional local translate via Ollama (LOCAL ONLY).
#    Env:
#      OLLAMA_URL  (e.g. http://192.168.1.162:11434)
#      OLLAMA_MODEL (e.g. qwen2.5:7b-instruct or whatever you have)
# -------------------------------------------------------------------
if "_mcp__ollama_generate" not in s:
    # Insert config near SEARXNG_URL if possible
    anchor = re.search(r"SEARXNG_URL\s*=\s*os\.getenv\([^\n]+\)\n", s)
    if not anchor:
        die("Cannot find SEARXNG_URL config anchor")
    insert_cfg = """
OLLAMA_URL = os.getenv("OLLAMA_URL", "").strip()
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "").strip()
"""
    s = s[:anchor.end()] + insert_cfg + s[anchor.end():]

    # Insert helper funcs after _mcp__norm_accept_language if exists, else after _mcp__auto_language
    if "def _mcp__norm_accept_language" in s:
        anchor2 = re.search(r"def _mcp__norm_accept_language\([\s\S]*?\n\)", s)
        # above search is too loose; use a safer anchor: insert after function end marker by finding next blank line after its definition block
        idx = s.find("def _mcp__norm_accept_language")
        if idx < 0:
            die("Cannot locate _mcp__norm_accept_language")
        # Find end by searching two newlines after it; fallback to after auto_language
        endpos = s.find("\n\n", idx)
        if endpos < 0:
            endpos = idx
        helper_insert_pos = endpos + 2
    else:
        idx = s.find("def _mcp__auto_language")
        if idx < 0:
            die("Cannot locate _mcp__auto_language")
        endpos = s.find("\n\n", idx)
        if endpos < 0:
            endpos = idx
        helper_insert_pos = endpos + 2

    helper = """
def _mcp__ollama_generate(prompt, timeout_sec=12):
    url = str(OLLAMA_URL or "").strip()
    model = str(OLLAMA_MODEL or "").strip()
    if (not url) or (not model):
        return ""
    try:
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 120
            }
        }
        r = requests.post(url.rstrip("/") + "/api/generate", json=payload, timeout=float(timeout_sec))
        if r.status_code != 200:
            return ""
        j = r.json()
        out = (j.get("response") or "").strip()
        return out
    except Exception:
        return ""

def _mcp__maybe_translate_to_zh_short(text):
    t = str(text or "").strip()
    if not t:
        return ""
    # Only translate when input is clearly non-Chinese to avoid damaging Chinese answers.
    if _mcp__has_zh(t):
        return t
    p = (
        "把下面内容翻译并压缩成1到2句中文。"
        "要求：不新增事实，不要链接，不要列出处，不要解释过程。\\n\\n内容：\\n"
        + t
    )
    out = _mcp__ollama_generate(p, timeout_sec=12)
    out = (out or "").strip()
    # As a safety: ensure output is Chinese; otherwise return empty.
    if out and _mcp__has_zh(out):
        return out
    return ""
"""
    s = s[:helper_insert_pos] + helper + s[helper_insert_pos:]

# -------------------------------------------------------------------
# 3) In web_answer: before MCP_LANG_LOCK_V1, try local translate when want zh
# -------------------------------------------------------------------
marker = "# --- MCP_LANG_LOCK_V1 BEGIN ---"
if marker not in s:
    die("Cannot find MCP_LANG_LOCK_V1 marker in app.py")

if "MCP_LOCAL_TRANSLATE_V1" not in s:
    inject = """
    # --- MCP_LOCAL_TRANSLATE_V1 BEGIN ---
    try:
        want_zh = True if str(language or "").strip().lower().startswith("zh") else False
        if want_zh and (not _mcp__has_zh(answer)):
            tr = _mcp__maybe_translate_to_zh_short(answer)
            if tr and _mcp__has_zh(tr):
                answer = tr
    except Exception:
        pass
    # --- MCP_LOCAL_TRANSLATE_V1 END ---

"""
    s = s.replace(marker, inject + marker, 1)

if s == orig:
    die("Patch did not change app.py (unexpected).")
write_text(PATH, s)
print("OK: patched app.py (lang consistency v2)")
