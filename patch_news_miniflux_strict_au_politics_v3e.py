import os
import sys
import shutil
from datetime import datetime

APP = "app.py"

def _backup_path():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return "app.py.bak.news_miniflux_v3e_strict_au_politics_" + ts

def _read_text(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()

def _write_text(p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)

def _leading_ws(line):
    i = 0
    while i < len(line) and line[i] in (" ", "\t"):
        i += 1
    return line[:i]

def main():
    if not os.path.exists(APP):
        print("ERR: app.py not found in current directory.")
        sys.exit(2)

    src = _read_text(APP)

    # Anchor: v3 end marker (you showed it exists in your grep)
    v3_end = "# NEWS_DIGEST_V3_END"
    if v3_end not in src:
        print("ERR: cannot find marker: " + v3_end)
        sys.exit(3)

    # Locate def news_digest(...)
    key_def = "def news_digest("
    p_def = src.find(key_def)
    if p_def < 0:
        print("ERR: cannot find " + key_def)
        sys.exit(4)

    p_end = src.find(v3_end, p_def)
    if p_end < 0:
        print("ERR: cannot find v3 end marker after news_digest")
        sys.exit(5)

    block = src[p_def:p_end]
    before = src[:p_def]
    after = src[p_end:]

    # 1) Insert STRICT_WHITELIST_CATS near FILTERS (preferred) or near docstring end.
    # We try to insert just before "FILTERS ="
    ins_line = 'STRICT_WHITELIST_CATS = set(["au_politics"])'
    if ins_line in block:
        print("OK: STRICT_WHITELIST_CATS already present, skipping insert.")
    else:
        p_filters = block.find("FILTERS")
        if p_filters < 0:
            print("ERR: cannot find FILTERS in news_digest block (v3).")
            sys.exit(6)

        # Find the start of the FILTERS line
        line_start = block.rfind("\n", 0, p_filters)
        if line_start < 0:
            line_start = 0
        else:
            line_start = line_start + 1

        # Determine indent of FILTERS line
        line_end = block.find("\n", line_start)
        if line_end < 0:
            line_end = len(block)
        filters_line = block[line_start:line_end]
        indent = _leading_ws(filters_line)

        insert_text = indent + ins_line + "\n"

        block = block[:line_start] + insert_text + block[line_start:]
        print("OK: inserted STRICT_WHITELIST_CATS above FILTERS.")

    # 2) Patch _pick(): force require_wl=True for strict categories
    # Find "def _pick(" inside block
    p_pick = block.find("def _pick(")
    if p_pick < 0:
        print("ERR: cannot find def _pick( in news_digest block.")
        sys.exit(7)

    # Find the line after def _pick(...)
    p_pick_line_end = block.find("\n", p_pick)
    if p_pick_line_end < 0:
        print("ERR: _pick definition line has no newline?")
        sys.exit(8)

    # Find first non-empty line after def _pick to get body indent
    p_scan = p_pick_line_end + 1
    body_indent = None
    while p_scan < len(block):
        p_nl = block.find("\n", p_scan)
        if p_nl < 0:
            p_nl = len(block)
        ln = block[p_scan:p_nl]
        if ln.strip() != "":
            body_indent = _leading_ws(ln)
            break
        p_scan = p_nl + 1

    if body_indent is None:
        print("ERR: cannot determine _pick() body indent.")
        sys.exit(9)

    guard_snip = (
        body_indent
        + "# Strict categories: never relax whitelist (keep category clean even if fewer items)\n"
        + body_indent
        + "try:\n"
        + body_indent
        + "    if key in STRICT_WHITELIST_CATS:\n"
        + body_indent
        + "        require_wl = True\n"
        + body_indent
        + "except Exception:\n"
        + body_indent
        + "    pass\n"
    )

    if "if key in STRICT_WHITELIST_CATS" in block:
        print("OK: _pick strict guard already present, skipping insert.")
    else:
        # Insert guard at the beginning of _pick body: right after the def line end
        insert_at = p_pick_line_end + 1
        block = block[:insert_at] + guard_snip + block[insert_at:]
        print("OK: inserted strict guard into _pick().")

    new_src = before + block + after

    # Backup then write
    bak = _backup_path()
    shutil.copyfile(APP, bak)
    _write_text(APP, new_src)

    print("DONE")
    print("Backup:", bak)

if __name__ == "__main__":
    main()
