#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import shutil
from datetime import datetime

APP_PATH = os.path.join(os.getcwd(), "app.py")

def _backup(path: str) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = path + ".bak.news_v2_5_repair." + ts
    shutil.copy2(path, bak)
    return bak

def _fix_decorator_def_same_line(s: str) -> str:
    # Fix: "@mcp.tool(... )def foo(...):"  -> decorator newline + def
    # Keep indentation.
    pattern = re.compile(r'(?m)^(\s*)(@mcp\.tool\([^\n]*\))def\s+')
    return pattern.sub(r'\1\2\n\1def ', s)

def _rename_duplicate_tool_names(s: str, tool_name: str) -> str:
    # If multiple @mcp.tool(name="news_digest"...), keep the first, rename the rest.
    # Works for both single/double quotes.
    pat = re.compile(r'(?m)^(\s*)@mcp\.tool\(([^)]*?)\)\s*$')
    out = []
    count = 0

    for line in s.splitlines(True):
        m = pat.match(line)
        if not m:
            out.append(line)
            continue
        inside = m.group(2)

        # Detect name="news_digest" or name='news_digest'
        name_pat = re.compile(r'(^|,)\s*name\s*=\s*([\"\'])' + re.escape(tool_name) + r'\2')
        if name_pat.search(inside):
            count += 1
            if count == 1:
                out.append(line)
            else:
                new_name = tool_name + "_legacy_" + str(count - 1)
                inside2 = name_pat.sub(r'\1 name="' + new_name + r'"', inside, count=1)
                out.append(m.group(1) + "@mcp.tool(" + inside2 + ")\n")
        else:
            out.append(line)

    return "".join(out)

def _rename_duplicate_def_names(s: str, def_name: str) -> str:
    # If multiple "def news_digest(", keep first, rename others to news_digest_legacy_fn_N
    pat = re.compile(r'(?m)^(\s*)def\s+' + re.escape(def_name) + r'\s*\(')
    matches = list(pat.finditer(s))
    if len(matches) <= 1:
        return s

    # Rename from the end to avoid offset shifts
    n = 0
    out = s
    for m in reversed(matches[1:]):
        n += 1
        legacy = def_name + "_legacy_fn_" + str(n)
        start = m.start()
        end = m.end()
        # Replace just "def news_digest(" prefix
        prefix_pat = re.compile(r'^(\s*)def\s+' + re.escape(def_name) + r'\s*\(', re.M)
        # Slice-based: replace first occurrence within this small window
        window = out[start:end]
        window2 = prefix_pat.sub(r'\1def ' + legacy + '(', window, count=1)
        out = out[:start] + window2 + out[end:]
    return out

def _force_first_news_digest_signature(s: str) -> str:
    # Ensure the FIRST def news_digest has a signature that accepts prefer_lang/user_text/**kwargs
    key = "def news_digest"
    idx = s.find(key)
    if idx < 0:
        return s

    # Find line start
    line_start = s.rfind("\n", 0, idx) + 1
    indent = ""
    m_indent = re.match(r'^(\s*)def\s+news_digest', s[line_start:idx+len(key)])
    if m_indent:
        indent = m_indent.group(1)

    # Parse until signature end ":" after matching parentheses
    i = idx
    # find first "("
    lp = s.find("(", i)
    if lp < 0:
        return s
    depth = 0
    j = lp
    while j < len(s):
        ch = s[j]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                j += 1
                break
        j += 1
    if depth != 0:
        return s

    # Skip spaces, optional return annotation "-> ...", then find ":"
    k = j
    while k < len(s) and s[k] in " \t":
        k += 1
    # allow "-> ..."
    if s.startswith("->", k):
        k2 = k + 2
        while k2 < len(s) and s[k2] != ":":
            k2 += 1
        k = k2
    # Now expect ":"
    colon = s.find(":", k)
    if colon < 0:
        return s

    sig_start = line_start
    sig_end = colon  # exclude ":"
    new_sig = (
        indent
        + 'def news_digest(category: str = "world", limit: int = 5, time_range: str = "day", '
        + 'prefer_lang: str = "zh", user_text: str = "", **kwargs) -> dict'
    )
    # Replace signature block (may be multiline) with one line
    return s[:sig_start] + new_sig + s[colon:]

def main():
    if not os.path.exists(APP_PATH):
        raise SystemExit("app.py not found in current directory: " + os.getcwd())

    with open(APP_PATH, "r", encoding="utf-8") as f:
        s = f.read()

    bak = _backup(APP_PATH)

    s2 = s
    s2 = _fix_decorator_def_same_line(s2)
    s2 = _rename_duplicate_tool_names(s2, "news_digest")
    s2 = _rename_duplicate_def_names(s2, "news_digest")
    s2 = _force_first_news_digest_signature(s2)

    if s2 == s:
        print("No changes needed.")
        print("Backup:", bak)
        return

    with open(APP_PATH, "w", encoding="utf-8") as f:
        f.write(s2)

    print("Patched OK.")
    print("Backup:", bak)

if __name__ == "__main__":
    main()
