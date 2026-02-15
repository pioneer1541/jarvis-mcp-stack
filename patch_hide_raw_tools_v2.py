import os
import time

PATH = os.environ.get("MCP_APP") or "./app.py"

TARGETS = {
    "web_search": True,
    "open_url_extract": True,
    "open_url": True,
}

def read_lines(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read().splitlines(True)

def write_lines(p, lines):
    with open(p, "w", encoding="utf-8") as f:
        f.writelines(lines)

def backup(p, lines):
    ts = time.strftime("%Y%m%d-%H%M%S")
    bak = p + ".bak." + ts
    write_lines(bak, lines)
    return bak

def patch_decorators(lines):
    out = []
    pending_mcp_tool = False
    pending_tool_line = ""
    pending_tool_idx = -1
    commented = 0

    for i, line in enumerate(lines):
        s = line.lstrip()

        if pending_mcp_tool:
            # Expect next meaningful line to be "def <name>("
            ss = s
            if ss.startswith("def "):
                # def name(
                name_part = ss[4:]
                name = name_part.split("(", 1)[0].strip()
                if name in TARGETS:
                    # comment the previously stored decorator line
                    out[pending_tool_idx] = "# " + pending_tool_line
                    commented += 1
            pending_mcp_tool = False
            pending_tool_line = ""
            pending_tool_idx = -1

        # store the decorator line if it is @mcp.tool(...)
        if s.startswith("@mcp.tool(") and (not s.startswith("#")):
            pending_mcp_tool = True
            pending_tool_line = line
            pending_tool_idx = len(out)

        out.append(line)

    return out, commented

def patch_tools_selfcheck(lines):
    # Replace the list in tools_selfcheck() return dict
    # From: "tools": ["hello", "ping", "web_search", "open_url_extract", "open_url", "web_answer"],
    # To:   "tools": ["hello", "ping", "tools_selfcheck", "web_answer"],
    old = '        "tools": ["hello", "ping", "web_search", "open_url_extract", "open_url", "web_answer"],\n'
    new = '        "tools": ["hello", "ping", "tools_selfcheck", "web_answer"],\n'
    changed = 0
    out = []
    for line in lines:
        if line == old:
            out.append(new)
            changed += 1
        else:
            out.append(line)
    return out, changed

def main():
    lines = read_lines(PATH)
    bak = backup(PATH, lines)

    lines2, n_commented = patch_decorators(lines)
    lines3, n_tools = patch_tools_selfcheck(lines2)

    write_lines(PATH, lines3)

    print("patched_path=" + PATH)
    print("backup_path=" + bak)
    print("commented_decorators=" + str(n_commented))
    print("patched_tools_selfcheck_list=" + str(n_tools))

if __name__ == "__main__":
    main()
