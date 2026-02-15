#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import os
import shutil


def _find_top_level_def_block(lines, def_name):
    """
    Return (start_idx, end_idx_exclusive) for a top-level def block.
    We assume "def <name>" starts at column 0.
    """
    start = -1
    for i, line in enumerate(lines):
        if line.startswith("def " + def_name + "(") or line.startswith("def " + def_name + " ("):
            # must be top-level
            if (len(line) - len(line.lstrip(" "))) == 0:
                start = i
                break
    if start < 0:
        return (-1, -1)

    # find end: next top-level "def " or top-level "@mcp.tool" or end of file
    end = len(lines)
    for j in range(start + 1, len(lines)):
        lj = lines[j]
        if (len(lj) - len(lj.lstrip(" "))) == 0:
            if lj.startswith("def ") or lj.startswith("@mcp.tool"):
                end = j
                break
    return (start, end)


def _find_decorator_for_route_request(lines, def_start_idx):
    """
    Find the nearest top-level decorator line(s) immediately above route_request.
    We'll replace from the first decorator @mcp.tool above it (if present),
    otherwise replace from def line itself.
    """
    i = def_start_idx - 1
    while i >= 0:
        line = lines[i]
        if line.strip() == "":
            i -= 1
            continue
        # stop if hits another top-level def or something not decorator
        if (len(line) - len(line.lstrip(" "))) == 0 and line.startswith("@"):
            # keep going upward to include consecutive decorators
            i2 = i
            while i2 - 1 >= 0 and (len(lines[i2 - 1]) - len(lines[i2 - 1].lstrip(" "))) == 0 and lines[i2 - 1].startswith("@"):
                i2 -= 1
            return i2
        break
    return def_start_idx


def main():
    app_path = os.path.join(os.getcwd(), "app.py")
    if not os.path.exists(app_path):
        raise RuntimeError("app.py not found in current directory")

    with io.open(app_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # locate route_request def block
    def_start, def_end = _find_top_level_def_block(lines, "route_request")
    if def_start < 0:
        raise RuntimeError("Cannot find top-level def route_request()")

    # include decorator
    replace_start = _find_decorator_for_route_request(lines, def_start)
    replace_end = def_end

    # Build new code block
    new_block = []
    new_block.append("@mcp.tool(description=\"(Router) Route natural language request into structured weather/calendar/holiday/state/news. Entry tool for HA. Returns plain text only.\")\n")
    new_block.append("def route_request(text: str, language: str = \"\") -> str:\n")
    new_block.append("    \"\"\"MCP tool entry: ALWAYS return plain text (final), not JSON/dict.\n")
    new_block.append("    This avoids HA-side JSON parsing / unicode escape confusion.\n")
    new_block.append("    \"\"\"\n")
    new_block.append("    rr = _route_request_obj(text=text, language=language)\n")
    new_block.append("    try:\n")
    new_block.append("        final = rr.get(\"final\") if isinstance(rr, dict) else \"\"\n")
    new_block.append("    except Exception:\n")
    new_block.append("        final = \"\"\n")
    new_block.append("    if final is None:\n")
    new_block.append("        final = \"\"\n")
    new_block.append("    return str(final)\n")
    new_block.append("\n")
    new_block.append("def _route_request_obj(text: str, language: str = \"\") -> dict:\n")

    # Now we need to take the original body of route_request and move it under _route_request_obj
    # Extract old function lines [def_start:def_end), strip the "def route_request(...)" line, reindent by +4
    old_block = lines[def_start:def_end]
    if len(old_block) < 2:
        raise RuntimeError("route_request block too small")

    # remove the first line (def ...)
    old_body = old_block[1:]

    # Ensure old body has at least one line
    # Reindent: remove 4 spaces from original body (it was indented by 4), then add 4 spaces (to fit new func)
    # Practically: keep the body as-is, but we need it to be under _route_request_obj with 4-space indent.
    # Original body already starts with 4 spaces; keep it, but we must ensure references to function signature still valid.
    # Also: original code uses 'user_text' etc, keep unchanged.
    for ln in old_body:
        # If it's a blank line, keep
        if ln.strip() == "":
            new_block.append(ln)
            continue
        # It already has indentation from old function. We need to ensure it's still indented under new def.
        # The old indentation is already correct (4+). Keep as-is.
        new_block.append(ln)

    # Replace in file
    new_lines = []
    new_lines.extend(lines[:replace_start])
    new_lines.extend(new_block)
    new_lines.extend(lines[replace_end:])

    # Backup
    bak_path = app_path + ".bak.before_route_plaintext_B10"
    if not os.path.exists(bak_path):
        shutil.copy2(app_path, bak_path)

    with io.open(app_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    print("OK: patched route_request to return plain text; backup:", bak_path)


if __name__ == "__main__":
    main()
