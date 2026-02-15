#!/usr/bin/env python3
import os
from datetime import datetime

def _read(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()

def _write(p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)

def _backup(path, src):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = path + ".bak.news_miniflux_v3d_" + ts
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

    # end boundary
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

    # locate function definition line
    needle = "def _passes_anchor_topic(it: dict, strict: bool) -> bool:"
    p = block.find(needle)
    if p < 0:
        raise SystemExit("cannot find _passes_anchor_topic in Miniflux news_digest block")

    # find function indent (spaces before def)
    line_start = block.rfind("\n", 0, p)
    if line_start < 0:
        line_start = 0
    else:
        line_start += 1
    indent = ""
    while line_start + len(indent) < len(block) and block[line_start + len(indent)] == " ":
        indent += " "
    if not indent:
        indent = "    "

    # find end of function: next line that starts with same indent + "def "
    # start scanning from after the def line
    def_line_end = block.find("\n", p)
    if def_line_end < 0:
        raise SystemExit("cannot parse _passes_anchor_topic def line")
    scan = def_line_end + 1

    endp = -1
    while scan < len(block):
        nl = block.find("\n", scan)
        if nl < 0:
            nl = len(block)
        line = block[scan:nl]
        if line.startswith(indent + "def ") and (not line.startswith(indent + "def _passes_anchor_topic")):
            endp = scan
            break
        scan = nl + 1
    if endp < 0:
        raise SystemExit("cannot find end of _passes_anchor_topic (next def)")

    new_fn = []
    new_fn.append(indent + "def _passes_anchor_topic(it: dict, strict: bool) -> bool:")
    new_fn.append(indent + "    anchors0 = MUST_ANCHOR.get(key) or []")
    new_fn.append(indent + "    topics0 = TOPIC_KWS.get(key) or []")
    new_fn.append(indent + "    if (not anchors0) and (not topics0):")
    new_fn.append(indent + "        return True")
    new_fn.append(indent + "")
    new_fn.append(indent + "    title0 = it.get(\"title\") or \"\"")
    new_fn.append(indent + "    sn0 = it.get(\"snippet\") or \"\"")
    new_fn.append(indent + "    src0 = it.get(\"source\") or \"\"")
    new_fn.append(indent + "    txt_ts = \"{0} {1}\".format(title0, sn0)")
    new_fn.append(indent + "    txt_all = \"{0} {1} {2}\".format(title0, sn0, src0)")
    new_fn.append(indent + "")
    new_fn.append(indent + "    # For au_politics: avoid false positives from short tokens and source strings.")
    new_fn.append(indent + "    if key == \"au_politics\":")
    new_fn.append(indent + "        # drop very short anchor tokens (e.g., act/vic/wa) to avoid substring false hits")
    new_fn.append(indent + "        anchors = []")
    new_fn.append(indent + "        for a in anchors0:")
    new_fn.append(indent + "            aa = (a or \"\").strip()")
    new_fn.append(indent + "            if not aa:")
    new_fn.append(indent + "                continue")
    new_fn.append(indent + "            # keep Chinese anchors; for Latin anchors keep length>=4")
    new_fn.append(indent + "            if _has_cjk(aa):")
    new_fn.append(indent + "                anchors.append(aa)")
    new_fn.append(indent + "                continue")
    new_fn.append(indent + "            if len(aa) >= 4:")
    new_fn.append(indent + "                anchors.append(aa)")
    new_fn.append(indent + "")
    new_fn.append(indent + "        topics = topics0")
    new_fn.append(indent + "")
    new_fn.append(indent + "        # intl safety net (Bangladesh etc.) based on title/snippet only")
    new_fn.append(indent + "        intl_ban = [")
    new_fn.append(indent + "            \"bangladesh\", \"pakistan\", \"dhaka\", \"sheikh hasina\",")
    new_fn.append(indent + "            \"孟加拉\", \"巴基斯坦\", \"达卡\", \"谢赫\", \"哈西娜\",")
    new_fn.append(indent + "        ]")
    new_fn.append(indent + "        if _kw_hit(txt_ts, intl_ban):")
    new_fn.append(indent + "            return False")
    new_fn.append(indent + "")
    new_fn.append(indent + "        src_low = (src0 or \"\").lower()")
    new_fn.append(indent + "        # ABC 'Just In' is very broad: require both AU anchor AND politics topic in title/snippet")
    new_fn.append(indent + "        if \"just in\" in src_low:")
    new_fn.append(indent + "            if anchors and (not _kw_hit(txt_ts, anchors)):")
    new_fn.append(indent + "                return False")
    new_fn.append(indent + "            if topics and (not _kw_hit(txt_ts, topics)):")
    new_fn.append(indent + "                return False")
    new_fn.append(indent + "            return True")
    new_fn.append(indent + "")
    new_fn.append(indent + "        # For au_politics generally: require anchor+topic in title/snippet (do not use source to match)")
    new_fn.append(indent + "        if anchors and (not _kw_hit(txt_ts, anchors)):")
    new_fn.append(indent + "            return False")
    new_fn.append(indent + "        if topics and (not _kw_hit(txt_ts, topics)):")
    new_fn.append(indent + "            return False")
    new_fn.append(indent + "        return True")
    new_fn.append(indent + "")
    new_fn.append(indent + "    # Default (other categories): anchor check can include source string")
    new_fn.append(indent + "    if anchors0 and (not _kw_hit(txt_all, anchors0)):")
    new_fn.append(indent + "        return False")
    new_fn.append(indent + "    return True")
    new_fn.append("")

    new_fn_text = "\n".join(new_fn)

    out_block = block[:p] + new_fn_text + block[endp:]
    out = src[:i0] + out_block + src[i1:]

    bak = _backup(path, src)
    _write(path, out)
    print("OK: rewrote _passes_anchor_topic for au_politics strict filtering (v3d).")
    print("Backup:", bak)

if __name__ == "__main__":
    main()
