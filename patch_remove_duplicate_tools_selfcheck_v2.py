import sys

PATH = "app.py"

def die(msg):
    sys.stderr.write(msg + "\n")
    sys.exit(1)

lines = open(PATH, "r", encoding="utf-8", errors="replace").read().splitlines(True)

# 找到所有 "def tools_selfcheck" 的位置
def_idx = [i for i,l in enumerate(lines) if l.lstrip().startswith("def tools_selfcheck(")]
if len(def_idx) <= 1:
    print("No duplicate def tools_selfcheck found (count=%d). No changes." % len(def_idx))
    sys.exit(0)

# 我们删除第二个及以后出现的 tools_selfcheck（含其上方紧邻的 decorator 行）
to_remove = []
for k in range(1, len(def_idx)):
    i = def_idx[k]

    # 往上找最近的 @mcp.tool(...) 装饰器（最多往上 12 行，跨过空行/注释）
    start = i
    for j in range(1, 13):
        up = i - j
        if up < 0:
            break
        s = lines[up].lstrip()
        if s.startswith("@mcp.tool"):
            start = up
            break
        # 遇到其他 def（不是 tools_selfcheck）就停止回溯，避免误删
        if s.startswith("def ") and ("tools_selfcheck" not in s):
            break

    # 往下删完整函数体：直到遇到非空且缩进 < 4 的下一段顶层代码（或文件末尾）
    end = i + 1
    while end < len(lines):
        ln = lines[end]
        if ln.strip() == "":
            end += 1
            continue
        # 顶层行：不以 4 空格开头、也不是续行缩进（保守）
        if not ln.startswith("    ") and not ln.startswith("\t"):
            break
        end += 1

    to_remove.append((start, end))

# 合并删除区间（从后往前删避免索引变化）
for start, end in sorted(to_remove, key=lambda x: x[0], reverse=True):
    del lines[start:end]

open(PATH, "w", encoding="utf-8").write("".join(lines))
print("OK: removed %d duplicate tools_selfcheck block(s)" % (len(to_remove)))
