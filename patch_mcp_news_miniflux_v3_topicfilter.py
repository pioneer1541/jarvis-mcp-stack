#!/usr/bin/env python3
import os
import re
from datetime import datetime

def _read(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()

def _write(p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)

def _backup(path, src):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = path + ".bak.news_miniflux_v3_" + ts
    _write(bak, src)
    return bak

def main():
    path = "app.py"
    if not os.path.exists(path):
        raise SystemExit("app.py not found")

    src = _read(path)

    # --- locate miniflux news_digest block (tool description marker is stable) ---
    marker = 'description="(Tool) News digest via Miniflux (RSS).'
    i0 = src.find(marker)
    if i0 < 0:
        raise SystemExit("cannot find Miniflux news_digest marker")

    # end boundary: legacy fn or v3 end marker
    end_candidates = []
    j1 = src.find("def news_digest_legacy_fn_1", i0)
    if j1 > 0:
        end_candidates.append(j1)
    j2 = src.find("# NEWS_DIGEST_V3_END", i0)
    if j2 > 0:
        end_candidates.append(j2)
    if not end_candidates:
        raise SystemExit("cannot find end boundary for Miniflux news_digest block")

    i1 = min(end_candidates)
    block = src[i0:i1]

    if "MUST_ANCHOR" in block and "TOPIC_KWS" in block:
        print("Looks already patched (MUST_ANCHOR/TOPIC_KWS present). No changes.")
        return

    # 1) Inject MUST_ANCHOR / TOPIC_KWS before cfg = FILTERS.get(key)...
    needle_cfg = 'cfg = FILTERS.get(key) or {"whitelist": [], "blacklist": []}'
    if needle_cfg not in block:
        raise SystemExit("cannot find cfg = FILTERS.get(key) line in block")

    inject = []
    inject.append('    MUST_ANCHOR = {')
    inject.append('        "au_politics": [')
    inject.append('            "australia", "australian", "canberra", "parliament house", "commonwealth",')
    inject.append('            "aec", "aph.gov.au", "pm.gov.au",')
    inject.append('            "act", "nsw", "vic", "qld", "wa", "sa", "tas", "nt",')
    inject.append('            "albanese", "dutton", "labor", "liberal", "greens", "coalition",')
    inject.append('            "澳", "澳洲", "澳大利亚", "联邦", "堪培拉", "议会", "工党", "自由党", "绿党",')
    inject.append('        ],')
    inject.append('        "mel_life": [')
    inject.append('            "melbourne", "victoria", "vic", "cbd", "ptv", "metro", "tram", "train", "bus",')
    inject.append('            "yarra", "docklands", "st kilda",')
    inject.append('            "墨尔本", "维州", "本地", "民生", "交通", "电车", "火车",')
    inject.append('        ],')
    inject.append('    }')
    inject.append('')
    inject.append('    TOPIC_KWS = {')
    inject.append('        "au_politics": [')
    inject.append('            "parliament", "senate", "house", "cabinet", "minister",')
    inject.append('            "election", "vote", "budget", "treasury", "policy", "bill", "legislation",')
    inject.append('            "immigration", "visa", "home affairs",')
    inject.append('            "议会", "参议院", "众议院", "内阁", "部长", "选举", "投票", "预算", "财政", "政策", "法案", "立法",')
    inject.append('            "移民", "签证",')
    inject.append('        ],')
    inject.append('    }')
    inject.append('')

    block2 = block.replace(needle_cfg, "\n".join(inject) + needle_cfg)

    # 2) After en_items = ... line, inject anchor/topic helpers + filtered lists
    # We match the first occurrence within this block only.
    m_en = re.search(r"(?m)^(?P<indent>\s*)en_items\s*=\s*\[.*\]\s*$", block2)
    if not m_en:
        raise SystemExit("cannot find en_items = [...] line in block")

    indent = m_en.group("indent")
    helper = []
    helper.append("")
    helper.append(indent + "must_anchor = MUST_ANCHOR.get(key) or []")
    helper.append(indent + "topic_kws = TOPIC_KWS.get(key) or []")
    helper.append(indent + "need_anchor = bool(must_anchor)")
    helper.append(indent + "need_topic = bool(topic_kws)")
    helper.append("")
    helper.append(indent + "def _passes_anchor(it: dict) -> bool:")
    helper.append(indent + "    if not need_anchor:")
    helper.append(indent + "        return True")
    helper.append(indent + "    txt = \"{0} {1} {2}\".format(it.get(\"title\") or \"\", it.get(\"snippet\") or \"\", it.get(\"source\") or \"\")")
    helper.append(indent + "    return _kw_hit(txt, must_anchor)")
    helper.append("")
    helper.append(indent + "def _passes_topic(it: dict) -> bool:")
    helper.append(indent + "    if not need_topic:")
    helper.append(indent + "        return True")
    helper.append(indent + "    txt = \"{0} {1}\".format(it.get(\"title\") or \"\", it.get(\"snippet\") or \"\")")
    helper.append(indent + "    return _kw_hit(txt, topic_kws)")
    helper.append("")
    helper.append(indent + "def _filter_anchor_topic(items_in: list, req_anchor: bool, req_topic: bool) -> list:")
    helper.append(indent + "    out = []")
    helper.append(indent + "    for it in (items_in or []):")
    helper.append(indent + "        if req_anchor and (not _passes_anchor(it)):")
    helper.append(indent + "            continue")
    helper.append(indent + "        if req_topic and (not _passes_topic(it)):")
    helper.append(indent + "            continue")
    helper.append(indent + "        out.append(it)")
    helper.append(indent + "    return out")
    helper.append("")
    helper.append(indent + "# Strict: anchor+topic; Relax1: anchor only")
    helper.append(indent + "zh_at = _filter_anchor_topic(zh_items, need_anchor, need_topic)")
    helper.append(indent + "en_at = _filter_anchor_topic(en_items, need_anchor, need_topic)")
    helper.append(indent + "zh_a = _filter_anchor_topic(zh_items, need_anchor, False) if need_topic else zh_at")
    helper.append(indent + "en_a = _filter_anchor_topic(en_items, need_anchor, False) if need_topic else en_at")
    helper.append("")

    insert_pos = m_en.end()
    block3 = block2[:insert_pos] + "\n".join(helper) + block2[insert_pos:]

    # 3) Replace strict pick block (the first if prefer == "zh": ... else: ... with require_wl=True)
    strict_pat = re.compile(
        r"(?ms)^\s*if\s+prefer\s*==\s*\"zh\"\s*:\s*\n"
        r"(?:\s*_pick\([^\n]*\)\s*\n)+"
        r"^\s*else\s*:\s*\n"
        r"(?:\s*_pick\([^\n]*\)\s*\n)+"
    )
    m_strict = strict_pat.search(block3)
    if not m_strict:
        raise SystemExit("cannot locate strict pick block (if prefer == \"zh\")")

    strict_new = []
    strict_new.append(indent + "if prefer == \"zh\":")
    strict_new.append(indent + "    _pick(zh_at, True, lim_int - len(picked), picked, seen)")
    strict_new.append(indent + "    _pick(en_at, True, lim_int - len(picked), picked, seen)")
    strict_new.append(indent + "    if need_topic and (len(picked) < lim_int):")
    strict_new.append(indent + "        _pick(zh_a, True, lim_int - len(picked), picked, seen)")
    strict_new.append(indent + "        _pick(en_a, True, lim_int - len(picked), picked, seen)")
    strict_new.append(indent + "    if need_anchor and (len(picked) < lim_int):")
    strict_new.append(indent + "        _pick(zh_items, True, lim_int - len(picked), picked, seen)")
    strict_new.append(indent + "        _pick(en_items, True, lim_int - len(picked), picked, seen)")
    strict_new.append(indent + "else:")
    strict_new.append(indent + "    _pick(en_at, True, lim_int - len(picked), picked, seen)")
    strict_new.append(indent + "    _pick(zh_at, True, lim_int - len(picked), picked, seen)")
    strict_new.append(indent + "    if need_topic and (len(picked) < lim_int):")
    strict_new.append(indent + "        _pick(en_a, True, lim_int - len(picked), picked, seen)")
    strict_new.append(indent + "        _pick(zh_a, True, lim_int - len(picked), picked, seen)")
    strict_new.append(indent + "    if need_anchor and (len(picked) < lim_int):")
    strict_new.append(indent + "        _pick(en_items, True, lim_int - len(picked), picked, seen)")
    strict_new.append(indent + "        _pick(zh_items, True, lim_int - len(picked), picked, seen)")
    strict_new.append("")
    block4 = block3[:m_strict.start()] + "\n".join(strict_new) + block3[m_strict.end():]

    # 4) Replace relax-whitelist pick block (require_wl=False) to prefer anchor-first when available
    relax_pat = re.compile(
        r"(?ms)^\s*if\s+len\(picked\)\s*<\s*lim_int\s*:\s*\n"
        r"^\s*if\s+prefer\s*==\s*\"zh\"\s*:\s*\n"
        r"(?:\s*_pick\([^\n]*\)\s*\n)+"
        r"^\s*else\s*:\s*\n"
        r"(?:\s*_pick\([^\n]*\)\s*\n)+"
    )
    m_relax = relax_pat.search(block4)
    if not m_relax:
        raise SystemExit("cannot locate relax pick block (require_wl=False)")

    relax_new = []
    relax_new.append(indent + "if len(picked) < lim_int:")
    relax_new.append(indent + "    # When we have anchors (au_politics/mel_life), try anchor-first even in relaxed whitelist stage")
    relax_new.append(indent + "    if need_anchor:")
    relax_new.append(indent + "        if prefer == \"zh\":")
    relax_new.append(indent + "            _pick(zh_a, False, lim_int - len(picked), picked, seen)")
    relax_new.append(indent + "            _pick(en_a, False, lim_int - len(picked), picked, seen)")
    relax_new.append(indent + "        else:")
    relax_new.append(indent + "            _pick(en_a, False, lim_int - len(picked), picked, seen)")
    relax_new.append(indent + "            _pick(zh_a, False, lim_int - len(picked), picked, seen)")
    relax_new.append(indent + "    if len(picked) < lim_int:")
    relax_new.append(indent + "        if prefer == \"zh\":")
    relax_new.append(indent + "            _pick(zh_items, False, lim_int - len(picked), picked, seen)")
    relax_new.append(indent + "            _pick(en_items, False, lim_int - len(picked), picked, seen)")
    relax_new.append(indent + "        else:")
    relax_new.append(indent + "            _pick(en_items, False, lim_int - len(picked), picked, seen)")
    relax_new.append(indent + "            _pick(zh_items, False, lim_int - len(picked), picked, seen)")
    relax_new.append("")
    block5 = block4[:m_relax.start()] + "\n".join(relax_new) + block4[m_relax.end():]

    # 5) Add stats for empty entries branch ("暂无符合最近24小时的条目。")
    # Only patch the first occurrence inside this block.
    empty_pat = re.compile(r'(?ms)"final"\s*:\s*"暂无符合最近24小时的条目。"\s*,\s*\n\s*"query_used"\s*:\s*[^,\n]+,\s*\n')
    m_empty = empty_pat.search(block5)
    if m_empty:
        snippet = m_empty.group(0)
        if '"stats"' not in snippet:
            add = snippet + '            "stats": {"fetched": 0, "zh_fetched": 0, "en_fetched": 0, "returned": 0},\n'
            block5 = block5[:m_empty.start()] + add + block5[m_empty.end():]

    # Replace original block in src
    out = src[:i0] + block5 + src[i1:]

    bak = _backup(path, src)
    _write(path, out)
    print("OK: patched Miniflux news_digest topic filtering (v3).")
    print("Backup:", bak)

if __name__ == "__main__":
    main()
