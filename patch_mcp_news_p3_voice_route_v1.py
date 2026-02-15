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
    bak = "app.py.bak.news_p3_voice_route_{0}".format(ts)
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

def patch_news_digest(block):
    out = block
    changed = []

    # 1) Add robust fallback builder right after: final_voice = "\n".join(voice_lines)
    # We rebuild from out_items if final_voice is empty.
    pat = r'(?m)^(?P<ind>[ \t]*)final_voice\s*=\s*"\\n"\.join\(voice_lines\)\s*$'
    m = re.search(pat, out)
    if m and ("__VOICE_FALLBACK_FROM_ITEMS__" not in out):
        ind = m.group("ind")
        insert = "\n".join([
            ind + "# __VOICE_FALLBACK_FROM_ITEMS__",
            ind + "if not (final_voice or \"\").strip():",
            ind + "    try:",
            ind + "        _vv = []",
            ind + "        for _i, _it in enumerate(out_items, 1):",
            ind + "            _t = (_it.get(\"title\") or \"\").strip()",
            ind + "            _src = (_it.get(\"source\") or \"\").strip()",
            ind + "            _pa = (_it.get(\"published_at\") or \"\").strip()",
            ind + "            _sn = (_it.get(\"snippet\") or \"\").strip()",
            ind + "            _meta = []",
            ind + "            if _src:",
            ind + "                _meta.append(_src)",
            ind + "            if _pa:",
            ind + "                _meta.append(_pa)",
            ind + "            _head = \"{0}) {1}\".format(_i, _t)",
            ind + "            if _meta:",
            ind + "                _head = _head + \"（{0}）\".format(\" | \".join(_meta))",
            ind + "            _vv.append(_head)",
            ind + "            if _sn:",
            ind + "                _x = _sn",
            ind + "                if len(_x) > 90:",
            ind + "                    _x = _x[:90].rstrip() + \"...\"",
            ind + "                _vv.append(_x)",
            ind + "        final_voice = \"\\n\".join(_vv)",
            ind + "    except Exception:",
            ind + "        pass",
        ])
        # insert after the line
        line_end = out.find("\n", m.end())
        if line_end < 0:
            line_end = len(out)
        out = out[:line_end+1] + insert + "\n" + out[line_end+1:]
        changed.append("news_digest_voice_fallback")

    return out, changed

def patch_route_request(block):
    out = block
    changed = []

    # (A) default news limit: 5 -> 3 (only first occurrence in route_request)
    out2, n = re.subn(
        r'(_news__extract_limit\(\s*user_text\s*,\s*)5(\s*\))',
        r'\g<1>3\2',
        out,
        count=1
    )
    if n:
        out = out2
        changed.append("route_default_limit_3")

    # (B) if route_request hard-codes limit=5 in news_digest call, replace with limit=lim when lim exists
    # Try a safe replacement: "rrn = news_digest(category=cat, limit=5" -> "rrn = news_digest(category=cat, limit=lim"
    out2, n = re.subn(
        r'(?m)^(?P<ind>[ \t]*)rrn\s*=\s*news_digest\(\s*category\s*=\s*cat\s*,\s*limit\s*=\s*5\s*,',
        r'\g<ind>rrn = news_digest(category=cat, limit=lim,',
        out,
        count=1
    )
    if n:
        out = out2
        changed.append("route_use_lim_for_news_digest")

    # (C) make user_text passed through (avoid empty string)
    out2, n = re.subn(
        r'(?m)^(?P<ind>[ \t]*)rrn\s*=\s*news_digest\((?P<args>.*)\buser_text\s*=\s*""\s*(?P<tail>,?.*)\)\s*$',
        r'\g<ind>rrn = news_digest(\g<args>user_text=user_text\g<tail>)',
        out,
        count=1
    )
    if n:
        out = out2
        changed.append("route_pass_user_text")

    # (D) prefer final_voice when composing final
    out2, n = re.subn(
        r'(?m)^(?P<ind>[ \t]*)final\s*=\s*\(data\.get\("final"\)\s*or\s*""\)\s*if\s*isinstance\(data,\s*dict\)\s*else\s*""\s*$',
        r'\g<ind>final = (data.get("final_voice") or data.get("final") or "") if isinstance(data, dict) else ""',
        out,
        count=1
    )
    if n:
        out = out2
        changed.append("route_prefer_final_voice")

    return out, changed

def main():
    if not os.path.exists(APP):
        raise SystemExit("app.py not found")

    src = _read(APP)
    bak = _backup()

    ch = []

    # patch news_digest
    fd = _find_func(src, "news_digest")
    if not fd:
        raise SystemExit("def news_digest not found")
    s0, e0, b0 = fd
    b1, c1 = patch_news_digest(b0)
    src2 = src[:s0] + b1 + src[e0:]
    ch += c1

    # patch route_request
    fr = _find_func(src2, "route_request")
    if fr:
        s1, e1, bR = fr
        bR2, c2 = patch_route_request(bR)
        src2 = src2[:s1] + bR2 + src2[e1:]
        ch += c2

    _write(APP, src2)
    print("OK: patched P3 (final_voice non-empty + route_request voice output).")
    print("Backup:", bak)
    print("Changes:", ch)

if __name__ == "__main__":
    main()
