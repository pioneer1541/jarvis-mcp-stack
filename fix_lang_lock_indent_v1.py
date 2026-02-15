import sys

PATH = "app.py"
BEGIN = "# --- MCP_LANG_LOCK_V1 BEGIN ---"
END = "# --- MCP_LANG_LOCK_V1 END ---"

with open(PATH, "r", encoding="utf-8", errors="replace") as f:
    lines = f.readlines()

b = None
e = None
for i, ln in enumerate(lines):
    if BEGIN in ln:
        b = i
    if END in ln:
        e = i
        break

if b is None or e is None or e <= b:
    sys.stderr.write("Cannot find MCP_LANG_LOCK_V1 block markers. No changes made.\n")
    sys.exit(2)

# If BEGIN line is already indented, do nothing.
if lines[b].startswith("    "):
    print("MCP_LANG_LOCK_V1 already indented. No changes made.")
    sys.exit(0)

# Indent the whole block by 4 spaces
for j in range(b, e + 1):
    lines[j] = "    " + lines[j]

with open(PATH, "w", encoding="utf-8") as f:
    f.writelines(lines)

print("OK: indented MCP_LANG_LOCK_V1 block by 4 spaces")
