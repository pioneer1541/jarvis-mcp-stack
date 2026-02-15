import sys

PATH = "app.py"

def die(msg):
    sys.stderr.write(msg + "\n")
    sys.exit(1)

s = open(PATH, "r", encoding="utf-8", errors="replace").read()
orig = s

# Anchor inside _searxng_search params dict
anchor = '        "count": int(count),\n    }\n'
if anchor not in s:
    die("Cannot find expected params dict anchor in _searxng_search")

# Avoid double patch
if '"engines"' in s[s.find("def _searxng_search("): s.find("# --- MCP_PHASEB_DEFAULT_NORUNAWAY")]:
    die("It looks like engines param is already present in _searxng_search (abort)")

inject = (
'        "count": int(count),\n'
'    }\n'
'    # Force engines to reduce low-quality sources (generic). Override via SEARXNG_ENGINES.\n'
'    eng = os.getenv("SEARXNG_ENGINES", "").strip()\n'
'    if not eng:\n'
'        eng = "google,bing,duckduckgo"\n'
'    params["engines"] = eng\n'
)

s = s.replace(anchor, inject, 1)

if s == orig:
    die("No changes made (unexpected).")

open(PATH, "w", encoding="utf-8").write(s)
print("OK: patched _searxng_search to pass engines param")
