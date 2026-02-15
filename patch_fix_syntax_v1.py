import sys

PATH = "app.py"

def die(msg):
    sys.stderr.write(msg + "\n")
    sys.exit(1)

s = open(PATH, "r", encoding="utf-8", errors="replace").read()
orig = s

# ---- Fix 1: remove the stray else-branch after 'return kws[:12]' inside _mcp__mk_keywords ----
bad_block = (
    "\n\n    else:\n"
    "        toks = re.findall(r\"[A-Za-z0-9]{3,}\", q)\n"
    "        for t in toks[:10]:\n"
    "            kws.append(t.lower())\n"
    "    return kws\n"
)

if bad_block in s:
    s = s.replace(bad_block, "\n", 1)
else:
    # More tolerant fallback: detect 'return kws[:12]' followed by an indented 'else:' within mk_keywords
    mk_start = s.find("def _mcp__mk_keywords(query):")
    if mk_start < 0:
        die("Cannot find def _mcp__mk_keywords(query):")
    mk_end = s.find("\ndef _mcp__is_relevant", mk_start)
    if mk_end < 0:
        die("Cannot find end of _mcp__mk_keywords (next def _mcp__is_relevant)")

    mk = s[mk_start:mk_end]
    marker = "return kws[:12]\n\n    else:\n"
    p = mk.find(marker)
    if p < 0:
        die("Cannot locate stray 'else' after return kws[:12] in _mcp__mk_keywords")

    # Delete from that stray else to the end of mk block (it is leftover old code)
    mk_fixed = mk[: p + len("return kws[:12]\n")] + "\n"
    s = s[:mk_start] + mk_fixed + s[mk_end:]

# ---- Fix 2: normalize indentation under 'try:' for evidence block (top = results_out...) ----
# This line in your file currently appears with too many spaces after try: and breaks indentation. :contentReference[oaicite:2]{index=2}
bad_indent = "try:\n                top = results_out[: min(3, len(results_out))]\n"
good_indent = "try:\n        top = results_out[: min(3, len(results_out))]\n"
if bad_indent in s:
    s = s.replace(bad_indent, good_indent, 1)

if s == orig:
    die("No changes made (did not find expected syntax issues).")

open(PATH, "w", encoding="utf-8").write(s)
print("OK: applied patch_fix_syntax_v1")
