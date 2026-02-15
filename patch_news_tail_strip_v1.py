#!/usr/bin/env python3
# patch_news_tail_strip_v1.py
# Purpose:
# - Add _news__strip_title_tail() to remove trailing "video/视频" tails
# - Apply it in voice formatter(s) and when assigning title_voice (post-translate)
#
# Notes:
# - No f-strings (per your rule)
# - Avoid fragile single-line anchors; use block/state scanning

import io
import os
import re
import shutil

APP = "app.py"
BAK = "app.py.bak.before_news_tail_strip_v1"

def read_text(p):
    with io.open(p, "r", encoding="utf-8") as f:
        return f.read()

def write_text(p, s):
    with io.open(p, "w", encoding="utf-8") as f:
        f.write(s)

def already_has_helper(s):
    return ("def _news__strip_title_tail(" in s)

def insert_helper_after_ug_clean_unicode(s):
    # Prefer inserting after _ug_clean_unicode() definition (stable util)
    # If not found, insert after imports (best-effort)
    helper = []
    helper.append("")
    helper.append("def _news__strip_title_tail(title: str) -> str:")
    helper.append("    \"\"\"")
    helper.append("    Remove trailing tails like:")
    helper.append("    - \" - video\" / \" – video\" / \" — video\"")
    helper.append("    - \"（视频）\" / \"【视频】\" / \"——视频\"")
    helper.append("    Keep the rest unchanged.")
    helper.append("    \"\"\"")
    helper.append("    t = (title or \"\").strip()")
    helper.append("    if not t:")
    helper.append("        return \"\"")
    helper.append("    try:")
    helper.append("        # Normalize whitespace a bit (keep punctuation)")
    helper.append("        t = re.sub(r\"\\s+\", \" \", t).strip()")
    helper.append("    except Exception:")
    helper.append("        t = (title or \"\").strip()")
    helper.append("")
    helper.append("    # English tail: - video / – video / — video / (video)")
    helper.append("    try:")
    helper.append("        t = re.sub(r\"\\s*[\\-\\u2013\\u2014\\u2212]\\s*video\\s*$\", \"\", t, flags=re.IGNORECASE).strip()")
    helper.append("        t = re.sub(r\"\\s*\\(\\s*video\\s*\\)\\s*$\", \"\", t, flags=re.IGNORECASE).strip()")
    helper.append("    except Exception:")
    helper.append("        pass")
    helper.append("")
    helper.append("    # Chinese tail: ——视频 / -视频 / （视频）/【视频】")
    helper.append("    try:")
    helper.append("        t = re.sub(r\"\\s*[\\-\\u2013\\u2014\\u2212]\\s*视频\\s*$\", \"\", t).strip()")
    helper.append("        t = re.sub(r\"\\s*（\\s*视频\\s*）\\s*$\", \"\", t).strip()")
    helper.append("        t = re.sub(r\"\\s*【\\s*视频\\s*】\\s*$\", \"\", t).strip()")
    helper.append("        t = re.sub(r\"\\s*——\\s*视频\\s*$\", \"\", t).strip()")
    helper.append("    except Exception:")
    helper.append("        pass")
    helper.append("")
    helper.append("    try:")
    helper.append("        t = re.sub(r\"\\s+\", \" \", t).strip()")
    helper.append("    except Exception:")
    helper.append("        t = (t or \"\").strip()")
    helper.append("    return t")
    helper.append("")
    helper_block = "\n".join(helper)

    m = re.search(r"\ndef _ug_clean_unicode\(text: str\) -> str:\n", s)
    if m:
        # Insert after _ug_clean_unicode function end: find next "\n\ndef " after it
        start = m.start()
        # find end of that function by searching for the next "\n\ndef " after start+1
        m2 = re.search(r"\n\ndef [a-zA-Z_]", s[m.start()+1:])
        if m2:
            insert_pos = m.start() + 1 + m2.start()
            return s[:insert_pos] + helper_block + s[insert_pos:]
        # fallback: append helper at end
        return s + "\n" + helper_block

    # fallback: after imports
    m3 = re.search(r"\nimport [^\n]+\n", s)
    if m3:
        # insert after a chunk of consecutive imports
        idx = m3.end()
        while True:
            m4 = re.match(r"(import [^\n]+\n|from [^\n]+\n)", s[idx:])
            if not m4:
                break
            idx += m4.end()
        return s[:idx] + helper_block + s[idx:]

    return s + "\n" + helper_block

def patch_formatters_and_title_voice(s):
    lines = s.splitlines(True)

    # Patch inside known voice formatter functions:
    # After: title = str(x.get("title") or "").strip()
    # Add:   title = _news__strip_title_tail(title)
    formatter_names = set([
        "_news__format_voice_miniflux",
        "_news__voice_from_items",
        "_news__format_voice",
        "_news__format_voice_v2",
    ])

    out = []
    in_def = None
    indent_def = ""
    for i in range(len(lines)):
        line = lines[i]
        # detect def
        m = re.match(r"^(\s*)def\s+([A-Za-z0-9_]+)\s*\(", line)
        if m:
            in_def = m.group(2)
            indent_def = m.group(1)
        # leave def when indentation drops (best-effort handled implicitly)

        out.append(line)

        if in_def in formatter_names:
            # title assignment patterns
            if re.search(r"\btitle\s*=\s*str\(\s*x\.get\(\"title\"\)\s*or\s*\"\"\s*\)\.strip\(\)\s*$", line.strip()):
                # keep same indentation as current line
                lead = re.match(r"^(\s*)", line).group(1)
                out.append(lead + "title = _news__strip_title_tail(title)\n")
            elif re.search(r"\btitle\s*=\s*str\(\s*it\.get\(\"title\"\)\s*or\s*\"\"\s*\)\.strip\(\)\s*$", line.strip()):
                lead = re.match(r"^(\s*)", line).group(1)
                out.append(lead + "title = _news__strip_title_tail(title)\n")

    s2 = "".join(out)

    # Patch title_voice assignment anywhere:
    # it["title_voice"] = <expr>  -> it["title_voice"] = _news__strip_title_tail(<expr>)
    # Only if not already wrapped.
    def repl_title_voice(m):
        indent = m.group(1)
        expr = m.group(2)
        if "_news__strip_title_tail" in expr:
            return m.group(0)
        return indent + "it[\"title_voice\"] = _news__strip_title_tail(" + expr + ")\n"

    s3 = re.sub(
        r"^(\s*)it\[\s*\"title_voice\"\s*\]\s*=\s*(.+?)\s*$",
        repl_title_voice,
        s2,
        flags=re.MULTILINE,
    )

    return s3

def main():
    if not os.path.exists(APP):
        raise SystemExit("Missing " + APP)

    # backup once
    if not os.path.exists(BAK):
        shutil.copy2(APP, BAK)

    src = read_text(APP)
    changed = False

    if not already_has_helper(src):
        src2 = insert_helper_after_ug_clean_unicode(src)
        if src2 != src:
            src = src2
            changed = True

    src3 = patch_formatters_and_title_voice(src)
    if src3 != src:
        src = src3
        changed = True

    if changed:
        write_text(APP, src)
        print("OK: news tail strip patch applied. backup:", BAK)
    else:
        print("OK: no changes needed (already patched).")

if __name__ == "__main__":
    main()
