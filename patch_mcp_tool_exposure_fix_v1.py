import io
import os
import re
import sys

TARGET = "app.py"

def main():
    path = TARGET
    if not os.path.exists(path):
        raise RuntimeError("Cannot find " + path)

    with io.open(path, "r", encoding="utf-8") as f:
        src = f.read()

    # 1) 找出所有 mcp = FastMCP("mcp-hello" 的位置
    pat = r'^[ \t]*mcp[ \t]*=[ \t]*FastMCP\([ \t]*["\']mcp-hello["\']'
    matches = list(re.finditer(pat, src, flags=re.M))
    if len(matches) <= 1:
        print("OK: only one mcp = FastMCP('mcp-hello') found. No change.")
        return

    # 2) 把第 2 个及之后的 mcp = FastMCP(...) 改名，避免覆盖全局 mcp
    #    只替换行首的 `mcp = FastMCP(` -> `_mcp_duplicate = FastMCP(`
    lines = src.splitlines(True)
    mcp_line_idx = []
    for i, line in enumerate(lines):
        if re.match(pat, line):
            mcp_line_idx.append(i)

    # keep the first occurrence as the "real" mcp
    for j in range(1, len(mcp_line_idx)):
        i = mcp_line_idx[j]
        line = lines[i]
        # insert a comment above for clarity
        comment = "# --- DUPLICATE_MCP_INSTANCE_DISABLED_V1 (do not overwrite global mcp) ---\n"
        if i > 0 and "DUPLICATE_MCP_INSTANCE_DISABLED_V1" in lines[i-1]:
            comment = ""
        # rename only the left-hand symbol
        line2 = re.sub(r'^[ \t]*mcp[ \t]*=', ' _mcp_duplicate =', line, count=1)
        # preserve indentation: remove leading extra space from replacement if original starts with no indent
        if re.match(r'^mcp[ \t]*=', line):
            line2 = re.sub(r'^[ \t]*_mcp_duplicate', '_mcp_duplicate', line2)
        lines[i] = line2
        if comment:
            lines.insert(i, comment)
            # shift subsequent indices by 1
            for k in range(j + 1, len(mcp_line_idx)):
                mcp_line_idx[k] += 1

    out = "".join(lines)

    if out == src:
        print("No change after processing. Abort.")
        return

    bak = path + ".bak.mcp_tools_fix_v1"
    with io.open(bak, "w", encoding="utf-8") as f:
        f.write(src)

    with io.open(path, "w", encoding="utf-8") as f:
        f.write(out)

    print("Patched OK. Backup written to " + bak)
    print("Now run: python3 -m py_compile app.py")

if __name__ == "__main__":
    main()
