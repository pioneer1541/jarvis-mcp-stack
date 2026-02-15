import os
import re
import time

PATH = os.environ.get("MCP_APP") or "./app.py"

def read_text(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()

def write_text(p, t):
    with open(p, "w", encoding="utf-8") as f:
        f.write(t)

def backup(p, t):
    ts = time.strftime("%Y%m%d-%H%M%S")
    bak = p + ".bak." + ts
    write_text(bak, t)
    return bak

def comment_tool_decorator(src, func_name):
    # Match: @mcp.tool(...) <newline> def <func_name>(
    pat = r"(^\s*@mcp\.tool\([^\n]*\)\s*\n)(\s*def\s+" + re.escape(func_name) + r"\s*\()"
    m = re.search(pat, src, flags=re.M)
    if not m:
        return src, 0
    dec = m.group(1)
    rep = "# " + dec.replace("\n", "\n# ").rstrip("# ") + "\n" + m.group(2)
    out = src[:m.start(1)] + rep + src[m.start(2)+0:]
    return out, 1

def patch_tools_list(src):
    # Replace the advertised tools list near line ~551:
    # "tools": ["hello", "ping", "web_search", "open_url_extract", "open_url", "web_answer"],
    # -> keep only hello/ping/tools/web_answer
    pat = r'("tools"\s*:\s*)\[[^\]]*\]'
    # We only want to patch the first occurrence (the registry)
    m = re.search(pat, src)
    if not m:
        return src, 0
    new_list = '["hello", "ping", "tools", "web_answer"]'
    out = src[:m.start(0)] + m.group(1) + new_list + src[m.end(0):]
    return out, 1

def main():
    src = read_text(PATH)
    if "FastMCP" not in src or "mcp-hello" not in src:
        raise SystemExit("This does not look like mcp-hello app.py: " + PATH)

    bak = backup(PATH, src)

    changed = 0
    src2, n1 = comment_tool_decorator(src, "web_search")
    changed += n1
    src3, n2 = comment_tool_decorator(src2, "open_url_extract")
    changed += n2
    src4, n3 = comment_tool_decorator(src3, "open_url")
    changed += n3

    src5, n4 = patch_tools_list(src4)
    changed += n4

    write_text(PATH, src5)

    print("patched_path=" + PATH)
    print("backup_path=" + bak)
    print("commented_decorators=" + str(n1 + n2 + n3))
    print("patched_tools_list=" + str(n4))

if __name__ == "__main__":
    main()
