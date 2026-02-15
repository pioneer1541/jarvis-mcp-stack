import re

P = "app.py"
s = open(P, "r", encoding="utf-8").read()

# ---------- helper: insert _ug_open_url_fetch if missing ----------
helper = r'''
def _ug_open_url_fetch(url: str, max_chars: int = 4000, timeout_sec: int = 10) -> dict:
    """
    Fetch URL and return a short excerpt. Keep it robust: no external deps except requests.
    """
    try:
        import html as _html
        import requests as _requests

        headers = {
            "User-Agent": "mcp-tools/1.0 (+homeassistant)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        r = _requests.get(url, headers=headers, timeout=timeout_sec, allow_redirects=True)
        ct = (r.headers.get("content-type") or "").lower()
        text = r.text or ""

        # Very light HTML-to-text: remove script/style, strip tags, collapse whitespace
        if "html" in ct:
            text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\\1>", " ", text)
            text = re.sub(r"(?is)<[^>]+>", " ", text)

        text = _html.unescape(text)
        text = re.sub(r"[\\r\\n\\t]+", " ", text)
        text = re.sub(r"\\s{2,}", " ", text).strip()

        excerpt = text[:max_chars]
        return {
            "ok": True,
            "url": url,
            "status_code": int(getattr(r, "status_code", 0) or 0),
            "content_type": ct,
            "excerpt": excerpt,
        }
    except Exception as e:
        return {
            "ok": False,
            "url": url,
            "error": str(e),
        }
'''

if "_ug_open_url_fetch" not in s:
    # Put helper before any @mcp.tool blocks (safe top-level)
    m = re.search(r"(?m)^\s*@mcp\.tool\b", s)
    if m:
        s = s[:m.start()] + helper + "\n" + s[m.start():]
    else:
        # fallback: append
        s = s + "\n" + helper + "\n"

# ---------- replace open_url_extract tool implementation ----------
# We replace the whole def open_url_extract(...) block body, keeping the decorator line if exists.
pat = r"(?ms)^(\s*@mcp\.tool[^\n]*\n\s*def\s+open_url_extract\s*\([^\)]*\)\s*->\s*dict\s*:\s*\n)(.*?)(?=^\s*(?:@mcp\.tool\b|def\s+\w+\s*\(|if\s+__name__\s*==))"
m = re.search(pat, s)
if not m:
    raise SystemExit("Cannot find open_url_extract tool block to patch")

head = m.group(1)

new_body = r'''    # NOTE: must be self-contained; do not depend on open_url/open_url_extract_impl
    try:
        if not isinstance(url, str) or not url:
            return {"ok": False, "error": "url is required"}
        return _ug_open_url_fetch(url=url, max_chars=max_chars, timeout_sec=timeout_sec)
    except Exception as e:
        return {"ok": False, "error": str(e)}
'''

s2 = s[:m.start()] + head + new_body + s[m.end():]

open(P, "w", encoding="utf-8").write(s2)
print("patched open_url_extract to be self-contained")
