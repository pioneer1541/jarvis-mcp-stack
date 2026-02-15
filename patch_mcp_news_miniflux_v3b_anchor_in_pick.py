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
    bak = path + ".bak.news_miniflux_v3b_" + ts
    _write(bak, src)
    return bak

def main():
    path = "app.py"
    if not os.path.exists(path):
        raise SystemExit("app.py not found")

    src = _read(path)

    # --- locate Miniflux news_digest block ---
    marker = 'description="(Tool) News digest via Miniflux (RSS).'
    i0 = src.find(marker)
    if i0 < 0:
        raise SystemExit("cannot find Miniflux news_digest marker")

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

    # idempotency
    if "_passes_anchor_topic" in block:
        print("Looks already patched (_passes_anchor_topic present). No changes.")
        return

    # 1) ensure empty-entries branch returns stats (optional but nice)
    # Patch only if we see the empty final string and no stats nearby.
    if 'final": "暂无符合最近24小时的条目。"' in block and '"stats"' not in block:
        block = block.replace(
            '"final": "暂无符合最近24小时的条目。",\n            "query_used": ',
            '"final": "暂无符合最近24小时的条目。",\n            "stats": {"fetched": 0, "zh_fetched": 0, "en_fetched": 0, "returned": 0},\n            "query_used": '
        )

    # 2) inject MUST_ANCHOR/TOPIC_KWS + _passes_anchor_topic just before def _pick
    m_pick_def = re.search(r"(?m)^\s*def _pick\(", block)
    if not m_pick_def:
        raise SystemExit("cannot find def _pick(...) in Miniflux news_digest")

    # we will insert at the same indent level as def _pick (usually 4 spaces)
    # get indent from the def line
    m_line = re.search(r"(?m)^(?P<indent>\s*)def _pick\(", block)
    indent = m_line.group("indent") if m_line else "    "

    inject = []
    inject.append(indent + "MUST_ANCHOR = {")
    inject.append(indent + '    "au_politics": [')
    inject.append(indent + '        "australia", "australian", "canberra", "parliament house", "commonwealth",')
    inject.append(indent + '        "aec", "aph.gov.au", "pm.gov.au",')
    inject.append(indent + '        "act", "nsw", "vic", "qld", "wa", "sa", "tas", "nt",')
    inject.append(indent + '        "albanese", "dutton", "labor", "liberal", "greens", "coalition",')
    inject.append(indent + '        "澳", "澳洲", "澳大利亚", "联邦", "堪培拉", "议会", "工党", "自由党", "绿党",')
    inject.append(indent + "    ],")
    inject.append(indent + '    "mel_life": [')
    inject.append(indent + '        "melbourne", "victoria", "vic", "cbd", "ptv", "metro", "tram", "train", "bus",')
    inject.append(indent + '        "yarra", "docklands", "st kilda",')
    inject.append(indent + '        "墨尔本", "维州", "本地", "民生", "交通", "电车", "火车",')
    inject.append(indent + "    ],")
    inject.append(indent + "}")
    inject.append("")
    inject.append(indent + "TOPIC_KWS = {")
    inject.append(indent + '    "au_politics": [')
    inject.append(indent + '        "parliament", "senate", "house", "cabinet", "minister",')
    inject.append(indent + '        "election", "vote", "budget", "treasury", "policy", "bill", "legislation",')
    inject.append(indent + '        "immigration", "visa", "home affairs",')
    inject.append(indent + '        "议会", "参议院", "众议院", "内阁", "部长", "选举", "投票", "预算", "财政", "政策", "法案", "立法",')
    inject.append(indent + '        "移民", "签证",')
    inject.append(indent + "    ],")
    inject.append(indent + "}")
    inject.append("")
    inject.append(indent + "def _passes_anchor_topic(it: dict, strict: bool) -> bool:")
    inject.append(indent + "    # strict=True 对应 require_wl=True（严格阶段）；strict=False 对应放宽阶段")
    inject.append(indent + "    anchors = MUST_ANCHOR.get(key) or []")
    inject.append(indent + "    topics = TOPIC_KWS.get(key) or []")
    inject.append(indent + "    if not anchors and not topics:")
    inject.append(indent + "        return True")
    inject.append(indent + "    title0 = it.get(\"title\") or \"\"")
    inject.append(indent + "    sn0 = it.get(\"snippet\") or \"\"")
    inject.append(indent + "    src0 = it.get(\"source\") or \"\"")
    inject.append(indent + "    txt_all = \"{0} {1} {2}\".format(title0, sn0, src0)")
    inject.append(indent + "    if anchors:")
    inject.append(indent + "        if not _kw_hit(txt_all, anchors):")
    inject.append(indent + "            return False")
    inject.append(indent + "    # 仅 au_politics 在严格阶段要求 topic 命中，避免 Bangladesh election 这类污染")
    inject.append(indent + "    if key == \"au_politics\" and strict and topics:")
    inject.append(indent + "        txt_ts = \"{0} {1}\".format(title0, sn0)")
    inject.append(indent + "        if not _kw_hit(txt_ts, topics):")
    inject.append(indent + "            return False")
    inject.append(indent + "    return True")
    inject.append("")

    block2 = block[:m_pick_def.start()] + "\n".join(inject) + block[m_pick_def.start():]

    # 3) in _pick loop: add anchor/topic gate right after whitelist gate
    # Find the specific whitelist gate line
    wl_gate = "            if require_wl and (not _passes_whitelist(it)):"
    pos = block2.find(wl_gate)
    if pos < 0:
        raise SystemExit("cannot find whitelist gate line in _pick")

    # Insert after the whitelist gate block (2 lines: gate + continue)
    # We patch the first occurrence only.
    # We locate the 'continue' line that follows it.
    pos2 = block2.find("                continue", pos)
    if pos2 < 0:
        raise SystemExit("cannot find continue after whitelist gate")

    # insert after that continue line
    insert_at = block2.find("\n", pos2)
    if insert_at < 0:
        raise SystemExit("cannot find line break after whitelist continue")
    insert_at = insert_at + 1

    add_lines = []
    add_lines.append("            if not _passes_anchor_topic(it, require_wl):")
    add_lines.append("                continue")
    add_lines.append("")
    add = "\n".join(add_lines)

    block3 = block2[:insert_at] + add + block2[insert_at:]

    out = src[:i0] + block3 + src[i1:]

    bak = _backup(path, src)
    _write(path, out)
    print("OK: patched Miniflux news_digest topic filter via _pick gate (v3b).")
    print("Backup:", bak)

if __name__ == "__main__":
    main()
