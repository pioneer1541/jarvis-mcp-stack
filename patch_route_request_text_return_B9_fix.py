#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import os
import shutil

def _find_route_request_block(lines):
    """
    Locate:
      @mcp.tool(...)
      def route_request(...):
         ...
    Return (start_idx, end_idx, def_line_idx)
    Indices are 0-based, end_idx is exclusive.
    """
    start = None
    def_idx = None

    for i in range(0, len(lines) - 1):
        if lines[i].lstrip().startswith("@mcp.tool") and "route_request" in lines[i + 1]:
            nxt = lines[i + 1].lstrip()
            if nxt.startswith("def route_request("):
                start = i
                def_idx = i + 1
                break

    if start is None or def_idx is None:
        return None

    # find end of function: next top-level decorator or def (col 0), after def_idx
    end = None
    for j in range(def_idx + 1, len(lines)):
        l = lines[j]
        if len(l) > 0 and (not l.startswith(" ")) and (l.startswith("def ") or l.startswith("@")):
            end = j
            break
    if end is None:
        end = len(lines)

    return (start, end, def_idx)

def main():
    path = "app.py"
    if not os.path.exists(path):
        raise RuntimeError("app.py not found in current directory")

    with io.open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    blk = _find_route_request_block(lines)
    if not blk:
        raise RuntimeError("Cannot find @mcp.tool + def route_request(...) block")

    start, end, def_idx = blk

    # backup
    bak = "app.py.bak.before_route_text_B9"
    shutil.copy2(path, bak)

    # extract original block
    orig_block = lines[start:end]
    # orig_block[0] is decorator, orig_block[1] is def route_request(...)
    decorator_line = orig_block[0]
    def_line = orig_block[1]

    # rename def route_request -> def _route_request_impl
    if "def route_request(" not in def_line:
        raise RuntimeError("Unexpected route_request def line")

    impl_def_line = def_line.replace("def route_request(", "def _route_request_impl(", 1)

    # original body lines after def line
    orig_body = orig_block[2:]

    # build new wrapper + impl block
    new_block = []
    new_block.append(decorator_line)
    new_block.append("def route_request(text: str, language: str = None) -> dict:\n")
    new_block.append("    \"\"\"HA entry tool.\n")
    new_block.append("    If ROUTE_RETURN_TEXT=1, return only the final string (plain text) to reduce JSON/escape confusion in HA.\n")
    new_block.append("    \"\"\"\n")
    new_block.append("    ret = _route_request_impl(text=text, language=language)\n")
    new_block.append("    try:\n")
    new_block.append("        v = str(os.environ.get(\"ROUTE_RETURN_TEXT\") or \"0\").strip().lower()\n")
    new_block.append("        if v in (\"1\", \"true\", \"yes\", \"y\", \"on\"):\n")
    new_block.append("            if isinstance(ret, dict):\n")
    new_block.append("                return str(ret.get(\"final\") or \"\")\n")
    new_block.append("            return str(ret or \"\")\n")
    new_block.append("    except Exception:\n")
    new_block.append("        pass\n")
    new_block.append("    return ret\n")
    new_block.append("\n")
    new_block.append(impl_def_line)
    new_block.extend(orig_body)

    # Replace original block with new block
    out_lines = []
    out_lines.extend(lines[:start])
    out_lines.extend(new_block)
    out_lines.extend(lines[end:])

    with io.open(path, "w", encoding="utf-8") as f:
        f.writelines(out_lines)

    print("OK: patched route_request wrapper for text return. backup:", bak)
    print("Hint: set ROUTE_RETURN_TEXT=1 to enable plain-text tool_result.")

if __name__ == "__main__":
    main()
