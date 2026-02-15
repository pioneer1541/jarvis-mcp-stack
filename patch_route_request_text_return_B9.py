#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import os
import sys

APP = "app.py"


def _read(path):
    with io.open(path, "r", encoding="utf-8") as f:
        return f.read().splitlines(True)


def _write(path, lines):
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        f.writelines(lines)


def _find_route_tool_block(lines):
    """
    Find the top-level MCP tool:
      @mcp.tool(...)\n
      def route_request(...):
          ...
    Return (start_idx, end_idx) for the whole tool function block (including decorator).
    """
    start = -1
    for i in range(len(lines) - 1):
        if lines[i].startswith("@mcp.tool") and ("Route natural language request" in lines[i]):
            # next non-empty line should be def route_request
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j < len(lines) and lines[j].startswith("def route_request("):
                start = i
                break

    if start < 0:
        return None

    # Find end: next top-level decorator or top-level def (not indented), after current def block.
    end = len(lines)
    for k in range(start + 1, len(lines)):
        if k == start:
            continue
        if lines[k].startswith("@mcp.tool") and k > start:
            end = k
            break
        if lines[k].startswith("def ") and k > start:
            # if another top-level def begins, also end here
            end = k
            break

    return (start, end)


def main():
    if not os.path.exists(APP):
        raise RuntimeError("Cannot find " + APP)

    lines = _read(APP)
    loc = _find_route_tool_block(lines)
    if not loc:
        raise RuntimeError("Cannot find MCP tool route_request() block")

    s, e = loc
    block = lines[s:e]

    # Expect first line is decorator and next non-empty is def route_request...
    decorator = block[0]
    # Find def line index inside block
    def_idx = None
    for i in range(1, len(block)):
        if block[i].startswith("def route_request("):
            def_idx = i
            break
    if def_idx is None:
        raise RuntimeError("Cannot locate def route_request line inside block")

    # Original function code (without decorator), we will rename it to route_request_dict
    original_def_and_body = block[def_idx:]

    # Rename the def line: def route_request(...) -> dict:  ==> def route_request_dict(...) -> dict:
    first = original_def_and_body[0]
    original_def_and_body[0] = first.replace("def route_request(", "def route_request_dict(", 1)

    # New wrapper tool: returns plain text by default (best for HA),
    # and returns JSON dict only when ROUTE_RETURN_JSON=1
    new_block = []
    new_block.append(decorator)
    new_block.append("def route_request(text: str, language: str = None):\n")
    new_block.append("    \"\"\"MCP tool entry for HA.\n")
    new_block.append("    Default: return plain text (final) to avoid HA-side JSON parsing / escaping issues.\n")
    new_block.append("    Debug: set ROUTE_RETURN_JSON=1 to return the full structured dict.\n")
    new_block.append("    \"\"\"\n")
    new_block.append("    rr = route_request_dict(text=text, language=language)\n")
    new_block.append("    try:\n")
    new_block.append("        mode = str(os.environ.get(\"ROUTE_RETURN_JSON\") or \"\").strip().lower()\n")
    new_block.append("        if mode in (\"1\", \"true\", \"yes\", \"on\", \"json\"):\n")
    new_block.append("            return rr\n")
    new_block.append("    except Exception:\n")
    new_block.append("        pass\n")
    new_block.append("    if isinstance(rr, dict):\n")
    new_block.append("        final = rr.get(\"final\")\n")
    new_block.append("        if isinstance(final, str) and final.strip():\n")
    new_block.append("            return final\n")
    new_block.append("    return \"暂时取不到结果，请稍后再试。\"\n")
    new_block.append("\n")
    new_block.extend(original_def_and_body)

    # Replace in file
    out = lines[:s] + new_block + lines[e:]
    _write(APP, out)

    print("OK: route_request tool now returns plain text by default; added route_request_dict().")
    print("Hint: set ROUTE_RETURN_JSON=1 when you want structured dict output for debugging.")


if __name__ == "__main__":
    main()
