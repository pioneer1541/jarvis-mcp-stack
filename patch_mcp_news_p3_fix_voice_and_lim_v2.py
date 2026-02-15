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
    bak = "app.py.bak.news_p3_fix2_{0}".format(ts)
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

def _patch_news_digest(block):
    out = block
    changed = []

    if "__VOICE_FINAL_FROM_OUT_ITEMS__" in out:
        return out, changed

    # Find the success return-dict that contains '"items": out_items'
    m_items = re.search(r'(?m)^(?P<ind>[ \t]*)"items"\s*:\s*out_items\s*,\s*$', out)
    if not m_items:
        return out, changed

    ind = m_items.group("ind")

    # Find the nearest preceding 'return {' line before this items line
    before = out[:m_items.start()]
    rets = list(re.finditer(r'(?m)^[ \t]*return\s*\{\s*$', before))
    if not rets:
        return out, changed
    m_ret = rets[-1]
    # Indent of the return line
    line_start = out.rfind("\n", 0, m_ret.start()) + 1
    ind_ret = re.match(r'[ \t]*', out[line_start:m_ret.start()]).group(0)

    voice_block = "\n".join([
        ind_ret + "# __VOICE_FINAL_FROM_OUT_ITEMS__",
        ind_ret + "final_voice2 = \"\"",
        ind_ret + "try:",
        ind_ret + "    _vv = []",
        ind_ret + "    for _i, _it in enumerate(out_items, 1):",
        ind_ret + "        _t = (_it.get(\"title\") or \"\").strip()",
        ind_ret + "        _src = (_it.get(\"source\") or \"\").strip()",
        ind_ret + "        _pa = (_it.get(\"published_at\") or \"\").strip()",
        ind_ret + "        _sn = (_it.get(\"snippet\") or \"\").strip()",
        ind_ret + "        _meta = []",
        ind_ret + "        if _src:",
        ind_ret + "            _meta.append(_src)",
        ind_ret + "        if _pa:",
        ind_ret + "            _meta.append(_pa)",
        ind_ret + "        _head = \"{0}) {1}\".format(_i, _t)",
        ind_ret + "        if _meta:",
        ind_ret + "            _head = _head + \"（{0}）\".format(\" | \".join(_meta))",
        ind_ret + "        _vv.append(_head)",
        ind_ret + "        if _sn:",
        ind_ret + "            _x = _sn",
        ind_ret + "            if len(_x) > 90:",
        ind_ret + "                _x = _x[:90].rstrip() + \"...\"",
        ind_ret + "            _vv.append(_x)",
        ind_ret + "    final_voice2 = \"\\n\".join(_vv)",
        ind_ret + "except Exception:",
        ind_ret + "    final_voice2 = \"\"",
        ""
    ])

    # Insert voice block just before 'return {'
    out = out[:m_ret.start()] + voice_block + out[m_ret.start():]
    changed.append("news_digest_build_final_voice2")

    # Replace return field "final_voice": ... with final_voice2 if exists; otherwise add it
    # First try replace existing "final_voice": <something>,
    out2, n = re.subn(
        r'(?m)^(?P<ind>[ \t]*)"final_voice"\s*:\s*[^,\n]*\s*,\s*$',
        r'\g<ind>"final_voice": final_voice2,',
        out,
        count=1
    )
    if n:
        out = out2
        changed.append("news_digest_final_voice_use_final_voice2")
    else:
        # Add final_voice right after "final": line
        out2, n2 = re.subn(
            r'(?m)^(?P<ind>[ \t]*)"final"\s*:\s*"\n"\.join\(lines\)\s*,\s*$',
            r'\g<ind>"final": "\n".join(lines),\n\g<ind>"final_voice": final_voice2,',
            out,
            count=1
        )
        if n2:
            out = out2
            changed.append("news_digest_insert_final_voice2_field")

    return out, changed

def _patch_route_request(block):
    out = block
    changed = []

    # Replace limit=lim with inline extract to avoid UnboundLocalError
    out2, n = re.subn(
        r'limit\s*=\s*lim\b',
        'limit=_news__extract_limit(user_text, 3)',
        out
    )
    if n:
        out = out2
        changed.append("route_inline_limit_extract")

    # Ensure prefer final_voice when composing final from data dict
    out2, n2 = re.subn(
        r'(?m)^(?P<ind>[ \t]*)final\s*=\s*\(data\.get\("final"\)\s*or\s*""\)\s*if\s*isinstance\(data,\s*dict\)\s*else\s*""\s*$',
        r'\g<ind>final = (data.get("final_voice") or data.get("final") or "") if isinstance(data, dict) else ""',
        out,
        count=1
    )
    if n2:
        out = out2
        changed.append("route_prefer_final_voice")

    # Default limit 5 -> 3 for explicit extract calls if still present
    out2, n3 = re.subn(
        r'(_news__extract_limit\(\s*user_text\s*,\s*)5(\s*\))',
        r'\g<1>3\2',
        out,
        count=1
    )
    if n3:
        out = out2
        changed.append("route_default_limit_3")

    return out, changed

def main():
    if not os.path.exists(APP):
        raise SystemExit("app.py not found")

    src = _read(APP)
    bak = _backup()
    changes = []

    fd = _find_func(src, "news_digest")
    if not fd:
        raise SystemExit("def news_digest not found")
    s0, e0, b0 = fd
    b1, c1 = _patch_news_digest(b0)
    src2 = src[:s0] + b1 + src[e0:]
    changes += c1

    fr = _find_func(src2, "route_request")
    if fr:
        s1, e1, bR = fr
        bR2, c2 = _patch_route_request(bR)
        src2 = src2[:s1] + bR2 + src2[e1:]
        changes += c2

    _write(APP, src2)
    print("OK: patched P3 fix v2 (final_voice from out_items + route inline limit).")
    print("Backup:", bak)
    print("Changes:", changes)

if __name__ == "__main__":
    main()
