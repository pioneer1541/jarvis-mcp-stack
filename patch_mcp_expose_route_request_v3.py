import re

APP = "app.py"

def _read(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()

def _write(p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)

def _find_def_line(lines):
    # find: def route_request(
    for i, ln in enumerate(lines):
        if re.match(r"^\s*def\s+route_request\s*\(", ln):
            return i
    return None

def _prev_code_line_index(lines, i):
    j = i - 1
    while j >= 0:
        t = lines[j].strip()
        if t == "":
            j -= 1
            continue
        return j
    return None

def main():
    src = _read(APP)
    lines = src.splitlines(True)

    idx = _find_def_line(lines)
    if idx is None:
        raise RuntimeError("Cannot find: def route_request(")

    # Determine indent
    def_line = lines[idx]
    indent = def_line[:len(def_line) - len(def_line.lstrip(" "))]

    # Check if already decorated
    prev_i = _prev_code_line_index(lines, idx)
    already = False
    if prev_i is not None:
        prev = lines[prev_i].lstrip()
        if prev.startswith("@mcp.tool"):
            already = True

    if already:
        print("OK: route_request already has @mcp.tool decorator. No change.")
        return

    # Insert decorator immediately above def line
    deco = indent + '@mcp.tool(description="(Router) Route natural language request into structured weather/calendar/holiday/state. Entry tool for HA.")\n'
    lines.insert(idx, deco)

    _write(APP, "".join(lines))
    print("OK: inserted @mcp.tool for route_request")

if __name__ == "__main__":
    main()
