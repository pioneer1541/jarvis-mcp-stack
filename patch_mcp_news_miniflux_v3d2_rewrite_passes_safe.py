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
    bak = path + ".bak.news_miniflux_v3d2_" + ts
    _write(bak, src)
    return bak

def main():
    path = "app.py"
    if not os.path.exists(path):
        raise SystemExit("app.py not found")

    src = _read(path)

    # 只在 Miniflux news_digest 这一段里替换，避免误伤其它位置
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

    # 必须存在 v3b 注入的函数名与 _pick，才允许继续
    if "def _passes_anchor_topic" not in block:
        raise SystemExit("_passes_anchor_topic not found in Miniflux news_digest block")
    if "def _pick(" not in block:
        raise SystemExit("_pick not found in Miniflux news_digest block")

    # 关键：严格匹配 _passes_anchor_topic 到紧邻的 def _pick( 之前
    pat = re.compile(
        r'(?ms)^(?P<indent>[ \t]*)def _passes_anchor_topic\(it: dict, strict: bool\) -> bool:\n'
        r'.*?'
        r'(?=^(?P=indent)def _pick\()'
    )
    m = pat.search(block)
    if not m:
        raise SystemExit("cannot regex-match _passes_anchor_topic -> def _pick boundary")

    indent = m.group("indent")

    # 新实现：对 au_politics 使用 title/snippet-only 的 AU+政治双条件；并加国际兜底黑名单
    new_lines = []
    new_lines.append(indent + "def _passes_anchor_topic(it: dict, strict: bool) -> bool:")
    new_lines.append(indent + "    anchors0 = MUST_ANCHOR.get(key) or []")
    new_lines.append(indent + "    topics0 = TOPIC_KWS.get(key) or []")
    new_lines.append(indent + "    if (not anchors0) and (not topics0):")
    new_lines.append(indent + "        return True")
    new_lines.append(indent + "")
    new_lines.append(indent + "    title0 = it.get(\"title\") or \"\"")
    new_lines.append(indent + "    sn0 = it.get(\"snippet\") or \"\"")
    new_lines.append(indent + "    src0 = it.get(\"source\") or \"\"")
    new_lines.append(indent + "    txt_ts = \"{0} {1}\".format(title0, sn0)")
    new_lines.append(indent + "    txt_all = \"{0} {1} {2}\".format(title0, sn0, src0)")
    new_lines.append(indent + "")
    new_lines.append(indent + "    if key == \"au_politics\":")
    new_lines.append(indent + "        # 过滤掉很短的英文锚点（避免子串误命中），只用 title/snippet 做匹配")
    new_lines.append(indent + "        anchors = []")
    new_lines.append(indent + "        for a in (anchors0 or []):")
    new_lines.append(indent + "            aa = (a or \"\").strip()")
    new_lines.append(indent + "            if not aa:")
    new_lines.append(indent + "                continue")
    new_lines.append(indent + "            if _has_cjk(aa):")
    new_lines.append(indent + "                anchors.append(aa)")
    new_lines.append(indent + "                continue")
    new_lines.append(indent + "            if len(aa) >= 4:")
    new_lines.append(indent + "                anchors.append(aa)")
    new_lines.append(indent + "")
    new_lines.append(indent + "        topics = topics0")
    new_lines.append(indent + "")
    new_lines.append(indent + "        intl_ban = [")
    new_lines.append(indent + "            \"bangladesh\", \"pakistan\", \"dhaka\", \"sheikh hasina\",")
    new_lines.append(indent + "            \"孟加拉\", \"巴基斯坦\", \"达卡\", \"哈西娜\", \"谢赫\",")
    new_lines.append(indent + "        ]")
    new_lines.append(indent + "        if _kw_hit(txt_ts.lower(), intl_ban) or _kw_hit(txt_ts, intl_ban):")
    new_lines.append(indent + "            return False")
    new_lines.append(indent + "")
    new_lines.append(indent + "        # 对 au_politics：必须同时满足 AU anchor + politics topic（避免 Just In 泛新闻污染）")
    new_lines.append(indent + "        if anchors and (not _kw_hit(txt_ts, anchors)):")
    new_lines.append(indent + "            return False")
    new_lines.append(indent + "        if topics and (not _kw_hit(txt_ts, topics)):")
    new_lines.append(indent + "            return False")
    new_lines.append(indent + "        return True")
    new_lines.append(indent + "")
    new_lines.append(indent + "    # 其它分类：沿用原本逻辑（允许 source 参与 anchor 判断）")
    new_lines.append(indent + "    if anchors0 and (not _kw_hit(txt_all, anchors0)):")
    new_lines.append(indent + "        return False")
    new_lines.append(indent + "    return True")
    new_lines.append(indent + "")

    replacement = "\n".join(new_lines)

    block2 = block[:m.start()] + replacement + block[m.end():]
    out = src[:i0] + block2 + src[i1:]

    bak = _backup(path, src)
    _write(path, out)
    print("OK: rewrote _passes_anchor_topic safely (v3d2).")
    print("Backup:", bak)

if __name__ == "__main__":
    main()
