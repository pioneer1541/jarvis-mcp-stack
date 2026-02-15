#!/usr/bin/env python3
import re
import datetime
from pathlib import Path

def _now_tag():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

def _insert_marker(text: str) -> str:
    marker = "MCP_EXPOSE_ONLY_ROUTE_REQUEST_V1"
    if marker in text:
        return text
    target = 'mcp = FastMCP("mcp-hello", transport_security=transport_security)\n'
    if target not in text:
        return text
    note = (
        target
        + "# {0}: Only expose route_request to Home Assistant to prevent accidental tool selection.\n"
        + "# Other functions remain callable internally by route_request.\n"
    ).format(marker)
    return text.replace(target, note, 1)

def patch_app_py(path: Path) -> None:
    src = path.read_text(encoding="utf-8")
    lines = src.splitlines(True)

    out = []
    i = 0
    while i < len(lines):
        line = lines[i]

        # 1) Handle multi-line decorator blocks: @mcp.tool( ... )
        # We comment out the whole block. route_request uses single-line decorator, so safe.
        if re.match(r"^\s*@mcp\.tool\(\s*$", line):
            if not line.lstrip().startswith("#"):
                out.append("# " + line)
            else:
                out.append(line)
            i += 1
            while i < len(lines):
                l2 = lines[i]
                if not l2.lstrip().startswith("#"):
                    out.append("# " + l2)
                else:
                    out.append(l2)
                if re.search(r"\)\s*$", l2):
                    i += 1
                    break
                i += 1
            continue

        # 2) Single-line @mcp.tool(...) decorators:
        # Keep only the one immediately decorating def route_request(...)
        if re.match(r"^\s*@mcp\.tool\b", line):
            j = i + 1
            def_name = None
            while j < len(lines):
                lj = lines[j]
                if lj.strip() == "" or lj.lstrip().startswith("#"):
                    j += 1
                    continue
                m = re.match(r"^\s*def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", lj)
                if m:
                    def_name = m.group(1)
                break

            if def_name == "route_request":
                out.append(line)
            else:
                if not line.lstrip().startswith("#"):
                    out.append("# " + line)
                else:
                    out.append(line)
            i += 1
            continue

        out.append(line)
        i += 1

    new_text = "".join(out)
    new_text = _insert_marker(new_text)

    # 3) Backup & write back
    bak = path.with_name("app.py.bak.only_route_request_" + _now_tag())
    bak.write_text(src, encoding="utf-8")
    path.write_text(new_text, encoding="utf-8")

    # 4) Quick sanity print
    tool_count = 0
    for l in new_text.splitlines():
        if l.strip().startswith("@mcp.tool"):
            tool_count += 1
    print("Patched OK. Remaining @mcp.tool decorators =", tool_count)
    print("Backup written:", bak.name)

if __name__ == "__main__":
    p = Path("app.py")
    if not p.exists():
        raise SystemExit("ERROR: app.py not found in current directory.")
    patch_app_py(p)
