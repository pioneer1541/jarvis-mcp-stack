#!/usr/bin/env python3
import sys
import re

def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read().splitlines(True)

def _write(path, lines):
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)

def ensure_tuple_import(lines):
    # If Tuple is used in annotations but not imported, add a safe import.
    joined_head = "".join(lines[:600])
    uses_tuple = ("Tuple[" in joined_head) or bool(re.search(r"\bTuple\[[^\]]+\]", joined_head))
    has_tuple = bool(re.search(r"(^|\n)\s*(from\s+typing\s+import\s+.*\bTuple\b|import\s+typing\b)", joined_head))
    if uses_tuple and (not has_tuple):
        # Prefer appending to an existing 'from typing import ...' line if present and single-line.
        for i, ln in enumerate(lines[:600]):
            if ln.lstrip().startswith("from typing import") and ("\n" in ln):
                if "Tuple" not in ln:
                    # Single-line import: append ", Tuple"
                    if ln.rstrip().endswith(")"):
                        break
                    lines[i] = ln.rstrip("\n") + ", Tuple\n"
                    return True
                return False
        # Otherwise insert a standalone import after the last import line in the header block.
        insert_at = 0
        for i, ln in enumerate(lines[:600]):
            if ln.startswith("import ") or ln.startswith("from "):
                insert_at = i + 1
            elif insert_at > 0:
                break
        lines.insert(insert_at, "from typing import Tuple\n")
        return True
    return False

def add_cache_control_in_brave_headers(lines):
    # Find the Brave backend block by its docstring marker, then locate headers = { ... } and inject Cache-Control.
    doc_idx = None
    for i, ln in enumerate(lines):
        if "Brave Search API backend" in ln:
            doc_idx = i
            break
    if doc_idx is None:
        return False, "marker_not_found"

    hdr_start = None
    for i in range(doc_idx, min(len(lines), doc_idx + 500)):
        if re.search(r"^\s*headers\s*=\s*\{", lines[i]):
            hdr_start = i
            break
    if hdr_start is None:
        return False, "headers_block_not_found"

    indent = re.match(r"^(\s*)", lines[hdr_start]).group(1)
    # Find end of dict by brace depth
    depth = 0
    hdr_end = None
    for j in range(hdr_start, len(lines)):
        depth += lines[j].count("{")
        depth -= lines[j].count("}")
        if depth == 0 and j > hdr_start:
            hdr_end = j
            break
    if hdr_end is None:
        return False, "headers_block_unclosed"

    block = "".join(lines[hdr_start:hdr_end+1])
    if "Cache-Control" in block or "cache-control" in block.lower():
        # normalize value to no-cache
        new_block = re.sub(r'(["\']Cache-Control["\']\s*:\s*["\'])([^"\']*)(["\'])', r"\1no-cache\3", block)
        if new_block != block:
            lines[hdr_start:hdr_end+1] = new_block.splitlines(True)
            return True, "cache_control_normalized"
        return False, "cache_control_already_ok"

    # Insert after Accept if possible; otherwise right after headers = {
    insert_at = hdr_start + 1
    for j in range(hdr_start + 1, hdr_end):
        if re.search(r'["\']Accept["\']\s*:', lines[j]):
            insert_at = j + 1
            break

    ins = indent + "    " + '"Cache-Control": "no-cache",' + "\n"
    lines.insert(insert_at, ins)
    return True, "cache_control_inserted"

def fix_route_web_lang(lines):
    # In route_request -> web search branch, replace the hard zh/en selection with auto-language based on stripped query q.
    # Look for the comment line then patch the next lang= line.
    changed = False
    for i in range(len(lines)):
        if "Semi-structured retrieval: web search" in lines[i]:
            # search within next 40 lines for `lang = ...prefer_lang...`
            for j in range(i, min(len(lines), i + 60)):
                if re.search(r"^\s*lang\s*=\s*\"zh-CN\"\s*if\s*str\(prefer_lang", lines[j]):
                    indent = re.match(r"^(\s*)", lines[j]).group(1)
                    lines[j] = indent + "lang = _mcp__auto_language(q, prefer_lang or \"\")\n"
                    changed = True
                    break
            break
    return changed

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "app.py"
    lines = _read(path)

    if not any("api.search.brave.com" in ln for ln in lines) and not any("BRAVE_SEARCH_TOKEN" in ln for ln in lines):
        print("ERROR: This app.py does not look like the Brave-search version (no Brave markers found).")
        sys.exit(2)

    changed_any = False

    if ensure_tuple_import(lines):
        changed_any = True
        print("OK: ensured Tuple import")

    ok, msg = add_cache_control_in_brave_headers(lines)
    if ok:
        changed_any = True
        print("OK: brave headers patch -> " + msg)
    else:
        print("NOTE: brave headers patch skipped -> " + msg)

    if fix_route_web_lang(lines):
        changed_any = True
        print("OK: route_request web lang now uses _mcp__auto_language(q, prefer_lang)")

    if not changed_any:
        print("NOTE: no changes applied (already patched?)")
        return

    _write(path, lines)
    print("OK patched: " + path)

if __name__ == "__main__":
    main()
