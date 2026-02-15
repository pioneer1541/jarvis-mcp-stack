import re
import sys

PATH = "app.py"

def die(msg):
    sys.stderr.write(msg + "\n")
    sys.exit(1)

s = open(PATH, "r", encoding="utf-8", errors="replace").read()

# 找到所有 "@mcp.tool(...)\ndef tools_selfcheck(" 的位置
pat = re.compile(r"@mcp\.tool\([\s\S]*?\)\n(def tools_selfcheck\s*\()", re.DOTALL)
ms = list(pat.finditer(s))
if len(ms) <= 1:
    print("No duplicate tools_selfcheck found (count=%d). No changes made." % len(ms))
    sys.exit(0)

# 保留最后一个，其它全部“取消注册 + 改名”
# 做法：把对应 decorator 那行前加 '# '，并把 def tools_selfcheck( 改为 def _tools_selfcheck_oldN(
out = s
offset = 0
for idx, m in enumerate(ms[:-1], 1):
    start = m.start() + offset
    # decorator 行起点
    deco_ls = out.rfind("\n", 0, start) + 1
    if not out[deco_ls:deco_ls+2] == "# ":
        out = out[:deco_ls] + "# " + out[deco_ls:]
        offset += 2

    # rename def
    def_pos = m.start(1) + offset
    out = out[:def_pos] + "def _tools_selfcheck_old%d(" % idx + out[m.end(1) + offset:]
    offset += (len("def _tools_selfcheck_old%d(" % idx) - len("def tools_selfcheck("))

open(PATH, "w", encoding="utf-8").write(out)
print("OK: deduped tools_selfcheck (kept last, renamed %d old ones)" % (len(ms)-1))
