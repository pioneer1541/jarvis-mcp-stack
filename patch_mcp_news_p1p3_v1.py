import re
import sys
import shutil
from datetime import datetime

APP = "app.py"

def _backup(path: str) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = "app.py.bak.news_p1p3_{0}".format(ts)
    shutil.copy2(path, bak)
    return bak

def _find_block(text: str, start_pat: str, end_pats: list) -> tuple:
    m0 = re.search(start_pat, text, flags=re.M)
    if not m0:
        raise RuntimeError("start pattern not found: {0}".format(start_pat))
    start = m0.start()

    tail = text[m0.end():]
    ends = []
    for ep in end_pats:
        m = re.search(ep, tail, flags=re.M)
        if m:
            ends.append(m0.end() + m.start())
    if not ends:
        raise RuntimeError("end pattern not found for: {0}".format(end_pats))
    end = min(ends)
    return start, end, text[start:end]

def _apply_patch_news_digest(block: str) -> tuple:
    text = block
    changed = []

    # 1) counters init (after bl = ...)
    pat_bl = r'(?m)^(?P<indent>[ \t]*)bl\s*=\s*cfg\.get\("blacklist"\)\s*or\s*\[\]\s*$'
    m = re.search(pat_bl, text)
    if m and ("dropped_blacklist" not in text[m.end():m.end()+250]):
        indent = m.group("indent")
        insert = "\n".join([
            indent + "dropped_blacklist = 0",
            indent + "dropped_whitelist = 0",
            indent + "dropped_anchor = 0",
            indent + "dropped_intlban = 0",
            indent + "relax_used = 0",
            ""
        ])
        line_end = text.find("\n", m.end())
        if line_end < 0:
            line_end = len(text)
        text = text[:line_end+1] + insert + text[line_end+1:]
        changed.append("insert_counters")

    def _add_counter(pattern: str, counter_name: str):
        nonlocal text, changed

        def repl(mm):
            ind = mm.group("indent")
            ifline = mm.group("ifline")
            ind2 = mm.group("indent2")
            return "{0}{1}\n{2}{3} += 1\n{2}continue".format(ind, ifline, ind2, counter_name)

        text2, n = re.subn(pattern, repl, text, flags=re.M)
        if n:
            text = text2
            changed.append("count_{0}".format(counter_name))

    # 2) add counters before continue in known filter gates
    _add_counter(
        r'^(?P<indent>[ \t]*)(?P<ifline>if\s+not\s+_passes_blacklist\(it\)\s*:\s*)\n(?P<indent2>[ \t]*)continue\s*$',
        "dropped_blacklist"
    )
    _add_counter(
        r'^(?P<indent>[ \t]*)(?P<ifline>if\s+require_wl\s+and\s*\(not\s+_passes_whitelist\(it\)\)\s*:\s*)\n(?P<indent2>[ \t]*)continue\s*$',
        "dropped_whitelist"
    )
    _add_counter(
        r'^(?P<indent>[ \t]*)(?P<ifline>if\s+not\s+_passes_anchor_topic\(it\)\s*:\s*)\n(?P<indent2>[ \t]*)continue\s*$',
        "dropped_anchor"
    )
    _add_counter(
        r'^(?P<indent>[ \t]*)(?P<ifline>if\s+not\s+_passes_intl_ban\(it\)\s*:\s*)\n(?P<indent2>[ \t]*)continue\s*$',
        "dropped_intlban"
    )

    # 3) insert voice_lines builder right before the *last* return-dict that returns items:<var>
    if "final_voice" not in text:
        rets = list(re.finditer(r'(?m)^[ \t]*return\s*\{\s*$', text))
        for r in reversed(rets):
            seg = text[r.start(): r.start() + 2500]
            mitems = re.search(r'"items"\s*:\s*([A-Za-z_][A-Za-z0-9_]*)', seg)
            if not mitems:
                continue
            items_var = mitems.group(1)

            # indent from the return line
            line_start = text.rfind("\n", 0, r.start()) + 1
            indent = re.match(r'[ \t]*', text[line_start:r.start()]).group(0)

            voice_block = "\n".join([
                indent + "voice_lines = []",
                indent + "try:",
                indent + "    for _i, _it in enumerate({0}, 1):".format(items_var),
                indent + "        _t = (_it.get(\"title\") or \"\").strip()",
                indent + "        _src = (_it.get(\"source\") or \"\").strip()",
                indent + "        _pa = (_it.get(\"published_at\") or \"\").strip()",
                indent + "        _sn = (_it.get(\"snippet\") or \"\").strip()",
                indent + "        _meta = []",
                indent + "        if _src:",
                indent + "            _meta.append(_src)",
                indent + "        if _pa:",
                indent + "            _meta.append(_pa)",
                indent + "        _head = \"{0}) {1}\".format(_i, _t)",
                indent + "        if _meta:",
                indent + "            _head = _head + \"（{0}）\".format(\" | \".join(_meta))",
                indent + "        voice_lines.append(_head)",
                indent + "        if _sn:",
                indent + "            _vsn = _sn",
                indent + "            if len(_vsn) > 90:",
                indent + "                _vsn = _vsn[:90].rstrip() + \"...\"",
                indent + "            voice_lines.append(_vsn)",
                indent + "except Exception:",
                indent + "    voice_lines = []",
                indent + "",
            ])
            text = text[:r.start()] + voice_block + text[r.start():]
            changed.append("add_final_voice_block")
            break

    # 4) add stats_detail next to items:<var> (only matches var-name, won't match items: [])
    if "stats_detail" not in text:
        pat_items = r'(?m)^(?P<indent>[ \t]*)"items"\s*:\s*(?P<var>[A-Za-z_][A-Za-z0-9_]*)\s*,\s*$'
        def repl_items(mm):
            ind = mm.group("indent")
            var = mm.group("var")
            return (
                '{0}"items": {1},\n'
                '{0}"stats_detail": {{"dropped_blacklist": dropped_blacklist, "dropped_whitelist": dropped_whitelist, "dropped_anchor": dropped_anchor, "dropped_intlban": dropped_intlban, "relax_used": relax_used}},'
            ).format(ind, var)

        text2, n = re.subn(pat_items, repl_items, text, count=1)
        if n:
            text = text2
            changed.append("add_stats_detail")

    # 5) add final_voice field right after the success final join(lines)
    if "final_voice" not in text:
        pat_final = r'(?m)^(?P<indent>[ \t]*)"final"\s*:\s*"\\n"\.join\(lines\)\s*,\s*$'
        def repl_final(mm):
            ind = mm.group("indent")
            return (
                '{0}"final": "\\n".join(lines),\n'
                '{0}"final_voice": "\\n".join(voice_lines),'
            ).format(ind)

        text2, n = re.subn(pat_final, repl_final, text, count=1)
        if n:
            text = text2
            changed.append("add_final_voice_field")

    return text, changed

def _patch_route_request(text: str) -> tuple:
    changed = []

    # Replace the whole _news__is_query block (keeps indentation correct)
    pat = r'(?ms)^\s{4}if _news__is_query\(user_text\):\n.*?\n\s{4}# Semi-structured retrieval: news digest\n'
    m = re.search(pat, text)
    if m:
        repl = (
            "    if _news__is_query(user_text):\n"
            "        cat = _news__category_from_text(user_text)\n"
            "        tr = _news__time_range_from_text(user_text)\n"
            "        lim = _news__extract_limit(user_text, 3)\n"
            "        rrn = news_digest(category=cat, limit=lim, time_range=tr, prefer_lang=\"zh\", user_text=user_text)\n"
            "        if rrn.get(\"ok\") and str((rrn.get(\"final_voice\") or rrn.get(\"final\") or \"\")).strip():\n"
            "            final = rrn.get(\"final_voice\") or rrn.get(\"final\")\n"
            "            return {\"ok\": True, \"route_type\": \"semi_structured_news\", \"final\": final, \"data\": rrn}\n"
            "        return {\"ok\": True, \"route_type\": \"semi_structured_news\", \"final\": \"新闻检索失败或暂无结果。\", \"data\": rrn}\n"
            "\n"
            "    # Semi-structured retrieval: news digest\n"
        )
        text = text[:m.start()] + repl + text[m.end():]
        changed.append("route_request_news_is_query")

    # In the legacy _is_news_query branch: default limit=3 and prefer final_voice
    text2, n1 = re.subn(r'(?m)^(\s{8}lim\s*=\s*_news__extract_limit\(user_text,\s*)5(\)\s*)$',
                        r'\g<1>3\g<2>', text, count=1)
    if n1:
        text = text2
        changed.append("route_request_news_default_limit_3")

    text2, n2 = re.subn(
        r'(?m)^\s{8}final\s*=\s*\(data\.get\("final"\)\s*or\s*""\)\s*if\s*isinstance\(data,\s*dict\)\s*else\s*""\s*$',
        '        final = (data.get("final_voice") or data.get("final") or "") if isinstance(data, dict) else ""',
        text,
        count=1
    )
    if n2:
        text = text2
        changed.append("route_request_news_use_final_voice")

    return text, changed

def main():
    with open(APP, "r", encoding="utf-8") as f:
        src = f.read()

    bak = _backup(APP)

    # Patch news_digest block only
    start, end, blk = _find_block(
        src,
        r'(?m)^def news_digest\(',
        [r'(?m)^def news_digest_legacy_fn_1\(', r'(?m)^def _news__norm_host\(']
    )
    blk2, ch1 = _apply_patch_news_digest(blk)
    out = src[:start] + blk2 + src[end:]

    # Patch route_request
    out, ch2 = _patch_route_request(out)

    with open(APP, "w", encoding="utf-8") as f:
        f.write(out)

    print("OK: patched P1+P3 (news stats_detail + final_voice; route_request voice default).")
    print("Backup:", bak)
    print("Changes:", (ch1 + ch2))

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("ERROR:", str(e))
        sys.exit(1)
