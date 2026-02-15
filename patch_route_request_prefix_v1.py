import os
import sys
from datetime import datetime

TARGET = "app.py"
MARK = "UG_MCP_FINAL_PREFIX_V1"

def read_text(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()

def write_text(p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)

def backup(p):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = p + ".bak.route_prefix_v1." + ts
    with open(p, "rb") as src:
        with open(bak, "wb") as dst:
            dst.write(src.read())
    return bak

def main():
    if not os.path.exists(TARGET):
        print("ERROR: not found:", TARGET)
        sys.exit(1)

    src = read_text(TARGET)
    if MARK in src:
        print("OK: already patched (marker found).")
        return

    # We patch inside route_request: just before each "return <something>" at function end.
    # Safer approach: add a helper _mcp_final_text() inside route_request and wrap final returns.
    needle = "def route_request(text: str, language: str = \"\") -> str:"
    pos = src.find(needle)
    if pos < 0:
        print("ERROR: cannot find route_request signature")
        sys.exit(2)

    # Find function block start line index
    lines = src.splitlines(True)
    i_start = None
    for i, ln in enumerate(lines):
        if ln.startswith(needle):
            i_start = i
            break
    if i_start is None:
        print("ERROR: cannot locate route_request line")
        sys.exit(3)

    # Find first indented line after docstring end to insert helper
    # We'll insert right after the docstring (first blank line after triple quotes)
    i_ins = None
    in_func = False
    triple_count = 0
    for i in range(i_start, len(lines)):
        ln = lines[i]
        if i == i_start:
            in_func = True
            continue
        if in_func:
            if '"""' in ln:
                triple_count += ln.count('"""')
            if triple_count >= 2:
                # docstring ended, insert after next line
                i_ins = i + 1
                break
    if i_ins is None:
        print("ERROR: cannot find docstring end in route_request")
        sys.exit(4)

    helper = []
    helper.append("    # " + MARK + "\n")
    helper.append("    def _mcp_final_text(s: str) -> str:\n")
    helper.append("        # Strong visual anchor so HA LLM reliably uses content[0].text and ignores structuredContent\n")
    helper.append("        t = str(s or \"\").strip()\n")
    helper.append("        if not t:\n")
    helper.append("            return \"新闻检索失败或暂无结果。\"\n")
    helper.append("        return \"FINAL_TEXT_ONLY:\\n\" + t\n")
    helper.append("\n")

    # Replace "return <expr>" inside route_request with "return _mcp_final_text(<expr>)"
    out = []
    out.extend(lines[:i_ins])
    out.extend(helper)

    in_route = False
    indent_ok = False
    for i in range(i_ins, len(lines)):
        ln = lines[i]
        if i == i_start:
            in_route = True
        if in_route and i > i_start:
            # end of function when dedent to column 0 with "def " or other top-level
            if not ln.startswith(" ") and (ln.startswith("def ") or ln.startswith("@") or ln.startswith("class ")):
                in_route = False

        if in_route:
            # naive but safe: only wrap returns that already return a string expression
            stripped = ln.strip()
            if stripped.startswith("return "):
                # Avoid double-wrapping
                if "_mcp_final_text(" not in ln:
                    expr = ln.split("return", 1)[1].strip()
                    ln = "    return _mcp_final_text(" + expr + ")\n"
        out.append(ln)

    bak = backup(TARGET)
    write_text(TARGET, "".join(out))
    print("OK: patched", TARGET)
    print("Backup:", bak)

if __name__ == "__main__":
    main()
