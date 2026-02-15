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
    bak = "app.py.bak.news_p1p3_v1b_{0}".format(ts)
    shutil.copy2(APP, bak)
    return bak

def _find_func(text, name):
    m0 = re.search(r'(?m)^def\s+{0}\s*\('.format(re.escape(name)), text)
    if not m0:
        return None
    start = m0.start()
    # next top-level def
    m1 = re.search(r'(?m)^def\s+\w+\s*\(', text[m0.end():])
    end = (m0.end() + m1.start()) if m1 else len(text)
    return (start, end, text[start:end])

def _patch_news_digest(block):
    out = block
    changed = []

    # (1) counters init after wl/bl
    m_bl = re.search(r'(?m)^(?P<ind>[ \t]*)bl\s*=\s*cfg\.get\("blacklist"\)\s*or\s*\[\]\s*$', out)
    if m_bl and ("stats_detail" not in out):
        ind = m_bl.group("ind")
        ins = "\n".join([
            ind + "dropped_blacklist = 0",
            ind + "dropped_whitelist = 0",
            ind + "dropped_anchor = 0",
            ind + "dropped_intlban = 0",
            ind + "relax_used = 0",
            ""
        ])
        pos = out.find("\n", m_bl.end())
        if pos < 0:
            pos = len(out)
        out = out[:pos+1] + ins + out[pos+1:]
        changed.append("counters_init")

    # (2) count before continue for blacklist/whitelist if patterns exist
    def _countify(pat, counter):
        nonlocal out, changed
        def repl(mm):
            ind = mm.group("ind")
            ind2 = mm.group("ind2")
            ifline = mm.group("ifline")
            return "{0}{1}\n{2}{3} += 1\n{2}continue".format(ind, ifline, ind2, counter)
        out2, n = re.subn(pat, repl, out, flags=re.M)
        if n:
            out = out2
            changed.append("count_{0}".format(counter))

    _countify(
        r'^(?P<ind>[ \t]*)(?P<ifline>if\s+not\s+_passes_blacklist\(it\)\s*:\s*)\n(?P<ind2>[ \t]*)continue\s*$',
        "dropped_blacklist"
    )
    _countify(
        r'^(?P<ind>[ \t]*)(?P<ifline>if\s+require_wl\s+and\s*\(not\s+_passes_whitelist\(it\)\)\s*:\s*)\n(?P<ind2>[ \t]*)continue\s*$',
        "dropped_whitelist"
    )
    # anchor/intlban 计数：只有存在对应 if 才会生效
    _countify(
        r'^(?P<ind>[ \t]*)(?P<ifline>if\s+not\s+_passes_anchor_topic\(it\)\s*:\s*)\n(?P<ind2>[ \t]*)continue\s*$',
        "dropped_anchor"
    )
    _countify(
        r'^(?P<ind>[ \t]*)(?P<ifline>if\s+not\s+_passes_intl_ban\(it\)\s*:\s*)\n(?P<ind2>[ \t]*)continue\s*$',
        "dropped_intlban"
    )

    # (3) build final_voice right before success return dict that contains "final": "\n".join(lines)
    if "final_voice" not in out:
        m_final_line = re.search(r'(?m)^(?P<ind>[ \t]*)"final"\s*:\s*"\n"\.join\(lines\)\s*,\s*$', out)
        if m_final_line:
            ind = m_final_line.group("ind")
            # Insert helper right before the "final" line
            helper = "\n".join([
                ind + "voice_lines = []",
                ind + "try:",
                ind + "    for _ln in lines:",
                ind + "        if re.match(r\"^\\s*https?://\", _ln or \"\"):",
                ind + "            continue",
                ind + "        _x = _ln or \"\"",
                ind + "        if len(_x) > 140:",
                ind + "            _x = _x[:140].rstrip() + \"...\"",
                ind + "        voice_lines.append(_x)",
                ind + "except Exception:",
                ind + "    voice_lines = []",
                ind + "final_voice = \"\\n\".join(voice_lines)",
                ""
            ])
            insert_at = m_final_line.start()
            out = out[:insert_at] + helper + out[insert_at:]
            changed.append("add_final_voice_helper")

            # Now add field in return dict by replacing the final line
            out2, n2 = re.subn(
                r'(?m)^(?P<ind>[ \t]*)"final"\s*:\s*"\n"\.join\(lines\)\s*,\s*$',
                r'\g<ind>"final": "\n".join(lines),\n\g<ind>"final_voice": final_voice,',
                out,
                count=1
            )
            if n2:
                out = out2
                changed.append("add_final_voice_field")

    # (4) add stats_detail into return dict near "stats": ...
    if "stats_detail" not in out:
        out2, n = re.subn(
            r'(?m)^(?P<ind>[ \t]*)"stats"\s*:\s*(?P<val>\{[^\n]*\})\s*,\s*$',
            r'\g<ind>"stats": \g<val>,\n\g<ind>"stats_detail": {"dropped_blacklist": dropped_blacklist, "dropped_whitelist": dropped_whitelist, "dropped_anchor": dropped_anchor, "dropped_intlban": dropped_intlban, "relax_used": relax_used},',
            out,
            count=1
        )
        if n:
            out = out2
            changed.append("add_stats_detail")

    return out, changed

def _patch_route_request(block):
    out = block
    changed = []

    # Default limit 5 -> 3 (only in route_request block)
    out2, n = re.subn(
        r'(_news__extract_limit\(\s*user_text\s*,\s*)5(\s*\))',
        r'\g<1>3\2',
        out,
        count=1
    )
    if n:
        out = out2
        changed.append("news_default_limit_3")

    # Prefer final_voice when selecting final from data dict
    out2, n = re.subn(
        r'(?m)^(?P<ind>[ \t]*)final\s*=\s*\(data\.get\("final"\)\s*or\s*""\)\s*if\s*isinstance\(data,\s*dict\)\s*else\s*""\s*$',
        r'\g<ind>final = (data.get("final_voice") or data.get("final") or "") if isinstance(data, dict) else ""',
        out,
        count=1
    )
    if n:
        out = out2
        changed.append("prefer_final_voice")

    return out, changed

def main():
    if not os.path.exists(APP):
        raise SystemExit("app.py not found")

    src = _read(APP)
    bak = _backup()

    # patch news_digest
    fd = _find_func(src, "news_digest")
    if not fd:
        raise SystemExit("def news_digest not found")
    s0, e0, b0 = fd
    b1, ch1 = _patch_news_digest(b0)
    src2 = src[:s0] + b1 + src[e0:]

    # patch route_request (minimal)
    fr = _find_func(src2, "route_request")
    ch2 = []
    if fr:
        s1, e1, bR = fr
        bR2, ch2 = _patch_route_request(bR)
        src2 = src2[:s1] + bR2 + src2[e1:]

    _write(APP, src2)
    print("OK: P1+P3 safe patch applied (v1b).")
    print("Backup:", bak)
    print("Changes:", (ch1 + ch2))

if __name__ == "__main__":
    main()
