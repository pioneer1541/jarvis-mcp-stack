#!/usr/bin/env python3
import os
import re
import shutil
from datetime import datetime

APP = "app.py"

def _read(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()

def _write(p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)

def _backup():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = "app.py.bak.news_p3_safehelper_{0}".format(ts)
    shutil.copy2(APP, bak)
    return bak

def _find_func(text, name):
    m0 = re.search(r'^def\s+{0}\s*\('.format(re.escape(name)), text, flags=re.M)
    if not m0:
        return None
    start = m0.start()
    tail = text[m0.end():]
    m1 = re.search(r'^def\s+\w+\s*\(', tail, flags=re.M)
    end = (m0.end() + m1.start()) if m1 else len(text)
    return start, end, text[start:end]

def main():
    if not os.path.exists(APP):
        raise SystemExit("app.py not found")

    src = _read(APP)
    bak = _backup()
    changes = []

    # 1) Insert helper before news_digest tool decorator (safe, top-level)
    if "_news__voice_from_items" not in src:
        m_tool = re.search(r'(?m)^@mcp\.tool\(\s*$', src)
        # If cannot find the decorator line, fallback to inserting before def news_digest
        if not m_tool:
            m_tool = re.search(r'(?m)^def\s+news_digest\s*\(', src)
        if not m_tool:
            raise SystemExit("Cannot find insertion point near news_digest")

        helper = "\n".join([
            "",
            "def _news__voice_from_items(items: list) -> str:",
            "    \"\"\"Build TTS-friendly text (no URLs) from news items.\"\"\"",
            "    try:",
            "        out = []",
            "        for i, it in enumerate(items or [], 1):",
            "            t = (it.get(\"title\") or \"\").strip()",
            "            src = (it.get(\"source\") or \"\").strip()",
            "            pa = (it.get(\"published_at\") or \"\").strip()",
            "            sn = (it.get(\"snippet\") or \"\").strip()",
            "            meta = []",
            "            if src:",
            "                meta.append(src)",
            "            if pa:",
            "                meta.append(pa)",
            "            head = \"{0}) {1}\".format(i, t)",
            "            if meta:",
            "                head = head + \"（{0}）\".format(\" | \".join(meta))",
            "            out.append(head)",
            "            if sn:",
            "                x = sn",
            "                if len(x) > 90:",
            "                    x = x[:90].rstrip() + \"...\"",
            "                out.append(x)",
            "        return \"\\n\".join(out).strip()",
            "    except Exception:",
            "        return \"\"",
            ""
        ])
        src = src[:m_tool.start()] + helper + src[m_tool.start():]
        changes.append("add_helper__news__voice_from_items")

    # 2) Patch news_digest return dict to ensure final_voice uses helper(out_items)
    fd = _find_func(src, "news_digest")
    if not fd:
        raise SystemExit("def news_digest not found")
    s0, e0, b0 = fd

    b = b0

    # replace existing "final_voice": ... line if exists
    b2, n = re.subn(
        r'(?m)^(?P<ind>[ \t]*)"final_voice"\s*:\s*[^,\n]*\s*,\s*$',
        r'\g<ind>"final_voice": _news__voice_from_items(out_items),',
        b,
        count=1
    )
    if n:
        b = b2
        changes.append("news_digest_final_voice_replace")
    else:
        # insert after "final": "\n".join(lines),
        b2, n2 = re.subn(
            r'(?m)^(?P<ind>[ \t]*)"final"\s*:\s*"\n"\.join\(lines\)\s*,\s*$',
            r'\g<ind>"final": "\n".join(lines),\n\g<ind>"final_voice": _news__voice_from_items(out_items),',
            b,
            count=1
        )
        if n2:
            b = b2
            changes.append("news_digest_final_voice_insert")

    src = src[:s0] + b + src[e0:]

    # 3) Patch route_request: remove lim dependency and default 3
    fr = _find_func(src, "route_request")
    if fr:
        s1, e1, br = fr
        br2 = br

        # limit=lim -> inline extract
        br2, n3 = re.subn(r'limit\s*=\s*lim\b', 'limit=_news__extract_limit(user_text, 3)', br2)
        if n3:
            changes.append("route_inline_limit_extract")

        # any _news__extract_limit(user_text, 5) -> 3 (first only)
        br2, n4 = re.subn(
            r'(_news__extract_limit\(\s*user_text\s*,\s*)5(\s*\))',
            r'\g<1>3\2',
            br2,
            count=1
        )
        if n4:
            changes.append("route_default_limit_3")

        # Prefer final_voice when present
        br2, n5 = re.subn(
            r'(?m)^(?P<ind>[ \t]*)final\s*=\s*\(data\.get\("final"\)\s*or\s*""\)\s*if\s*isinstance\(data,\s*dict\)\s*else\s*""\s*$',
            r'\g<ind>final = (data.get("final_voice") or data.get("final") or "") if isinstance(data, dict) else ""',
            br2,
            count=1
        )
        if n5:
            changes.append("route_prefer_final_voice")

        src = src[:s1] + br2 + src[e1:]

    _write(APP, src)
    print("OK: patched P3 safely (helper + route inline limit).")
    print("Backup:", bak)
    print("Changes:", changes)

if __name__ == "__main__":
    main()
