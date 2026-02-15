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
    bak = path + ".bak.news_miniflux_v3c_" + ts
    _write(bak, src)
    return bak

def main():
    path = "app.py"
    if not os.path.exists(path):
        raise SystemExit("app.py not found")

    src = _read(path)

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
    if "MUST_ANCHOR" not in block or "TOPIC_KWS" not in block or "_passes_anchor_topic" not in block:
        raise SystemExit("v3b helpers not found (MUST_ANCHOR/TOPIC_KWS/_passes_anchor_topic).")

    # --- replace MUST_ANCHOR au_politics list (remove short state abbreviations to avoid false positives) ---
    # Match the list content between "au_politics": [ ... ],
    pat_anchor = re.compile(r'(?s)("au_politics"\s*:\s*\[)(.*?)(\]\s*,)')
    m = pat_anchor.search(block)
    if not m:
        raise SystemExit("cannot find MUST_ANCHOR au_politics list")

    # Keep only strong anchors (no 2-3 char abbreviations)
    new_anchor_items = [
        '"australia"', '"australian"', '"canberra"', '"parliament house"', '"commonwealth"',
        '"federal"', '"government"', '"opposition"',
        '"prime minister"', '"pm"', '"minister"', '"mp"', '"senator"', '"treasurer"',
        '"albanese"', '"dutton"', '"labor"', '"liberal"', '"greens"', '"coalition"',
        '"new south wales"', '"victoria"', '"queensland"', '"western australia"', '"south australia"', '"tasmania"', '"northern territory"', '"australian capital territory"',
        '"australian parliament"',
        '"澳"', '"澳洲"', '"澳大利亚"', '"联邦"', '"堪培拉"', '"议会"', '"政府"', '"反对党"', '"总理"', '"部长"', '"议员"', '"工党"', '"自由党"', '"绿党"'
    ]
    indent_guess = " " * 8
    if "\n        " in m.group(2):
        indent_guess = " " * 8
    new_anchor_text = "\n" + indent_guess + (",\n" + indent_guess).join(new_anchor_items) + ",\n"
    block2 = block[:m.start(2)] + new_anchor_text + block[m.end(2):]

    # --- replace TOPIC_KWS au_politics list (expand politics topics) ---
    pat_topic = re.compile(r'(?s)("au_politics"\s*:\s*\[)(.*?)(\]\s*,)')
    # We need the TOPIC_KWS au_politics, not the MUST_ANCHOR one; find after "TOPIC_KWS"
    idx_topic_map = block2.find("TOPIC_KWS")
    if idx_topic_map < 0:
        raise SystemExit("cannot find TOPIC_KWS")
    sub = block2[idx_topic_map:]
    m2 = pat_topic.search(sub)
    if not m2:
        raise SystemExit("cannot find TOPIC_KWS au_politics list")
    # compute absolute positions
    abs_start2 = idx_topic_map + m2.start(2)
    abs_end2 = idx_topic_map + m2.end(2)

    new_topic_items = [
        '"parliament"', '"senate"', '"house"', '"cabinet"', '"minister"', '"shadow minister"', '"opposition"',
        '"election"', '"vote"', '"ballot"', '"campaign"',
        '"budget"', '"treasury"', '"tax"', '"spending"', '"funding"',
        '"policy"', '"bill"', '"law"', '"laws"', '"legislation"', '"reform"', '"inquiry"', '"royal commission"',
        '"immigration"', '"visa"', '"citizenship"', '"asylum"', '"home affairs"',
        '"national security"', '"defence"', '"foreign minister"',
        '"议会"', '"参议院"', '"众议院"', '"内阁"', '"部长"', '"影子部长"', '"反对党"',
        '"选举"', '"投票"', '"竞选"',
        '"预算"', '"财政"', '"税"', '"拨款"',
        '"政策"', '"法案"', '"法律"', '"立法"', '"改革"', '"调查"',
        '"移民"', '"签证"', '"国籍"', '"内政"', '"国防"', '"外交"'
    ]
    new_topic_text = "\n" + indent_guess + (",\n" + indent_guess).join(new_topic_items) + ",\n"
    block3 = block2[:abs_start2] + new_topic_text + block2[abs_end2:]

    # --- make au_politics always require topic (ignore strict flag) ---
    block4 = block3.replace('if key == "au_politics" and strict and topics:', 'if key == "au_politics" and topics:')

    # --- add a small intl blacklist for au_politics as a safety net ---
    # Insert right after anchor check block (after "if anchors:" section ends)
    insert_marker = "    if anchors:\n        if not _kw_hit(txt_all, anchors):\n            return False\n"
    if insert_marker in block4 and "INTL_BAN" not in block4:
        add = []
        add.append("    INTL_BAN = [")
        add.append('        "bangladesh", "pakistan", "sheikh hasina", "dhaka",')
        add.append('        "india", "china", "beijing", "taiwan", "ukraine", "russia", "israel", "gaza",')
        add.append('        "孟加拉", "巴基斯坦", "达卡", "印度", "中国", "乌克兰", "俄罗斯", "以色列", "加沙",')
        add.append("    ]")
        add.append("    if key == \"au_politics\":")
        add.append("        if _kw_hit(txt_all, INTL_BAN):")
        add.append("            return False")
        add.append("")
        block4 = block4.replace(insert_marker, insert_marker + "\n" + "    ".join([""]) + "\n".join([("    " + x) for x in add]))

    out = src[:i0] + block4 + src[i1:]
    bak = _backup(path, src)
    _write(path, out)
    print("OK: refined au_politics anchor/topic filters (v3c).")
    print("Backup:", bak)

if __name__ == "__main__":
    main()
