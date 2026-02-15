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
    bak = path + ".bak.news_miniflux_v3d3_" + ts
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

    # get indent style from def _pick(
    m_pick = re.search(r'(?m)^(?P<indent>[ \t]*)def _pick\(', block)
    if not m_pick:
        raise SystemExit("cannot find def _pick( in Miniflux news_digest block")
    indent = m_pick.group("indent")
    unit = "\t" if ("\t" in indent) else "    "
    body = indent + unit

    # ensure _kw_hit and _has_cjk exist in scope (should, per your earlier grep)
    if "_kw_hit" not in block:
        raise SystemExit("_kw_hit not found in Miniflux news_digest block")
    if "_has_cjk" not in block:
        # _has_cjk may be earlier in the same function; if not, we can still work without it
        pass

    pat = re.compile(
        r'(?ms)^' + re.escape(indent) + r'def _passes_anchor_topic\(it: dict, strict: bool\) -> bool:\n'
        r'.*?'
        r'(?=^' + re.escape(indent) + r'def _pick\()'
    )
    m = pat.search(block)
    if not m:
        raise SystemExit("cannot locate _passes_anchor_topic -> def _pick boundary with the expected indent")

    lines = []
    lines.append(indent + "def _passes_anchor_topic(it: dict, strict: bool) -> bool:")
    lines.append(body + "anchors0 = MUST_ANCHOR.get(key) or []")
    lines.append(body + "topics0 = TOPIC_KWS.get(key) or []")
    lines.append(body + "if (not anchors0) and (not topics0):")
    lines.append(body + unit + "return True")
    lines.append("")
    lines.append(body + "title0 = it.get(\"title\") or \"\"")
    lines.append(body + "sn0 = it.get(\"snippet\") or \"\"")
    lines.append(body + "src0 = it.get(\"source\") or \"\"")
    lines.append(body + "txt_ts = \"{0} {1}\".format(title0, sn0)")
    lines.append(body + "txt_all = \"{0} {1} {2}\".format(title0, sn0, src0)")
    lines.append("")
    lines.append(body + "if key == \"au_politics\":")
    lines.append(body + unit + "# 只用 title/snippet 做判断，避免 source(Just In) 等导致误命中")
    lines.append(body + unit + "anchors = []")
    lines.append(body + unit + "for a in (anchors0 or []):")
    lines.append(body + unit + unit + "aa = (a or \"\").strip()")
    lines.append(body + unit + unit + "if not aa:")
    lines.append(body + unit + unit + unit + "continue")
    lines.append(body + unit + unit + "# 中文锚点保留；英文锚点要求长度>=4，避免 act/vic/wa 这类子串误命中")
    lines.append(body + unit + unit + "try:")
    lines.append(body + unit + unit + unit + "is_cjk = _has_cjk(aa)")
    lines.append(body + unit + unit + "except Exception:")
    lines.append(body + unit + unit + unit + "is_cjk = False")
    lines.append(body + unit + unit + "if is_cjk:")
    lines.append(body + unit + unit + unit + "anchors.append(aa)")
    lines.append(body + unit + unit + unit + "continue")
    lines.append(body + unit + unit + "if len(aa) >= 4:")
    lines.append(body + unit + unit + unit + "anchors.append(aa)")
    lines.append("")
    lines.append(body + unit + "topics = topics0")
    lines.append(body + unit + "intl_ban = [\"bangladesh\", \"pakistan\", \"dhaka\", \"sheikh hasina\", \"孟加拉\", \"巴基斯坦\", \"达卡\", \"哈西娜\", \"谢赫\"]")
    lines.append(body + unit + "if _kw_hit(txt_ts, intl_ban):")
    lines.append(body + unit + unit + "return False")
    lines.append("")
    lines.append(body + unit + "# au_politics：必须同时满足 AU anchor + politics topic")
    lines.append(body + unit + "if anchors and (not _kw_hit(txt_ts, anchors)):")
    lines.append(body + unit + unit + "return False")
    lines.append(body + unit + "if topics and (not _kw_hit(txt_ts, topics)):")
    lines.append(body + unit + unit + "return False")
    lines.append(body + unit + "return True")
    lines.append("")
    lines.append(body + "# 其它分类：允许 source 参与 anchor 判断（保持原行为）")
    lines.append(body + "if anchors0 and (not _kw_hit(txt_all, anchors0)):")
    lines.append(body + unit + "return False")
    lines.append(body + "return True")
    lines.append("")
    replacement = "\n".join(lines)

    block2 = block[:m.start()] + replacement + block[m.end():]
    out = src[:i0] + block2 + src[i1:]

    bak = _backup(path, src)
    _write(path, out)
    print("OK: rewrote _passes_anchor_topic with indent-safe method (v3d3).")
    print("Backup:", bak)

if __name__ == "__main__":
    main()
