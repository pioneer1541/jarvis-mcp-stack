import re
import sys

PATH = "app.py"

def die(msg):
    sys.stderr.write(msg + "\n")
    sys.exit(1)

s = open(PATH, "r", encoding="utf-8", errors="replace").read()

# 匹配：@mcp.tool(...) + def tools_selfcheck(): + return {...} 这个整体块
# 用非贪婪匹配，确保一次只吃一个 block
pat = re.compile(
    r"\n@mcp\.tool\([^\n]*\)\ndef tools_selfcheck\(\)\s*->\s*dict:\n(?:[^\n]*\n)*?\s*return\s*\{[\s\S]*?\n\s*\}\n",
    re.DOTALL,
)

blocks = list(pat.finditer(s))
if len(blocks) < 2:
    print("No duplicate tools_selfcheck block found (count=%d). No changes." % len(blocks))
    sys.exit(0)

# 删除第二个 block
b2 = blocks[1]
out = s[:b2.start()] + "\n" + s[b2.end():]

open(PATH, "w", encoding="utf-8").write(out)
print("OK: removed second duplicate tools_selfcheck block")
